"""
宏观仪表盘 FastAPI 后端
- 优先读取本地公开数据快照（data/public_snapshot.json）
- 并发补充东方财富美国宏观数据、可选 FRED / yfinance / AKShare 实时数据
- 统一由 signal_engine 计算 RISK ON/OFF 与仓位建议
- 内置 TTL 缓存，避免重复串行外网请求导致超时
"""

import os
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, Callable

import requests
import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from backend.signal_engine import calculate_risk_score
except ImportError:
    from signal_engine import calculate_risk_score

app = FastAPI(title="宏观仪表盘 API", version="2.1.0")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=(CORS_ORIGINS != ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 配置与路径 ============
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))

_CACHE: Dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: int, loader: Callable[[], Any], force_refresh: bool = False) -> Any:
    now = time.monotonic()
    if not force_refresh and key in _CACHE:
        expires_at, value = _CACHE[key]
        if now < expires_at:
            return value
    value = loader()
    _CACHE[key] = (now + ttl, value)
    return value


def clear_cache() -> None:
    _CACHE.clear()


# ============ FRED 数据获取 ============
# value_scale 用于将 FRED 原始单位统一换算为本系统标准单位
FRED_SERIES = {
    "vix": ("VIXCLS", 1.0, False),
    "move_idx": ("MOVE", 1.0, False),
    "us_10y_yield": ("DGS10", 1.0, False),
    "us_2y_yield": ("DGS2", 1.0, False),
    "us_core_pce_yy": ("PCEPILFE", 1.0, True),     # 指数 -> 同比 %
    "us_cpi_yy": ("CPIAUCSL", 1.0, True),          # 指数 -> 同比 %
    "fed_balance_sheet": ("WALCL", 1e6, False),    # 百万美元 -> 美元
    "on_rrp_balance": ("RRPONTSYD", 1e9, False),   # 十亿美元 -> 美元
    "fed_funds_rate": ("FEDFUNDS", 1.0, False),
    "dxy_idx": ("DTWEXBGS", 1.0, False),
    "hy_spread_oas": ("BAMLH0A0HYM2", 100.0, False),  # 百分点 -> bp
    "ted_spread": ("TEDRATE", 100.0, False),          # 百分点 -> bp
    "spx": ("SP500", 1.0, False),
    "btc_usd": ("CBBTCUSD", 1.0, False),
}


def fetch_fred_series(series_id: str, limit: int = 30) -> list:
    """从 FRED 获取历史时间序列（升序）。"""
    if not FRED_API_KEY:
        return []
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "error" not in data and "observations" in data:
            return [
                {
                    "date": obs["date"],
                    "value": float(obs["value"]) if obs.get("value") not in (None, ".", "") else None,
                }
                for obs in reversed(data["observations"])
            ]
    except Exception as e:
        print(f"FRED history error for {series_id}: {e}")
    return []


def fetch_fred(series_id: str, scale: float = 1.0, yoy_from_index: bool = False) -> Optional[float]:
    """从 FRED 获取单个指标最新值，自动做单位换算或同比计算。"""
    if not FRED_API_KEY:
        return None
    if yoy_from_index:
        series = [p for p in fetch_fred_series(series_id, limit=15) if p["value"] is not None]
        if len(series) >= 13 and series[-13]["value"]:
            yoy = (series[-1]["value"] / series[-13]["value"] - 1.0) * 100.0
            return round(yoy, 2)
        return None

    series = [p for p in fetch_fred_series(series_id, limit=5) if p["value"] is not None]
    if not series:
        return None
    return round(series[-1]["value"] * scale, 4)


def fetch_cboe_vix_history(days: int = 30) -> list:
    """无 FRED_API_KEY 时从 CBOE 公开 CSV 拉取 VIX 日频历史。"""
    try:
        session = requests.Session()
        session.trust_env = False
        session.headers["User-Agent"] = "Mozilla/5.0"
        resp = session.get(
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
            timeout=15,
        )
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()[1:]
        points = []
        for line in lines[-max(days, 1):]:
            parts = line.split(",")
            if len(parts) < 5:
                continue
            month, day, year = parts[0].split("/")
            points.append({
                "date": f"{year}-{month.zfill(2)}-{day.zfill(2)}",
                "value": round(float(parts[4]), 2),
            })
        return points
    except Exception as e:
        print(f"CBOE VIX history error: {e}")
        return []


# ============ yfinance / AKShare 数据获取 ============
YF_SYMBOLS = {
    "spx": "SPY",
    "hs300": "000300.SS",
    "hsi": "^HSI",
    "nk225": "^N225",
    "gold_spot": "GC=F",
    "wti_oil": "CL=F",
    "usd_cnh": "CNHF=X",
    "usd_jpy": "JPY=X",
}


def fetch_akshare(key: str) -> Optional[dict]:
    """akshare 备援获取资产价格（仅覆盖沪深300、恒生指数）。"""
    try:
        import akshare as ak
    except ImportError:
        return None

    try:
        if key == "hs300":
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if not df.empty:
                row = df.iloc[-1]
                return {"price": round(float(row["close"]), 2), "currency": "CNY"}
        elif key == "hsi":
            df = ak.stock_hk_index_daily_sina(symbol="HSI")
            if not df.empty:
                row = df.iloc[-1]
                return {"price": round(float(row["close"]), 2), "currency": "HKD"}
    except Exception as e:
        print(f"akshare fallback error for {key}: {e}")
    return None


def fetch_yfinance(symbol: str) -> Optional[dict]:
    """从 yfinance 获取资产价格。"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = info.get("last_price") or info.get("previous_close")
        currency = str(info.get("currency", "USD"))
        return {"price": round(float(price), 2), "currency": currency} if price else None
    except Exception as e:
        print(f"yfinance fetch error for {symbol}: {e}")
    return None


# ============ 趋势计算 ============
def get_trend(
    current: float,
    history: list,
    threshold_pct: float = 2.0,
    invert: bool = False,
) -> str:
    """
    计算趋势（基于近30日数据）。
    invert=True 用于美债收益率代理中美利差（美债升 -> 中美利差走阔）。
    """
    if not history or len(history) < 5:
        return "持平"
    values = [h["value"] for h in history if h.get("value") is not None]
    if len(values) < 5:
        return "持平"
    avg_past = sum(values[:10]) / min(10, len(values))
    if not avg_past:
        return "持平"
    change_pct = (current - avg_past) / abs(avg_past) * 100.0
    if invert:
        change_pct = -change_pct
    if change_pct > threshold_pct:
        return "收窄"
    if change_pct < -threshold_pct:
        return "走阔"
    return "持平"


# ============ 本地 JSON 快照读取 ============
def load_public_snapshot() -> dict:
    """读取仪表盘本地公开数据快照。"""
    path = os.path.join(DATA_DIR, "public_snapshot.json")
    if not os.path.exists(path):
        return {"status": "missing"}
    try:
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        report["status"] = "ok"
        return report
    except (OSError, json.JSONDecodeError) as e:
        print(f"Failed to load public_snapshot.json: {e}")
        return {"status": "error"}


def load_bull_liquidity_report() -> dict:
    """读取本地计算好的 A股牛熊流动性条件。"""
    path = os.path.join(DATA_DIR, "bull_liquidity.json")
    if not os.path.exists(path):
        return {
            "status": "missing",
            "stage": "未计算",
            "stage_detail": "还没有本地数据。在项目目录运行 python scripts/fetch_bull_liquidity.py",
            "met_count": 0,
            "conditions": [],
        }
    try:
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        report["status"] = "ok"
        return report
    except (OSError, json.JSONDecodeError) as e:
        print(f"Failed to load bull_liquidity.json: {e}")
        return {
            "status": "error",
            "stage": "读取失败",
            "stage_detail": "本地流动性数据格式异常，请重新拉取。",
            "met_count": 0,
            "conditions": [],
        }


# ============ 东方财富美国宏观 ============
EM_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_USA_IDS = {
    "us_ism_pmi": "EMG00002790",
    "us_cpi_yy": "EMG00000733",
    "fed_funds_low": "EMG00358536",
    "fed_funds_high": "EMG00342250",
}


def latest_eastmoney_usa(indicator_id: str) -> Optional[dict]:
    """东方财富美国指标。未公布的当期 VALUE 为空，跳到最近一条有数字的记录。"""
    params = {
        "reportName": "RPT_ECONOMICVALUE_USA",
        "columns": "ALL",
        "filter": f'(INDICATOR_ID="{indicator_id}")',
        "pageSize": "8",
        "pageNumber": "1",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        resp = requests.get(EM_DATACENTER, params=params, timeout=12)
        resp.raise_for_status()
        rows = (resp.json().get("result") or {}).get("data") or []
        for row in rows:
            if row.get("VALUE") is None:
                continue
            return {
                "value": float(row["VALUE"]),
                "date": row.get("REPORT_DATE_CH") or "",
                "name": row.get("INDICATOR_NAME") or "",
                "source": "东方财富",
            }
    except Exception as e:
        print(f"EastMoney USA fetch error for {indicator_id}: {e}")
    return None


def eastmoney_global_macro() -> dict:
    """并发获取东方财富美国 ISM PMI、CPI 与联邦基金利率目标区间。"""
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {key: pool.submit(latest_eastmoney_usa, ind_id) for key, ind_id in EM_USA_IDS.items()}
        results = {key: fut.result() or {} for key, fut in futures.items()}

    ism = results["us_ism_pmi"]
    cpi = results["us_cpi_yy"]
    low = results["fed_funds_low"]
    high = results["fed_funds_high"]
    funds = None
    if low.get("value") is not None and high.get("value") is not None:
        funds = {
            "value": low["value"],
            "high": high["value"],
            "range": f"{low['value']:.2f}–{high['value']:.2f}",
            "date": low.get("date") or high.get("date"),
            "source": "东方财富",
            "name": "联邦基金利率目标区间",
        }
    return {
        "us_ism_pmi": ({**ism, "unit": ""} if ism else None),
        "us_cpi_yy": ({**cpi, "unit": "%"} if cpi else None),
        "fed_funds_rate": funds,
        "source_note": "ISM、美国 CPI、联邦基金利率目标区间来自东方财富。核心PCE来自美国商务部，美联储资产负债表来自 H.4.1。",
    }


def _merge_section(base: Optional[dict], patch: Optional[dict]) -> dict:
    merged = dict(base or {})
    for key, item in (patch or {}).items():
        if item is None:
            continue
        if isinstance(item, dict) and item.get("value") is None and item.get("spread") is None and item.get("range") is None:
            continue
        if isinstance(item, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **item}
        else:
            merged[key] = item
    return merged


def _build_dashboard_payload() -> dict:
    """构建统一全景仪表盘响应：以本地公开快照为基底，叠加实时东方财富与可选 FRED。"""
    now = datetime.now()
    snapshot = load_public_snapshot()
    has_snapshot = snapshot.get("status") == "ok"

    china_core = dict(snapshot.get("china_core") or {}) if has_snapshot else {}
    global_macro = dict(snapshot.get("global_macro") or {}) if has_snapshot else {}
    fx_liquidity = dict(snapshot.get("fx_liquidity") or {}) if has_snapshot else {}
    assets = dict(snapshot.get("assets") or {}) if has_snapshot else {}
    risk_monitor = dict(snapshot.get("risk_monitor") or {}) if has_snapshot else {}

    # 并发补充东方财富美国宏观数据（无 FRED Key 时也能拿到 ISM / CPI / 联邦基金利率）
    em_macro = eastmoney_global_macro()
    global_macro = _merge_section(global_macro, {
        k: em_macro.get(k) for k in ("us_ism_pmi", "us_cpi_yy", "fed_funds_rate")
    })
    if em_macro.get("source_note"):
        global_macro["source_note"] = em_macro["source_note"]

    # 若配置了 FRED_API_KEY，并发补齐仍然缺失的 FRED 字段
    spread_history = []
    if FRED_API_KEY:
        missing_fred = {}
        section_map = {
            "vix": risk_monitor,
            "move_idx": risk_monitor,
            "hy_spread_oas": risk_monitor,
            "ted_spread": risk_monitor,
            "us_10y_yield": global_macro,
            "us_2y_yield": global_macro,
            "us_core_pce_yy": global_macro,
            "us_cpi_yy": global_macro,
            "fed_balance_sheet": global_macro,
            "on_rrp_balance": global_macro,
            "fed_funds_rate": global_macro,
            "dxy_idx": fx_liquidity,
            "spx": assets,
            "btc_usd": assets,
        }
        for key, target_section in section_map.items():
            existing = target_section.get(key)
            if not isinstance(existing, dict) or existing.get("value") is None:
                missing_fred[key] = FRED_SERIES[key]

        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {
                key: pool.submit(fetch_fred, sid, scale, is_yoy)
                for key, (sid, scale, is_yoy) in missing_fred.items()
            }
            hist_fut = pool.submit(fetch_fred_series, "DGS10", 30)
            for key, fut in futs.items():
                val = fut.result()
                if val is not None:
                    section_map[key][key] = {
                        "value": val,
                        "date": now.date().isoformat(),
                        "source": "FRED",
                    }
            spread_history = hist_fut.result()

        if global_macro.get("us_10y_yield") and not (assets.get("us_10y_yield") or {}).get("value"):
            assets["us_10y_yield"] = global_macro["us_10y_yield"]

    # 计算中美利差 (bp)
    cn_10y = (china_core.get("cn_10y_yield") or {}).get("value")
    us_10y = (assets.get("us_10y_yield") or global_macro.get("us_10y_yield") or {}).get("value")
    us_2y = (global_macro.get("us_2y_yield") or {}).get("value")
    cn_us_spread = round((cn_10y - us_10y) * 100.0, 1) if (cn_10y is not None and us_10y is not None) else None
    if cn_us_spread is not None:
        fx_liquidity["cn_us_10y_spread"] = {
            "value": cn_us_spread,
            "unit": "bp",
            "date": (china_core.get("cn_10y_yield") or {}).get("date") or (assets.get("us_10y_yield") or {}).get("date") or "",
            "source": "10Y中债减美债",
        }

    # 计算美债 10Y - 2Y 期限利差 (bp)
    if us_10y is not None and us_2y is not None:
        us_curve_bp = round((us_10y - us_2y) * 100.0, 1)
        curve_date = (global_macro.get("us_10y_yield") or {}).get("date") or (global_macro.get("us_2y_yield") or {}).get("date") or ""
        fx_liquidity["us_10y_2y_spread"] = {
            "value": us_curve_bp,
            "unit": "bp",
            "date": curve_date,
            "source": "10Y美债减2Y美债",
        }

    # 计算沪深300 股债性价比 ERP = 100 / PE_TTM - 10Y中债收益率（仅在快照已有 PE 时计算，不做假数据）
    hs300_pe = (china_core.get("hs300_pe") or {}).get("value")
    if hs300_pe and cn_10y is not None and hs300_pe > 0:
        erp_val = round(100.0 / hs300_pe - cn_10y, 2)
        china_core["hs300_erp"] = {
            "value": erp_val,
            "pe": round(float(hs300_pe), 2),
            "unit": "%",
            "date": (china_core.get("hs300_pe") or {}).get("date") or (china_core.get("cn_10y_yield") or {}).get("date") or "",
            "source": "1/PE减10Y中债",
        }

    # 统一信号合成
    m1_m2_item = china_core.get("cn_m1_m2_spread") or {}
    m1_m2_spread = m1_m2_item.get("spread")
    m1_m2_spread_6m = m1_m2_item.get("spread_6m")
    vix = (risk_monitor.get("vix") or {}).get("value")
    credit_spread = (risk_monitor.get("hy_spread_oas") or {}).get("value")
    north_money_3d = (china_core.get("north_money_3d") or {}).get("value")

    cn_us_trend = (
        get_trend(us_10y, spread_history, invert=True)
        if (us_10y is not None and spread_history)
        else "持平"
    )

    score_result = calculate_risk_score(
        cn_us_spread=cn_us_spread,
        cn_us_spread_trend=cn_us_trend,
        m1_m2_spread=m1_m2_spread,
        m1_m2_spread_6m=m1_m2_spread_6m,
        vix=vix,
        north_money_3d=north_money_3d,
        credit_spread=credit_spread,
    )

    factor_details_out = {
        f.name: {
            "name_cn": f.name_cn,
            "value": f.value,
            "signal": f.signal,
            "weight": f.weight,
            "contribution": f.contribution,
            "view": f.view,
            "narrative": f.narrative,
            "trend": f.trend,
        }
        for f in score_result.factor_details
    }

    snapshot_updated = snapshot.get("updated_at") if has_snapshot else None
    data_date = (snapshot_updated[:10] if snapshot_updated else now.date().isoformat())

    return {
        "meta": {
            "updated_at": now.isoformat(timespec="seconds"),
            "public_updated_at": snapshot_updated,
            "data_date": data_date,
            "status": "success" if score_result.confidence > 30 else "degraded",
        },
        "overview": {
            "bias": score_result.bias,
            "confidence": score_result.confidence,
            "score": score_result.score,
            "label": score_result.label,
            "primary_driver": score_result.primary_driver,
            "suggestions": score_result.suggestions,
            "narrative": score_result.narrative,
            "factor_details": factor_details_out,
        },
        "china_core": china_core,
        "global_macro": global_macro,
        "fx_liquidity": fx_liquidity,
        "assets": assets,
        "risk_monitor": risk_monitor,
        "events": build_macro_calendar(now.date(), days=30),
    }


# ============ 宏观经济日历（含官方央行议息会议 + 常规数据发布窗口） ============
# 官方日程（利率决议公布日，覆盖 2026–2027）
CENTRAL_BANK_MEETINGS = [
    # 美联储 FOMC（标 SEP 的含经济预测与点阵图）
    ("2026-01-28", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2026-03-18", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2026-04-29", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2026-06-17", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2026-07-29", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2026-09-16", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2026-10-28", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2026-12-09", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2027-01-27", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2027-03-17", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2027-04-28", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2027-06-09", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2027-07-28", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    ("2027-09-15", "US", "美联储 FOMC 议息决议（含点阵图）", "官方日程 · 附经济预测 SEP 与发布会"),
    ("2027-11-17", "US", "美联储 FOMC 议息决议", "官方日程 · 美东 14:00 公布利率决议"),
    # 日本央行 BOJ（影响日元套息交易与 USD/JPY）
    ("2026-01-23", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 关注利率与套息交易波动"),
    ("2026-03-19", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与 USD/JPY"),
    ("2026-04-28", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2026-06-16", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与 USD/JPY"),
    ("2026-07-31", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2026-09-18", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与 USD/JPY"),
    ("2026-10-30", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2026-12-18", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与套息交易波动"),
    ("2027-01-22", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2027-03-18", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与 USD/JPY"),
    ("2027-04-28", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2027-06-11", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与 USD/JPY"),
    ("2027-07-22", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2027-09-22", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与 USD/JPY"),
    ("2027-10-29", "JP", "日本央行 BOJ 议息决议（含展望报告）", "官方日程 · 附季度经济与通胀展望"),
    ("2027-12-17", "JP", "日本央行 BOJ 议息决议", "官方日程 · 关注利率与套息交易波动"),
    # 欧洲央行 ECB
    ("2026-02-05", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2026-03-19", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2026-04-30", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2026-06-11", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2026-07-23", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2026-09-10", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2026-10-29", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2026-12-17", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2027-02-04", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2027-03-18", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2027-04-29", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2027-06-10", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2027-07-22", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2027-09-09", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
    ("2027-10-28", "EU", "欧洲央行 ECB 议息决议", "官方日程 · 欧洲中部时间 14:15 公布"),
    ("2027-12-16", "EU", "欧洲央行 ECB 议息决议（含经济预测）", "官方日程 · 附宏观经济预测"),
]


def _next_weekday(d: date) -> date:
    if d.weekday() == 5:
        return d + timedelta(days=2)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    offset = (4 - d.weekday()) % 7
    return d + timedelta(days=offset)


def _last_friday(year: int, month: int) -> date:
    d = _month_end(year, month)
    offset = (d.weekday() - 4) % 7
    return d - timedelta(days=offset)


def build_macro_calendar(today: Optional[date] = None, days: int = 30) -> list:
    """生成未来 N 天内全球主要央行议息会议与中美核心宏观数据的发布窗口。"""
    base = today or datetime.now().date()
    end = base + timedelta(days=max(days, 1))
    months_to_check = {(base.year, base.month), (end.year, end.month)}
    mid = base + timedelta(days=15)
    months_to_check.add((mid.year, mid.month))

    events = []
    # 1. 官方央行议息会议
    for date_str, region, title, note in CENTRAL_BANK_MEETINGS:
        ev_date = date.fromisoformat(date_str)
        if base <= ev_date <= end:
            events.append({
                "date": date_str,
                "days_away": (ev_date - base).days,
                "region": region,
                "category": "rate",
                "title": title,
                "impact": "高",
                "note": note,
            })

    # 2. 中美月度核心数据常规发布窗口
    for year, month in sorted(months_to_check):
        candidates = [
            (_next_weekday(date(year, month, 1)), "CN", "财新制造业 PMI", "中", "常规月初首工作日公布"),
            (_first_friday(year, month), "US", "美国非农就业 (NFP)", "高", "常规每月首个周五公布"),
            (_next_weekday(date(year, month, 9)), "CN", "中国 CPI / PPI 同比", "高", "常规每月 9–10 日公布"),
            (_next_weekday(date(year, month, 12)), "CN", "中国社融 / M1 / M2", "高", "常规每月 10–15 日窗口"),
            (_next_weekday(date(year, month, 13)), "US", "美国 CPI 通胀数据", "高", "常规每月中旬公布"),
            (_next_weekday(date(year, month, 20)), "CN", "中国 1Y / 5Y LPR 报价", "高", "每月 20 日（遇节假日顺延）"),
            (_last_friday(year, month), "US", "美国核心 PCE 同比", "高", "常规每月末最后一个周五"),
            (_month_end(year, month), "CN", "中国官方制造业 PMI", "高", "常规每月末最后一日公布"),
        ]
        for ev_date, region, title, impact, note in candidates:
            if base <= ev_date <= end:
                events.append({
                    "date": ev_date.isoformat(),
                    "days_away": (ev_date - base).days,
                    "region": region,
                    "category": "data",
                    "title": title,
                    "impact": impact,
                    "note": note,
                })
    events.sort(key=lambda item: (item["date"], 0 if item["category"] == "rate" else 1, item["region"], item["title"]))
    return events


# ============ API 端点 ============

@app.get("/api/v1/dashboard")
def get_dashboard(refresh: bool = False):
    """统一全景接口（带 TTL 缓存，传 ?refresh=true 可强制刷新）。"""
    return _cached("dashboard", CACHE_TTL_SECONDS, _build_dashboard_payload, force_refresh=refresh)


@app.get("/api/v1/overview")
def get_overview(refresh: bool = False):
    """顶层概览：RISK ON/OFF + 核心信号"""
    return get_dashboard(refresh=refresh)["overview"]


@app.get("/api/v1/china-core")
def get_china_core(refresh: bool = False):
    """中国内核数据"""
    return get_dashboard(refresh=refresh)["china_core"]


@app.get("/api/v1/global-macro")
def get_global_macro(refresh: bool = False):
    """全球宏观数据"""
    return get_dashboard(refresh=refresh)["global_macro"]


@app.get("/api/v1/fx-liquidity")
def get_fx_liquidity(refresh: bool = False):
    """汇率与流动性（优先用快照，缺项再用 yfinance 补齐）"""
    fx = dict(get_dashboard(refresh=refresh)["fx_liquidity"])
    for key, symbol in (("usd_cnh", "CNHF=X"), ("usd_jpy", "JPY=X")):
        if not (fx.get(key) or {}).get("value"):
            yf_item = fetch_yfinance(symbol)
            if yf_item:
                fx[key] = {"value": yf_item["price"], "unit": "", "source": "yfinance"}
    return fx


@app.get("/api/v1/assets")
def get_assets(refresh: bool = False):
    """全球核心资产行情"""
    return get_dashboard(refresh=refresh)["assets"]


@app.get("/api/v1/risk")
def get_risk(refresh: bool = False):
    """波动率与风险指标"""
    return get_dashboard(refresh=refresh)["risk_monitor"]


@app.get("/api/v1/events")
def get_events(days: int = 30):
    """未来央行议息会议与宏观数据常规发布窗口"""
    safe_days = max(7, min(days, 90))
    return {"events": build_macro_calendar(datetime.now().date(), days=safe_days)}


@app.get("/api/v1/vix-history")
def get_vix_history(days: int = 30, refresh: bool = False):
    """VIX 历史数据（有 FRED Key 走 FRED，否则走 CBOE 公开 CSV）。"""
    safe_days = max(5, min(days, 365))

    def _load():
        if FRED_API_KEY:
            data = fetch_fred_series("VIXCLS", safe_days)
            if data:
                return {"data": data, "source": "FRED"}
        return {"data": fetch_cboe_vix_history(safe_days), "source": "CBOE"}

    return _cached(f"vix_history_{safe_days}", CACHE_TTL_SECONDS, _load, force_refresh=refresh)


@app.get("/api/v1/public-snapshot")
def get_public_snapshot():
    """本地公开数据快照。"""
    return load_public_snapshot()


@app.get("/api/v1/bull-liquidity")
def get_bull_liquidity():
    """A股牛熊流动性 8 条条件。"""
    return load_bull_liquidity_report()


_BULL_REFRESH_LOCK = threading.Lock()
_BULL_REFRESH_STATE: Dict[str, Any] = {
    "running": False,
    "last_error": None,
    "started_at": None,
    "finished_at": None,
}


def _run_bull_liquidity_script() -> None:
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    script = os.path.join(root, "scripts", "fetch_bull_liquidity.py")
    err_msg = None
    try:
        proc = subprocess.run(
            [sys.executable, script],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if proc.returncode != 0:
            err_msg = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()[-300:]
    except Exception as exc:
        err_msg = str(exc)
    finally:
        with _BULL_REFRESH_LOCK:
            _BULL_REFRESH_STATE["running"] = False
            _BULL_REFRESH_STATE["last_error"] = err_msg
            _BULL_REFRESH_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")


@app.post("/api/v1/bull-liquidity/refresh")
def trigger_bull_liquidity_refresh():
    """后台异步运行 fetch_bull_liquidity.py 生成最新条件与历史回测曲线。"""
    with _BULL_REFRESH_LOCK:
        if _BULL_REFRESH_STATE["running"]:
            return {"started": False, **_BULL_REFRESH_STATE}
        _BULL_REFRESH_STATE["running"] = True
        _BULL_REFRESH_STATE["last_error"] = None
        _BULL_REFRESH_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
        threading.Thread(target=_run_bull_liquidity_script, daemon=True).start()
        return {"started": True, **_BULL_REFRESH_STATE}


@app.get("/api/v1/bull-liquidity/status")
def get_bull_liquidity_status():
    """查询牛熊流动性回测后台生成状态。"""
    report = load_bull_liquidity_report()
    has_history = len(report.get("history") or []) >= 3
    with _BULL_REFRESH_LOCK:
        return {**_BULL_REFRESH_STATE, "has_history": has_history}


def format_daily_brief_markdown(dashboard: dict, bull: Optional[dict] = None) -> str:
    """将全景数据与牛熊流动性报告格式化为 SPEC §7 三段式 Markdown 简报。"""
    meta = dashboard.get("meta") or {}
    overview = dashboard.get("overview") or {}
    suggestions = overview.get("suggestions") or {}
    factors = overview.get("factor_details") or {}
    date_label = meta.get("data_date") or datetime.now().date().isoformat()
    bias = overview.get("bias") or "NEUTRAL"
    bias_text = (
        "偏进攻 (RISK ON)" if bias == "RISK_ON"
        else "偏防守 (RISK OFF)" if bias == "RISK_OFF"
        else "中性 (NEUTRAL)"
    )

    lines = [
        f"📋 每日宏观简报 · {date_label}",
        "",
        f"{bias_text} · {overview.get('label', '--')} · 总分 {overview.get('score', '--')} / 2.0 · "
        f"置信度 {overview.get('confidence', '--')}% · 权益建议仓位 {suggestions.get('equity', '--')}%",
        "",
        f"核心观点：{overview.get('narrative', '暂无')}",
        "",
        "📌 逻辑拆解",
        "| 因子 | 信号 | 变化 | 简评 |",
        "|---|---|---|---|",
    ]
    for f in factors.values():
        sig = f.get("signal")
        sig_str = f"+{sig}" if isinstance(sig, (int, float)) and sig > 0 else str(sig if sig is not None else "--")
        lines.append(
            f"| {f.get('name_cn', '--')} | {sig_str} | {f.get('trend', '--')} | "
            f"{f.get('view', '--')}：{f.get('narrative', '')} |"
        )

    drivers = "、".join(overview.get("primary_driver") or []) or "暂无"
    lines.extend([
        "",
        f"主要驱动：{drivers}",
        "",
        "🎯 配置建议",
        f"- 权益：{suggestions.get('equity', '--')}%",
        f"- 债券：{suggestions.get('bond', '--')}%",
        f"- 黄金：{suggestions.get('gold', '--')}%",
        f"- 现金：{suggestions.get('cash', '--')}%",
    ])

    if bull and bull.get("stage"):
        bear = bull.get("bear") or {}
        lines.extend([
            "",
            f"🧭 A股流动性阶段：牛市「{bull.get('stage')}」({bull.get('met_count', 0)}/8) · "
            f"熊市「{bear.get('stage', '--')}」({bear.get('met_count', 0)}/8)",
        ])

    lines.extend([
        "",
        f"*数据日期：{date_label} · 来源：公开宏观数据快照 / 东方财富 / CBOE*",
    ])
    return "\n".join(lines)


@app.get("/api/v1/brief")
def get_daily_brief(refresh: bool = False):
    """每日宏观简报（返回 Markdown 文本与核心摘要，便于机器人/定时推送调用）。"""
    dashboard = get_dashboard(refresh=refresh)
    bull = load_bull_liquidity_report()
    return {
        "data_date": (dashboard.get("meta") or {}).get("data_date"),
        "bias": (dashboard.get("overview") or {}).get("bias"),
        "score": (dashboard.get("overview") or {}).get("score"),
        "label": (dashboard.get("overview") or {}).get("label"),
        "markdown": format_daily_brief_markdown(dashboard, bull),
    }


@app.get("/api/v1/health")
def health_check():
    """健康检查"""
    snapshot = load_public_snapshot()
    bull = load_bull_liquidity_report()
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "fred_connected": bool(FRED_API_KEY),
        "public_snapshot": snapshot.get("status"),
        "bull_liquidity": bull.get("status"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
