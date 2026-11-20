"""
把仪表盘里还能从公开接口拿到的序列写成 data/public_snapshot.json。

    python scripts/fetch_public_snapshot.py
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import time
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "public_snapshot.json")
EM = "https://datacenter-web.eastmoney.com/api/data/v1/get"



_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    "January": 1, "February": 2, "March": 3, "April": 4, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


def _point(value, date, source, **extra):
    if value is None:
        return None
    item = {"value": value, "date": date or "", "source": source}
    item.update(extra)
    return item


def em_latest(report, value_key):
    response = requests.get(
        EM,
        params={
            "reportName": report,
            "columns": "ALL",
            "pageSize": "6",
            "pageNumber": "1",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
        timeout=20,
    )
    rows = (response.json().get("result") or {}).get("data") or []
    for row in rows:
        raw = row.get(value_key)
        if raw is None or str(raw).strip() in ("", "None"):
            continue
        return _point(float(raw), row.get("TIME") or "", "东方财富")
    return None


def latest_lpr():
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
    for item in response.json().get("records") or []:
        if item.get("1Y") and item.get("showDateCN"):
            return _point(float(item["1Y"]), item["showDateCN"], "中国货币网")
    return None


def latest_yields():
    response = requests.get(
        "https://datacenter.eastmoney.com/api/data/get",
        params={
            "type": "RPTA_WEB_TREASURYYIELD",
            "sty": "ALL",
            "st": "SOLAR_DATE",
            "sr": "-1",
            "token": "894050c76af8597a853f5b408b759f5d",
            "p": "1",
            "ps": "8",
        },
        timeout=20,
    )
    rows = (response.json().get("result") or {}).get("data") or []
    for row in rows:
        cn = row.get("EMM00166466")
        us10 = row.get("EMG00001310")
        us2 = row.get("EMG00001306")
        if cn in (None, "") or us10 in (None, ""):
            continue
        date = str(row.get("SOLAR_DATE") or "")[:10]
        return {
            "cn_10y": _point(float(cn), date, "东方财富"),
            "us_10y": _point(float(us10), date, "东方财富"),
            "us_2y": _point(float(us2), date, "东方财富") if us2 not in (None, "") else None,
        }
    return {}


def latest_social():
    response = requests.post(
        "https://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery",
        timeout=20,
    )
    rows = response.json() or []
    parsed = []
    for row in rows:
        month = str(row.get("date") or "")
        raw = row.get("tiosfs")
        if not month or raw in (None, ""):
            continue
        parsed.append((month, float(raw)))
    if not parsed:
        return None
    month, value = max(parsed)
    # 商务部这张表的单位是亿元。卡片按元再换算成亿。
    yuan = value * 1e8 if abs(value) < 1e7 else value
    label = f"{month[:4]}-{month[4:6]}" if len(month) >= 6 else month
    return _point(yuan, label, "商务部")


def latest_caixin():
    response = requests.post(
        "https://yun.ccxe.com.cn/dataindices/pmi",
        data={"type": "MAN"},
        timeout=20,
    )
    payload = (response.json() or {}).get("data") or {}
    months = payload.get("month") or []
    values = payload.get("data") or []
    for month, raw in zip(reversed(months), reversed(values)):
        if raw in (None, ""):
            continue
        return _point(float(raw), str(month)[:10], "财新")
    return None


def em_clist(filter_text, page_size="20"):
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    last_error = None
    for _ in range(4):
        try:
            response = session.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={
                    "np": "1",
                    "fltt": "2",
                    "invt": "2",
                    "fs": filter_text,
                    "fields": "f12,f14,f2",
                    "pn": "1",
                    "pz": page_size,
                },
                timeout=20,
            )
            diff = ((response.json() or {}).get("data") or {}).get("diff") or {}
            rows = diff.values() if isinstance(diff, dict) else diff
            return list(rows)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1)
    if last_error:
        print(f"行情批次失败: {last_error}")
    return []


def latest_sina_quotes():
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    session.headers["Referer"] = "https://finance.sina.com.cn/"
    response = session.get("https://hq.sinajs.cn/list=sh204001,gb_ixic", timeout=15)
    response.raise_for_status()
    found = {}
    for line in response.text.split(";"):
        if "hq_str_sh204001=" in line:
            parts = line.split("=", 1)[1].strip().strip('"').split(",")
            day = next((part for part in parts if len(part) == 10 and part[4:5] == "-" and part[7:8] == "-"), "")
            found["gc001"] = _point(round(float(parts[3]), 3), day, "上交所")
        if "hq_str_gb_ixic=" in line:
            parts = line.split("=", 1)[1].strip().strip('"').split(",")
            stamp = parts[3][:10] if len(parts) > 3 else ""
            found["nasdaq"] = _point(round(float(parts[1]), 2), stamp, "新浪财经")
    return found


def latest_quotes():
    today = datetime.now().strftime("%Y-%m-%d")
    found = {}
    batches = [
        ("i:1.000300,i:100.HSI,i:100.N225,i:100.SPX,i:100.UDI", "20"),
        ("m:119,m:120,m:133", "200"),
        ("m:101,m:102", "80"),
    ]
    rows = []
    for filter_text, page_size in batches:
        rows.extend(em_clist(filter_text, page_size))
        time.sleep(0.8)
    by_code = {str(row.get("f12")): row for row in rows if row.get("f2") not in (None, "-")}
    mapping = {
        "spx": ("SPX", 2),
        "hs300": ("000300", 2),
        "hsi": ("HSI", 2),
        "nk225": ("N225", 2),
        "dxy_idx": ("UDI", 2),
        "usd_cnh": ("USDCNH", 4),
        "usd_jpy": ("USDJPY", 4),
        "gold_spot": ("GC00Y", 2),
        "wti_oil": ("CL00Y", 2),
    }
    for key, (code, digits) in mapping.items():
        row = by_code.get(code)
        if not row:
            print(f"行情缺失 {key}")
            continue
        found[key] = _point(round(float(row["f2"]), digits), today, "东方财富")
    return found


def latest_vix():
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    response = session.get(
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        timeout=20,
    )
    response.raise_for_status()
    last = response.text.strip().splitlines()[-1].split(",")
    month, day, year = last[0].split("/")
    return _point(round(float(last[4]), 2), f"{year}-{month}-{day}", "芝加哥期权交易所")


def latest_cn_vix():
    """50ETF 期权波动率。交易所不再发布 iVIX，这是公开日频里最近的替代。"""
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    response = session.get("http://1.optbbs.com/d/csv/d/k.csv", timeout=20)
    response.raise_for_status()
    latest = None
    for line in response.content.decode("gbk", errors="replace").splitlines():
        parts = line.split(",")
        if len(parts) < 5:
            continue
        day = parts[0].strip().replace("/", "-")
        close = parts[4].strip()
        if len(day) != 10 or not close or close.startswith("#"):
            continue
        try:
            value = float(close)
        except ValueError:
            continue
        latest = _point(round(value, 2), day, "50ETF期权")
    return latest


def latest_fed_balance():
    """H.4.1 总资产，单位美元。页面上的数字是百万美元。"""
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    response = session.get("https://www.federalreserve.gov/releases/h41/current/h41.htm", timeout=25)
    response.raise_for_status()
    text = response.text
    index = text.find("Total assets")
    plain = html.unescape(re.sub(r"<[^>]+>", " ", text[index: index + 5000]))
    plain = re.sub(r"\s+", " ", plain)
    found = re.search(
        r"Total assets\s+\(0\)\s+([\d,]+)\s+([+\-])\s+([\d,]+)\s+([+\-])\s+([\d,]+)",
        plain,
    )
    if not found:
        return None
    level_million = float(found.group(1).replace(",", ""))
    weekly_million = float(found.group(3).replace(",", ""))
    if found.group(2) == "-":
        weekly_million = -weekly_million
    header = re.search(r'id="t7h1c3"[\s\S]{0,500}?([A-Z][a-z]{2} \d{1,2}, \d{4})', text)
    day = ""
    if header:
        day = datetime.strptime(header.group(1), "%b %d, %Y").date().isoformat()
    return _point(level_million * 1_000_000, day, "美联储", weekly_change=weekly_million * 1_000_000)


def latest_core_pce():
    """核心 PCE 同比。取美国商务部最新一篇个人收入和支出新闻稿。"""
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    listing = session.get("https://www.bea.gov/news/current-releases", timeout=20)
    listing.raise_for_status()
    hrefs = re.findall(r'href="(/news/\d{4}/personal-income-and-outlays-[a-z]+-\d{4})"', listing.text)
    if not hrefs:
        return None
    path = hrefs[0]
    page = session.get("https://www.bea.gov" + path, timeout=25)
    page.raise_for_status()
    plain = re.sub(r"<[^>]+>", " ", page.text)
    found = re.search(
        r"Excluding food and energy, the PCE price index increased\s+([\d.]+)\s+percent from one year ago",
        plain,
    )
    if not found:
        return None
    month_name, year = path.rsplit("/", 1)[-1].replace("personal-income-and-outlays-", "").split("-")
    month = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }[month_name]
    return _point(float(found.group(1)), f"{year}-{month:02d}", "美国商务部")


def latest_hy_oas():
    """ICE 美银美国高收益债期权调整利差，单位 bp。"""
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    response = session.get("https://dollarliquidity.com/en/indicators/hy-spread", timeout=20)
    response.raise_for_status()
    title = re.search(r"<title>(.*?)</title>", response.text)
    found = re.search(r"([\d.]+)\s*bps\s*\((\d{4}-\d{2}-\d{2})\)", title.group(1) if title else "")
    if not found:
        return None
    return _point(round(float(found.group(1)), 1), found.group(2), "ICE BofA")


def latest_ted():
    """原版 TED 已停更。这里用 90 天 AA 金融商业票据减 13 周国债，单位 bp。"""
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    page = session.get("https://www.federalreserve.gov/releases/cp/", timeout=20)
    page.raise_for_status()
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(page.text)))
    posted = re.search(r"as of ([A-Z][a-z]+ \d{1,2}, \d{4})", plain)
    if not posted:
        return None
    year = int(posted.group(1).rsplit(" ", 1)[-1])
    section = plain.split("Period AA financial AA asset-backed")[-1]
    rows = re.findall(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\. (\d+)\s+"
        r"([\d.]+|n\.a\.)\s+([\d.]+|n\.a\.)\s+([\d.]+|n\.a\.)\s+"
        r"([\d.]+|n\.a\.)\s+([\d.]+|n\.a\.)\s+([\d.]+|n\.a\.)",
        section,
    )
    latest = None
    for month, day, _one, _seven, _fifteen, _thirty, _sixty, ninety in rows:
        if ninety == "n.a.":
            continue
        latest = (month, int(day), float(ninety))
    if latest is None:
        return None
    month, day, commercial_paper = latest
    stamp = datetime(year, _MONTHS[month], day).date()
    bill = session.get(
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/"
        f"{stamp.year}{stamp.month:02d}?type=daily_treasury_bill_rates&field_tdr_date_value_month="
        f"{stamp.year}{stamp.month:02d}&page&_format=csv",
        timeout=20,
    )
    bill.raise_for_status()
    wanted = stamp.strftime("%m/%d/%Y")
    coupon = None
    for row in csv.reader(io.StringIO(bill.text)):
        if row and row[0] == wanted and len(row) > 8 and row[8]:
            coupon = float(row[8])
    if coupon is None:
        return None
    return _point(round((commercial_paper - coupon) * 100, 1), stamp.isoformat(), "美联储票据减国债")


def latest_rrp():
    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "Mozilla/5.0"
    response = session.get(
        "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/1.json",
        timeout=20,
    )
    response.raise_for_status()
    operation = response.json()["repo"]["operations"][0]
    amount = operation.get("totalAmtAccepted")
    if amount in (None, ""):
        return None
    return _point(float(amount), operation.get("operationDate") or "", "纽约联储")


def main():
    snapshot = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "china_core": {},
        "global_macro": {},
        "fx_liquidity": {},
        "assets": {},
        "risk_monitor": {},
    }

    jobs = {
        "cn_pmi_official": lambda: em_latest("RPT_ECONOMY_PMI", "MAKE_INDEX"),
        "cn_cpi_yy": lambda: em_latest("RPT_ECONOMY_CPI", "NATIONAL_SAME"),
        "cn_ppi_yy": lambda: em_latest("RPT_ECONOMY_PPI", "BASE_SAME"),
        "cn_lpr_1y": latest_lpr,
        "cn_social_financing": latest_social,
        "cn_pmi_caixin": latest_caixin,
    }
    for key, fetcher in jobs.items():
        try:
            snapshot["china_core"][key] = fetcher()
            print(key, snapshot["china_core"][key])
        except Exception as exc:
            print(f"{key} 失败: {exc}")
            snapshot["china_core"][key] = None

    try:
        m2 = em_latest("RPT_ECONOMY_CURRENCY_SUPPLY", "BASIC_CURRENCY_SAME")
        m1 = em_latest("RPT_ECONOMY_CURRENCY_SUPPLY", "CURRENCY_SAME")
        if m1 and m2:
            snapshot["china_core"]["cn_m1_m2_spread"] = {
                "spread": round(m1["value"] - m2["value"], 2),
                "m1_yoy": m1["value"],
                "m2_yoy": m2["value"],
                "date": m2["date"] or m1["date"],
                "source": "东方财富",
            }
        print("m1m2", snapshot["china_core"].get("cn_m1_m2_spread"))
    except Exception as exc:
        print(f"货币供应失败: {exc}")

    try:
        yields = latest_yields()
        snapshot["china_core"]["cn_10y_yield"] = yields.get("cn_10y")
        snapshot["global_macro"]["us_10y_yield"] = yields.get("us_10y")
        snapshot["global_macro"]["us_2y_yield"] = yields.get("us_2y")
        snapshot["assets"]["us_10y_yield"] = yields.get("us_10y")
        print("yields", yields)
    except Exception as exc:
        print(f"国债收益率失败: {exc}")

    previous = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as handle:
                previous = json.load(handle)
        except json.JSONDecodeError:
            previous = {}
    try:
        quotes = latest_quotes()
    except Exception as exc:
        print(f"行情失败: {exc}")
        quotes = {}

    def keep(section, key):
        fresh = quotes.get(key)
        if fresh:
            return fresh
        old = (previous.get(section) or {}).get(key)
        if old:
            print(f"{key} 这次没取到，沿用 {old.get('date')}")
        return old

    for key in ("spx", "hs300", "hsi", "nk225", "gold_spot", "wti_oil"):
        snapshot["assets"][key] = keep("assets", key)
    snapshot["assets"]["btc_usd"] = None
    try:
        sina = latest_sina_quotes()
        snapshot["china_core"]["cn_repo_gc001"] = sina.get("gc001")
        snapshot["assets"]["nasdaq"] = sina.get("nasdaq")
        print("gc001", sina.get("gc001"))
        print("nasdaq", sina.get("nasdaq"))
    except Exception as exc:
        print(f"新浪行情失败: {exc}")
        snapshot["china_core"]["cn_repo_gc001"] = (previous.get("china_core") or {}).get("cn_repo_gc001")
        snapshot["assets"]["nasdaq"] = (previous.get("assets") or {}).get("nasdaq")
    for key in ("dxy_idx", "usd_cnh", "usd_jpy"):
        snapshot["fx_liquidity"][key] = keep("fx_liquidity", key)
    snapshot["risk_monitor"]["vix"] = keep("risk_monitor", "vix")
    try:
        snapshot["risk_monitor"]["vix"] = latest_vix()
        print("vix", snapshot["risk_monitor"]["vix"])
    except Exception as exc:
        print(f"VIX 失败: {exc}")
    snapshot["risk_monitor"]["cn_vix"] = (previous.get("risk_monitor") or {}).get("cn_vix")
    try:
        snapshot["risk_monitor"]["cn_vix"] = latest_cn_vix()
        print("cn_vix", snapshot["risk_monitor"]["cn_vix"])
    except Exception as exc:
        print(f"A股VIX 失败: {exc}")
    previous_risk = previous.get("risk_monitor") or {}
    for key in ("hy_spread_oas", "ted_spread"):
        snapshot["risk_monitor"][key] = previous_risk.get(key)
    try:
        point = latest_hy_oas()
        if point:
            snapshot["risk_monitor"]["hy_spread_oas"] = point
        print("hy", snapshot["risk_monitor"]["hy_spread_oas"])
    except Exception as exc:
        print(f"高收益债利差失败: {exc}")
    try:
        point = latest_ted()
        if point:
            snapshot["risk_monitor"]["ted_spread"] = point
        print("ted", snapshot["risk_monitor"]["ted_spread"])
    except Exception as exc:
        print(f"TED利差失败: {exc}")
    try:
        snapshot["global_macro"]["on_rrp_balance"] = latest_rrp()
        print("rrp", snapshot["global_macro"]["on_rrp_balance"])
    except Exception as exc:
        print(f"隔夜逆回购失败: {exc}")
        snapshot["global_macro"]["on_rrp_balance"] = (previous.get("global_macro") or {}).get("on_rrp_balance")
    previous_global = previous.get("global_macro") or {}
    snapshot["global_macro"]["us_core_pce_yy"] = previous_global.get("us_core_pce_yy")
    snapshot["global_macro"]["fed_balance_sheet"] = previous_global.get("fed_balance_sheet")
    try:
        point = latest_core_pce()
        if point:
            snapshot["global_macro"]["us_core_pce_yy"] = point
        print("pce", snapshot["global_macro"]["us_core_pce_yy"])
    except Exception as exc:
        print(f"核心PCE失败: {exc}")
    try:
        point = latest_fed_balance()
        if point:
            snapshot["global_macro"]["fed_balance_sheet"] = point
        print("fed_bs", snapshot["global_macro"]["fed_balance_sheet"])
    except Exception as exc:
        print(f"美联储资产负债表失败: {exc}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
    print("已写入", OUT)


if __name__ == "__main__":
    main()
