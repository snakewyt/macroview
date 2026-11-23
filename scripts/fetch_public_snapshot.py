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
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

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


def _cn_month(label):
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月份", str(label).strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def latest_m1_m2():
    response = requests.get(
        EM,
        params={
            "reportName": "RPT_ECONOMY_CURRENCY_SUPPLY",
            "columns": "REPORT_DATE,TIME,CURRENCY_SAME,BASIC_CURRENCY_SAME",
            "pageSize": "18",
            "pageNumber": "1",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
        timeout=20,
    )
    rows = (response.json().get("result") or {}).get("data") or []
    points = []
    for row in rows:
        stamp = _cn_month(row.get("TIME"))
        m1 = row.get("CURRENCY_SAME")
        m2 = row.get("BASIC_CURRENCY_SAME")
        if stamp is None or m1 in (None, "") or m2 in (None, ""):
            continue
        points.append((stamp[0] * 12 + stamp[1], float(m1), float(m2), row.get("TIME") or ""))
    if not points:
        return None
    points.sort(reverse=True)
    index, m1, m2, label = points[0]
    item = {
        "spread": round(m1 - m2, 2),
        "m1_yoy": m1,
        "m2_yoy": m2,
        "date": label,
        "source": "东方财富",
    }
    prior = next((row for row in points if row[0] == index - 6), None)
    if prior:
        item["spread_6m"] = round(prior[1] - prior[2], 2)
        item["date_6m"] = prior[3]
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


def _xlsx_column_rows(content):
    """读央行 xlsx 的 A、B 列。月份有的是数字，10 月以后是文本。"""
    def local(tag):
        return tag.rsplit("}", 1)[-1]

    with zipfile.ZipFile(io.BytesIO(content)) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            for item in root.iter():
                if local(item.tag) != "si":
                    continue
                shared.append("".join(node.text or "" for node in item.iter() if local(node.tag) == "t"))
        sheet_name = next(name for name in book.namelist() if name.startswith("xl/worksheets/sheet"))
        root = ET.fromstring(book.read(sheet_name))
        rows = []
        for row in root.iter():
            if local(row.tag) != "row":
                continue
            values = {}
            for cell in row:
                if local(cell.tag) != "c":
                    continue
                ref = cell.get("r") or ""
                column = "".join(ch for ch in ref if ch.isalpha())
                kind = cell.get("t")
                text = None
                for node in cell.iter():
                    if local(node.tag) == "v" and node.text is not None:
                        text = node.text
                        break
                if text is None:
                    continue
                values[column] = shared[int(text)] if kind == "s" else text
            if values:
                rows.append(values)
        return rows


def _flow_month(raw, seen):
    match = re.fullmatch(r"(\d{4})\.(\d{1,2})", str(raw).strip())
    if not match:
        return None
    year, token = int(match.group(1)), match.group(2)
    month = int(token)
    # Excel 把 10 月存成数字时会变成 2025.1。1 月已经出现过，这个 .1 就是 10 月。
    if len(token) == 1 and month == 1 and f"{year:04d}-01" in seen:
        month = 10
    if year < 2000 or not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def _pbc_page(url):
    page = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    if page.status_code != 200:
        return ""
    text = page.content.decode("utf-8", "replace")
    if "社会融资" not in text and "统计数据" not in text:
        text = page.content.decode("gbk", "replace")
    return text


def _pbc_url(href):
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.pbc.gov.cn" + href
    return "https://www.pbc.gov.cn/" + href


def _flow_points_from_page(text):
    start = text.find("社会融资规模增量统计表")
    if start < 0:
        return []
    end = text.find("社会融资规模存量", start)
    chunk = text[start:end if end > start else None]
    match = re.search(r"""href=['"]([^'"]+\.xlsx)['"]""", chunk)
    if not match:
        return []
    book = requests.get(_pbc_url(match.group(1)), headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    book.raise_for_status()
    points = []
    seen = set()
    for row in _xlsx_column_rows(book.content):
        label = _flow_month(row.get("A"), seen)
        raw = row.get("B")
        if not label or raw in (None, ""):
            continue
        seen.add(label)
        try:
            value = float(str(raw).replace(",", ""))
        except ValueError:
            continue
        points.append((label, value))
    return points


def _pbc_flow_points(year):
    direct = _flow_points_from_page(_pbc_page(
        f"https://www.pbc.gov.cn/diaochatongjisi/116219/116319/{year}ntjsj/shrzgm/index.html"
    ))
    if direct:
        return direct
    index = _pbc_page("https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html")
    year_link = re.search(
        rf"""href=['"]([^'"]+)['"][^>]*>\s*{year}年统计数据""",
        index,
    )
    if not year_link:
        return []
    year_page = _pbc_page(_pbc_url(year_link.group(1)))
    social = re.search(r"""href=['"]([^'"]+)['"][^>]*>\s*社会融资规模""", year_page)
    if not social:
        return []
    return _flow_points_from_page(_pbc_page(_pbc_url(social.group(1))))


def _sum_through(points, year, month_num):
    prefix = f"{year:04d}-"
    chosen = {
        int(label[5:7]): value
        for label, value in points
        if label.startswith(prefix) and 1 <= int(label[5:7]) <= month_num
    }
    if set(range(1, month_num + 1)) - set(chosen):
        return None
    return sum(chosen.values())


def latest_social():
    year = datetime.now().year
    points = _pbc_flow_points(year) or _pbc_flow_points(year - 1)
    if not points:
        return None
    month, value = points[-1]
    data_year = int(month[:4])
    month_num = int(month[5:7])
    prior_points = _pbc_flow_points(data_year - 1)
    extra = {}
    ytd = _sum_through(points, data_year, month_num)
    ytd_prev = _sum_through(prior_points, data_year - 1, month_num)
    if ytd is not None:
        extra["ytd"] = ytd * 1e8
    if ytd_prev is not None:
        extra["ytd_last_year"] = ytd_prev * 1e8
    # 央行表单位是亿元。卡片按元再换算成亿。
    return _point(value * 1e8, month, "人民银行", **extra)


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


def latest_move():
    response = requests.get(
        "https://query2.finance.yahoo.com/v8/finance/chart/%5EMOVE?interval=1d&range=10d",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
        timeout=20,
    )
    response.raise_for_status()
    result = ((response.json().get("chart") or {}).get("result") or [None])[0] or {}
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    stamp = meta.get("regularMarketTime")
    if price in (None, "") or stamp in (None, ""):
        return None
    day = datetime.fromtimestamp(int(stamp), ZoneInfo("America/New_York")).date().isoformat()
    return _point(round(float(price), 2), day, "雅虎财经")


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


def latest_hs300_pe():
    """沪深300滚动市盈率 PE-TTM（用于计算股债性价比 ERP）。"""
    try:
        import akshare as ak
        df = ak.stock_index_pe_lg(symbol="沪深300")
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        pe_col = next((c for c in df.columns if "滚动市盈率" in str(c) or "pe_ttm" in str(c).lower()), None)
        date_col = next((c for c in df.columns if "日期" in str(c) or "date" in str(c).lower()), None)
        if not pe_col:
            return None
        val = float(row[pe_col])
        day = str(row[date_col])[:10] if date_col else datetime.now().strftime("%Y-%m-%d")
        return _point(round(val, 2), day, "乐咕乐股")
    except Exception as exc:
        print(f"沪深300 PE 失败: {exc}")
        return None


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
        snapshot["china_core"]["cn_m1_m2_spread"] = latest_m1_m2()
        print("m1m2", snapshot["china_core"].get("cn_m1_m2_spread"))
    except Exception as exc:
        print(f"货币供应失败: {exc}")
        snapshot["china_core"]["cn_m1_m2_spread"] = None

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
    if snapshot["china_core"].get("cn_social_financing") is None:
        old = (previous.get("china_core") or {}).get("cn_social_financing")
        if old:
            snapshot["china_core"]["cn_social_financing"] = old
            print(f"社融这次没取到，沿用 {old.get('date')}")
    if snapshot["china_core"].get("cn_m1_m2_spread") is None:
        old = (previous.get("china_core") or {}).get("cn_m1_m2_spread")
        if old:
            snapshot["china_core"]["cn_m1_m2_spread"] = old
            print(f"剪刀差这次没取到，沿用 {old.get('date')}")
    hs300_pe = latest_hs300_pe()
    snapshot["china_core"]["hs300_pe"] = hs300_pe or (previous.get("china_core") or {}).get("hs300_pe")
    if snapshot["china_core"].get("hs300_pe"):
        print("hs300_pe", snapshot["china_core"]["hs300_pe"])
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
    snapshot["risk_monitor"]["move_idx"] = (previous.get("risk_monitor") or {}).get("move_idx")
    try:
        point = latest_move()
        if point:
            snapshot["risk_monitor"]["move_idx"] = point
        print("move", snapshot["risk_monitor"]["move_idx"])
    except Exception as exc:
        print(f"MOVE 失败: {exc}")
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
