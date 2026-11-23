"""
拉取 A股牛市流动性条件所需的公开序列，写入 data/bull_liquidity.json。

    python scripts/fetch_bull_liquidity.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from bull_liquidity import backtest_liquidity, evaluate_bear_liquidity, evaluate_bull_liquidity  # noqa: E402


def _import_akshare():
    try:
        import akshare as ak
    except ImportError as exc:
        raise SystemExit("请先安装 AKShare：pip install akshare") from exc
    return ak


def _frame(fetcher, label):
    try:
        frame = fetcher()
    except Exception as exc:
        print(f"{label} 获取失败: {exc}")
        return None
    if frame is None or getattr(frame, "empty", True):
        print(f"{label} 为空")
        return None
    print(f"{label} 列: {list(frame.columns)}")
    return frame


def _column(frame, names):
    for name in names:
        if name in frame.columns:
            return name
    for column in frame.columns:
        text = str(column)
        if any(name in text for name in names):
            return column
    return None


def _normalize_date(value) -> str:
    text = str(value).strip()
    quarters = (
        ("第1-4季度", "12"), ("第1-3季度", "09"), ("第1-2季度", "06"), ("第1季度", "03"),
        ("第四季度", "12"), ("第三季度", "09"), ("第二季度", "06"), ("第一季度", "03"),
        ("四季度", "12"), ("三季度", "09"), ("二季度", "06"), ("一季度", "03"),
        ("第4季度", "12"), ("第3季度", "09"), ("第2季度", "06"),
    )
    for label, month in quarters:
        if label in text:
            year = re.search(r"(\d{4})", text)
            return f"{year.group(1)}-{month}" if year else text[:10]
    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:\.0+)?", text)
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    compact = re.fullmatch(r"(\d{4})(\d{2})(?:\.0+)?", text)
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}"
    match = re.search(r"(\d{4})\D+(\d{1,2})(?:\D+(\d{1,2}))?", text)
    if not match:
        return text[:10]
    year = int(match.group(1))
    month = int(match.group(2))
    day = match.group(3)
    if day:
        return f"{year:04d}-{month:02d}-{int(day):02d}"
    return f"{year:04d}-{month:02d}"


def _points(frame, date_names, value_names):
    if frame is None:
        return []
    date_col = _column(frame, date_names)
    value_col = _column(frame, value_names)
    if date_col is None or value_col is None:
        print(f"缺列 date={date_names} value={value_names}")
        return []
    points = []
    for _, row in frame.iterrows():
        raw = row[value_col]
        if raw is None or str(raw).strip() in ("", "nan", "None", "--"):
            continue
        try:
            value = float(str(raw).replace("%", "").replace(",", ""))
        except ValueError:
            continue
        points.append({"date": _normalize_date(row[date_col]), "value": value})
    points.sort(key=lambda item: item["date"])
    return points


def _nominal_gdp_yoy(frame):
    if frame is None:
        return []
    date_col = _column(frame, ["季度", "日期"])
    level_col = _column(frame, ["国内生产总值-绝对值", "国内生产总值_绝对值"])
    if date_col is None or level_col is None:
        print("GDP 绝对值列不存在，无法计算名义同比")
        return []
    rows = []
    for _, row in frame.iterrows():
        try:
            level = float(str(row[level_col]).replace(",", ""))
        except ValueError:
            continue
        rows.append({"date": _normalize_date(row[date_col]), "level": level})
    rows.sort(key=lambda item: item["date"])
    points = []
    for index, row in enumerate(rows):
        if index < 4 or rows[index - 4]["level"] == 0:
            continue
        yoy = (row["level"] / rows[index - 4]["level"] - 1) * 100
        points.append({"date": row["date"], "value": round(yoy, 4)})
    return points


def _rrr_levels(frame):
    if frame is None:
        return []
    date_col = _column(frame, ["生效日期", "生效时间", "公布时间", "日期", "月份"])
    after_col = _column(frame, ["大型金融机构-调整后", "大型金融机构存款准备金率", "存款准备金率"])
    before_col = _column(frame, ["大型金融机构-调整前"])
    if date_col is None or after_col is None:
        return _points(frame, ["日期", "月份"], ["存款准备金率", "大型金融机构"])
    points = []
    rows = list(frame.iterrows())
    for index, (_, row) in enumerate(rows):
        try:
            after = float(str(row[after_col]).replace("%", ""))
        except ValueError:
            continue
        if index == 0 and before_col is not None:
            try:
                before = float(str(row[before_col]).replace("%", ""))
                points.append({"date": _normalize_date(row[date_col]), "value": before})
            except ValueError:
                pass
        points.append({"date": _normalize_date(row[date_col]), "value": after})
    points.sort(key=lambda item: item["date"])
    return points


def _flow_growth(flow):
    if len(flow) < 24:
        return []
    indexed = {item["date"]: item["value"] for item in flow}
    points = []
    ordered = [item["date"] for item in flow]
    for index, current in enumerate(ordered):
        if index < 23:
            continue
        window = ordered[index - 11:index + 1]
        base = ordered[index - 23:index - 11]
        if len(window) < 12 or len(base) < 12:
            continue
        now = sum(indexed[item] for item in window)
        prev = sum(indexed[item] for item in base)
        if prev <= 0:
            continue
        points.append({"date": current, "value": round((now / prev - 1) * 100, 4)})
    return points


def _newer_series(*candidates):
    available = [(points, name) for points, name in candidates if points]
    if not available:
        return [], ""
    return max(available, key=lambda item: item[0][-1]["date"])


def _credit_yoy(shrzgm):
    stock = _points(shrzgm, ["月份", "日期"], ["社会融资规模存量同比"])
    if stock:
        return stock, "社融存量同比"
    return _flow_growth(_points(shrzgm, ["月份", "日期"], ["社会融资规模增量"])), "社融增量12个月滚动同比"


def _load_sources():
    _import_akshare()
    from akshare.bond.bond_em import bond_zh_us_yield_em
    from akshare.interest_rate.interest_rate_lpr_em import interest_rate_lpr_em
    from akshare.macro.macro_china import (
        macro_china_gdp,
        macro_china_money_supply_em,
        macro_china_new_financial_credit,
        macro_china_reserve_requirement_ratio,
        macro_china_social_financing,
    )
    from akshare.stock.flow.stock_margin_sse import stock_margin_sse
    return {
        "money": lambda: macro_china_money_supply_em(),
        "gdp": lambda: macro_china_gdp(),
        "lpr": lambda: interest_rate_lpr_em(),
        "rrr": lambda: macro_china_reserve_requirement_ratio(),
        "bond": lambda: bond_zh_us_yield_em(start_date="20150101"),
        "social": lambda: macro_china_social_financing(),
        "loan": lambda: macro_china_new_financial_credit(),
        "margin": lambda: stock_margin_sse(
            start_date="20240101",
            end_date=datetime.now().strftime("%Y%m%d"),
        ),
    }


def _nbs_points(kind, path, indicator, period="2016-"):
    from akshare.macro.macro_china_nbs import macro_china_nbs_nation
    frame = macro_china_nbs_nation(kind=kind, path=path, period=period)
    match = next((name for name in frame.index if indicator in str(name)), None)
    if match is None:
        print(f"统计局未找到 {indicator}")
        return []
    points = []
    for column, raw in frame.loc[match].items():
        if raw is None or str(raw).strip() in ("", "nan", "None"):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        points.append({"date": _normalize_date(column), "value": value})
    points.sort(key=lambda item: item["date"])
    return points


def _same_quarter_yoy(levels):
    points = []
    for index in range(4, len(levels)):
        base = levels[index - 4]["value"]
        if not base:
            continue
        points.append({
            "date": levels[index]["date"],
            "value": round((levels[index]["value"] / base - 1) * 100, 4),
        })
    return points


def _official_lpr():
    import requests
    response = requests.get(
        "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis",
        params={"lang": "CN", "pageSize": "18"},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.chinamoney.com.cn/chinese/bklpr/",
        },
        timeout=20,
    )
    response.raise_for_status()
    records = response.json().get("records") or []
    points = [
        {"date": item["showDateCN"], "value": float(item["1Y"])}
        for item in records
        if item.get("1Y") and item.get("showDateCN")
    ]
    points.sort(key=lambda item: item["date"])
    return points


def _official_bond():
    from akshare.bond.bond_china import bond_china_yield
    end = datetime.now()
    start = end - timedelta(days=300)
    frame = bond_china_yield(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    treasury = frame[frame["曲线名称"] == "中债国债收益率曲线"]
    return _points(treasury, ["日期"], ["10年"])


def _margin_with_szse(sse_points):
    if len(sse_points) < 2:
        return sse_points, "两融只有沪市，历史点不够。"
    latest = sse_points[-1]
    latest_day = datetime.strptime(latest["date"][:10], "%Y-%m-%d")
    cutoff = (latest_day - timedelta(days=31)).strftime("%Y-%m-%d")
    previous = None
    for point in sse_points:
        if point["date"][:10] <= cutoff:
            previous = point
    if previous is None:
        return sse_points, "两融只有沪市。"
    try:
        from akshare.stock.flow.stock_margin_szse import stock_margin_szse

        def shenzhen(date_text):
            frame = stock_margin_szse(date_text.replace("-", ""))
            return float(str(frame.iloc[0]["融资余额"]).replace(",", ""))

        latest_sz = shenzhen(latest["date"][:10])
        previous_sz = shenzhen(previous["date"][:10])
    except Exception as exc:
        print(f"深市两融获取失败: {exc}")
        return sse_points, "两融只有沪市，深市这次没有取到。"
    # 上交所余额是元，深交所汇总表是亿元。
    if latest["value"] > latest_sz * 1e7:
        latest_sz *= 1e8
        previous_sz *= 1e8
    elif latest_sz > latest["value"] * 50 or latest["value"] > latest_sz * 50:
        return sse_points, "两融只有沪市，沪深余额单位对不上，没有相加。"
    return [
        {"date": previous["date"], "value": previous["value"] + previous_sz},
        {"date": latest["date"], "value": latest["value"] + latest_sz},
    ], "两融是上交所加深交所融资余额。"


def _fallback_market_series():
    sources = _load_sources()
    money = _frame(sources["money"], "货币供应")
    gdp = _frame(sources["gdp"], "GDP")
    lpr = _frame(sources["lpr"], "LPR")
    bond = _frame(sources["bond"], "中美国债收益率")
    return {
        "m2_yoy": _points(money, ["月份", "日期"], ["货币和准货币(M2)-同比增长", "M2同比增长"]),
        "m1_yoy": _points(money, ["月份", "日期"], ["货币(M1)-同比增长", "M1同比增长"]),
        "nominal_gdp_yoy": _nominal_gdp_yoy(gdp),
        "lpr_1y": _points(lpr, ["日期", "TRADE_DATE"], ["1年期LPR", "LPR1Y"]),
        "cn_10y": _points(bond, ["日期"], ["中国国债收益率10年"]),
    }


def fetch_series():
    provenance = []
    fallback = None

    def market(key):
        nonlocal fallback
        if fallback is None:
            fallback = _fallback_market_series()
        return fallback.get(key) or []

    try:
        m2 = _nbs_points("月度数据", "金融 > 货币供应量", "货币和准货币(M2)供应量__同比增长")
        m1 = _nbs_points("月度数据", "金融 > 货币供应量", "货币(M1)供应量__同比增长")
        provenance.append("M1、M2：国家统计局「金融 > 货币供应量」。")
    except Exception as exc:
        print(f"统计局货币供应失败: {exc}")
        m2, m1 = market("m2_yoy"), market("m1_yoy")
        provenance.append("M1、M2：统计局失败，退回东方财富。")

    try:
        gdp_levels = _nbs_points(
            "季度数据", "国民经济核算 > 国内生产总值 (现价)", "国内生产总值当季值", period="2012-",
        )
        gdp = _same_quarter_yoy(gdp_levels)
        provenance.append("名义 GDP：国家统计局现价当季值，同比按四个季度前同季计算。")
    except Exception as exc:
        print(f"统计局 GDP 失败: {exc}")
        gdp = market("nominal_gdp_yoy")
        provenance.append("名义 GDP：统计局失败，退回东方财富累计额。")

    try:
        lpr = _official_lpr()
        provenance.append("一年期 LPR：中国货币网。")
    except Exception as exc:
        print(f"中国货币网 LPR 失败: {exc}")
        lpr = market("lpr_1y")
        provenance.append("一年期 LPR：货币网失败，退回东方财富。")

    try:
        bond = _official_bond()
        provenance.append("10 年国债：中债国债收益率曲线。")
    except Exception as exc:
        print(f"中债收益率失败: {exc}")
        bond = market("cn_10y")
        provenance.append("10 年国债：中债失败，退回东方财富。")

    try:
        profit = _nbs_points("月度数据", "工业 > 工业企业主要经济指标", "利润总额累计增长")
        provenance.append("工业企业利润：国家统计局利润总额累计增长。")
    except Exception as exc:
        print(f"统计局利润失败: {exc}")
        profit = []
        provenance.append("工业企业利润：统计局这次没有取到。")

    rrr_frame = _frame(_load_sources()["rrr"], "存款准备金率")
    provenance.append("存款准备金率：没有稳定的央行开放接口，仍用东方财富整理的调整记录。")

    loan = _frame(_load_sources()["loan"], "新增人民币贷款")
    social = _frame(_load_sources()["social"], "社融")
    social_points, social_name = _credit_yoy(social)
    loan_points = _flow_growth(_points(loan, ["月份", "日期"], ["当月"]))
    credit_points, credit_name = _newer_series(
        (social_points, social_name),
        (loan_points, "新增人民币贷款12个月滚动同比"),
    )
    provenance.append("信贷：东方财富只有新增人民币贷款，没有社融存量同比。这里用新增贷款 12 个月滚动同比。")

    sse = _points(_frame(_load_sources()["margin"], "沪市两融"), ["信用交易日期", "日期"], ["融资余额"])
    margin, margin_note = _margin_with_szse(sse)
    provenance.append(margin_note)

    series = {
        "m2_yoy": m2,
        "m1_yoy": m1,
        "nominal_gdp_yoy": gdp,
        "lpr_1y": lpr,
        "rrr": _rrr_levels(rrr_frame),
        "cn_10y": bond,
        "credit_yoy": credit_points,
        "industrial_profit_yoy": profit,
        "margin_balance": margin,
        "north_money": [],
    }
    return series, {
        "credit_name": credit_name,
        "sources": provenance,
        "earnings_note": "",
    }


def _gc001_series():
    path = os.path.join(ROOT, "data", "public_snapshot.json")
    try:
        with open(path, encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    point = ((snapshot.get("china_core") or {}).get("cn_repo_gc001")) or {}
    if point.get("value") is None:
        return []
    return [{"date": str(point.get("date") or "")[:10], "value": float(point["value"])}]


def _hs300_monthly():
    """拉取沪深300历史收盘价（用于牛熊流动性回测对齐）。"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000300")
        if df is None or df.empty:
            return []
        return _points(df, ["date", "日期"], ["close", "收盘"])
    except Exception as exc:
        print(f"沪深300历史拉取失败（不影响主计算）: {exc}")
        return []


def main():
    series, notes = fetch_series()
    series["gc001"] = _gc001_series()
    report = evaluate_bull_liquidity(series)
    bear = evaluate_bear_liquidity(series)
    credit_name = notes.get("credit_name")
    if credit_name:
        for item in report["conditions"] + bear["conditions"]:
            if item["id"] in (4, 8):
                item["detail"] = f"{credit_name}。{item['detail']}"
    report["bear"] = bear
    report["history"] = backtest_liquidity(series, hs300=_hs300_monthly(), max_months=96)
    report["updated_at"] = datetime.now().isoformat(timespec="seconds")
    report["source"] = "国家统计局 / 中国货币网 / 中债 / 交易所"
    report["notes"] = notes
    report["latest"] = {
        key: (values[-1] if values else None)
        for key, values in series.items()
    }
    path = os.path.join(ROOT, "data", "bull_liquidity.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"已写入 {path}")
    print("牛市", report["stage"], report["met_count"])
    for item in report["conditions"]:
        print(f"{item['id']}. {item['status']:7} {item['name']} | {item['detail']}")
    print("熊市", bear["stage"], bear["met_count"])
    for item in bear["conditions"]:
        print(f"{item['id']}. {item['status']:7} {item['name']} | {item['detail']}")


if __name__ == "__main__":
    main()
