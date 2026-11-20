"""
A股牛市、熊市流动性条件。

两套各 8 条，阶段划分保持独立，不改 macroview 原有的 5 因子仓位模型。
输入是已经对齐的时间序列，计算本身不访问网络。
"""

from __future__ import annotations

from datetime import date
from typing import Optional


def _parse(value: str) -> date:
    text = str(value).strip().replace("/", "-").replace(".", "-")
    parts = text.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    day = int(parts[2]) if len(parts) > 2 else 1
    return date(year, month, day)


def _iso(value: date) -> str:
    return value.isoformat()


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(value.day, _month_length(year, month))
    return date(year, month, day)


def _month_length(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def _sorted(points) -> list:
    cleaned = []
    for point in points or []:
        if point is None or point.get("value") is None:
            continue
        try:
            parsed = _parse(str(point["date"])[:10])
        except (TypeError, ValueError):
            continue
        cleaned.append({"date": _iso(parsed), "value": float(point["value"])})
    cleaned.sort(key=lambda item: item["date"])
    return cleaned


def _latest(points) -> Optional[dict]:
    series = _sorted(points)
    return series[-1] if series else None


def _asof(points, target: date) -> Optional[dict]:
    found = None
    for point in _sorted(points):
        if _parse(point["date"]) <= target:
            found = point
        else:
            break
    return found


def _months_before(points, months: int) -> Optional[dict]:
    latest = _latest(points)
    if latest is None:
        return None
    return _asof(points, _add_months(_parse(latest["date"]), -months))


def _count_cuts(points, since: date, until: date) -> int:
    previous = None
    count = 0
    for point in _sorted(points):
        current = _parse(point["date"])
        if previous is not None and point["value"] < previous - 1e-9 and since <= current <= until:
            count += 1
        previous = point["value"]
    return count


def _balance_text(value: Optional[float]) -> str:
    if value is None:
        return "--"
    if abs(value) >= 1e6:
        return f"{value / 1e8:.0f}亿"
    return _num(value, 0)


def _num(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def _condition(condition_id, group, name, status, rule, detail, value=None, unit=""):
    return {
        "id": condition_id,
        "group": group,
        "name": name,
        "status": status,
        "rule": rule,
        "detail": detail,
        "value": None if value is None else round(float(value), 4),
        "unit": unit,
    }


def _excess_series(m2_yoy, nominal_gdp_yoy) -> list:
    series = []
    for point in _sorted(m2_yoy):
        gdp = _asof(nominal_gdp_yoy, _parse(point["date"]))
        if gdp is None:
            continue
        series.append({
            "date": point["date"],
            "value": point["value"] - gdp["value"],
            "m2": point["value"],
            "gdp": gdp["value"],
        })
    return series


def _stage(conditions) -> tuple[str, str]:
    by_id = {item["id"]: item for item in conditions}

    def met(condition_id: int) -> bool:
        return by_id[condition_id]["status"] == "met"

    def partial(condition_id: int) -> bool:
        return by_id[condition_id]["status"] == "partial"

    if met(8) and (met(1) or met(2)):
        return (
            "主升条件",
            "社融或信贷已经从底部回升，盈利也跟着转好。流动性从估值修复切到基本面。",
        )
    if partial(8) and (met(1) or met(6)):
        return (
            "信用接棒",
            "社融或信贷已经回升，盈利还没有跟上。主升条件只完成了一半。",
        )
    if met(6) and met(7) and met(1):
        return (
            "资金进场",
            "M1 已从低位回升，并且至少有一条增量资金渠道在扩大。",
        )
    if all(met(condition_id) for condition_id in (1, 2, 3, 4, 5)):
        return (
            "启动土壤",
            "前 5 条同时满足。钱已经不紧，实体还没接住，政策利率也已经连续往下。",
        )
    names = {
        1: "剩余流动性走阔",
        2: "政策利率转入下行",
        3: "宽松连续累积",
        4: "钱宽、实体未接住",
        5: "政策工具点火",
        6: "M1 见底回升",
        7: "增量资金渠道",
        8: "信贷回升且盈利跟上",
    }
    missing = [names[condition_id] for condition_id in names if not met(condition_id)]
    return "条件未齐", "尚未满足：" + "、".join(missing)


def evaluate_bull_liquidity(series: dict) -> dict:
    """根据 8 条流动性条件给出状态和阶段。series 的每个键是 {date, value} 列表。"""
    m2 = series.get("m2_yoy") or []
    gdp = series.get("nominal_gdp_yoy") or []
    m1 = series.get("m1_yoy") or []
    lpr = series.get("lpr_1y") or []
    rrr = series.get("rrr") or []
    bond = series.get("cn_10y") or []
    credit = series.get("credit_yoy") or []
    profit = series.get("industrial_profit_yoy") or []
    margin = series.get("margin_balance") or []

    excess = _excess_series(m2, gdp)
    excess_now = excess[-1] if excess else None
    excess_prev = None
    if excess_now is not None:
        excess_prev = next(
            (
                point for point in reversed(excess)
                if _parse(point["date"]) <= _add_months(_parse(excess_now["date"]), -3)
            ),
            None,
        )

    if excess_now is None or excess_prev is None:
        condition_1 = _condition(
            1, "启动", "剩余流动性走阔", "missing",
            "M2 同比减名义 GDP 同比为正，且高于三个月前",
            "缺 M2 或名义 GDP，这条还不能判断。",
        )
    else:
        widened = excess_now["value"] > excess_prev["value"]
        positive = excess_now["value"] > 0
        if positive and widened:
            status = "met"
        elif positive:
            status = "partial"
        else:
            status = "unmet"
        condition_1 = _condition(
            1, "启动", "剩余流动性走阔", status,
            "M2 同比减名义 GDP 同比为正，且高于三个月前",
            (
                f"最新 {_num(excess_now['value'])} 个百分点"
                f"（M2 {_num(excess_now['m2'])}% − 名义GDP {_num(excess_now['gdp'])}%），"
                f"三个月前 {_num(excess_prev['value'])} 个百分点。"
            ),
            excess_now["value"],
            "pct",
        )

    lpr_now = _latest(lpr)
    lpr_6m = _months_before(lpr, 6)
    bond_now = _latest(bond)
    bond_3m = _months_before(bond, 3)
    if lpr_now is None or lpr_6m is None:
        condition_2 = _condition(
            2, "启动", "政策利率转入下行", "missing",
            "一年期 LPR 六个月下行，或 LPR 不再上调且 10 年国债收益率三个月下行",
            "缺一年期 LPR 历史，这条还不能判断。",
        )
    else:
        lpr_down = lpr_now["value"] < lpr_6m["value"] - 1e-9
        lpr_up = lpr_now["value"] > lpr_6m["value"] + 1e-9
        bond_down = (
            bond_now is not None and bond_3m is not None
            and bond_now["value"] <= bond_3m["value"] - 0.10
        )
        bond_up = (
            bond_now is not None and bond_3m is not None
            and bond_now["value"] >= bond_3m["value"] + 0.10
        )
        if lpr_up or (not lpr_down and bond_up):
            status = "unmet"
        elif lpr_down or bond_down:
            status = "met"
        else:
            status = "partial"
        bond_text = ""
        if bond_now is not None and bond_3m is not None:
            bond_text = f"10 年国债 {_num(bond_3m['value'])}% → {_num(bond_now['value'])}%。"
        condition_2 = _condition(
            2, "启动", "政策利率转入下行", status,
            "一年期 LPR 六个月下行，或 LPR 不再上调且 10 年国债收益率三个月下行至少 10bp",
            f"一年期 LPR {_num(lpr_6m['value'])}% → {_num(lpr_now['value'])}%。{bond_text}",
            lpr_now["value"],
            "%",
        )

    anchors = [item for item in (lpr_now, _latest(rrr), bond_now) if item is not None]
    if not anchors:
        condition_3 = _condition(
            3, "启动", "宽松连续累积", "missing",
            "过去 12 个月降息或降准至少 2 次",
            "缺 LPR 和存款准备金率，这条还不能判断。",
        )
        condition_5 = _condition(
            5, "启动", "政策工具点火", "missing",
            "近 3 个月至少有一次降息或降准",
            "缺 LPR 和存款准备金率，这条还不能判断。",
        )
    else:
        until = max(_parse(item["date"]) for item in anchors)
        cuts_12m = _count_cuts(lpr, _add_months(until, -12), until) + _count_cuts(rrr, _add_months(until, -12), until)
        cuts_3m = _count_cuts(lpr, _add_months(until, -3), until) + _count_cuts(rrr, _add_months(until, -3), until)
        if cuts_12m >= 2:
            status_3 = "met"
        elif cuts_12m == 1:
            status_3 = "partial"
        else:
            status_3 = "unmet"
        condition_3 = _condition(
            3, "启动", "宽松连续累积", status_3,
            "过去 12 个月降息或降准至少 2 次",
            f"过去 12 个月降息、降准合计 {cuts_12m} 次。",
            cuts_12m,
            "次",
        )
        condition_5 = _condition(
            5, "启动", "政策工具点火", "met" if cuts_3m >= 1 else "unmet",
            "近 3 个月至少有一次降息或降准。社论和改革信号不在这套数据里",
            f"近 3 个月降息、降准合计 {cuts_3m} 次。",
            cuts_3m,
            "次",
        )

    credit_now = _latest(credit)
    credit_prev = _months_before(credit, 3)
    credit_delta = None
    if credit_now is not None and credit_prev is not None:
        credit_delta = credit_now["value"] - credit_prev["value"]

    if excess_now is None or credit_delta is None:
        condition_4 = _condition(
            4, "启动", "钱宽、实体未接住", "missing",
            "剩余流动性为正，且社融或信贷同比三个月升幅不超过 0.3 个百分点",
            "缺剩余流动性或信贷同比，这条还不能判断。",
        )
    else:
        loose = excess_now["value"] > 0 and credit_delta <= 0.3
        if loose:
            status = "met"
        elif excess_now["value"] > 0:
            status = "unmet"
        else:
            status = "unmet"
        condition_4 = _condition(
            4, "启动", "钱宽、实体未接住", status,
            "剩余流动性为正，且社融或信贷同比三个月升幅不超过 0.3 个百分点",
            (
                f"剩余流动性 {_num(excess_now['value'])} 个百分点（截至 {excess_now['date']}），"
                f"信贷同比三个月变化 {_num(credit_delta)} 个百分点（截至 {credit_now['date']}）。"
            ),
            credit_delta,
            "pct",
        )

    m1_now = _latest(m1)
    m1_prev = _months_before(m1, 3)
    if m1_now is None or m1_prev is None:
        condition_6 = _condition(
            6, "进场", "M1 见底回升", "missing",
            "M1 同比高于三个月前，并且高于此前六个月的低点",
            "缺 M1 同比，这条还不能判断。",
        )
    else:
        window_start = _add_months(_parse(m1_now["date"]), -6)
        prior = [
            point["value"] for point in _sorted(m1)
            if window_start <= _parse(point["date"]) < _parse(m1_now["date"])
        ]
        trough = min(prior) if prior else m1_prev["value"]
        rising = m1_now["value"] > m1_prev["value"] and m1_now["value"] > trough
        condition_6 = _condition(
            6, "进场", "M1 见底回升", "met" if rising else "unmet",
            "M1 同比高于三个月前，并且高于此前六个月的低点",
            f"M1 同比 {_num(m1_prev['value'])}% → {_num(m1_now['value'])}%，区间低点 {_num(trough)}%。",
            m1_now["value"],
            "%",
        )

    channels = []
    margin_now = _latest(margin)
    margin_prev = _months_before(margin, 1)
    if margin_now is not None and margin_prev is not None and margin_now["value"] > margin_prev["value"]:
        channels.append(
            f"两融余额 {_balance_text(margin_prev['value'])} → {_balance_text(margin_now['value'])}"
        )
    if margin_now is None or margin_prev is None:
        condition_7 = _condition(
            7, "进场", "增量资金渠道", "missing",
            "两融余额一个月上升",
            "缺两融余额，这条还不能判断。",
        )
    else:
        condition_7 = _condition(
            7, "进场", "增量资金渠道", "met" if channels else "unmet",
            "两融余额一个月上升",
            "；".join(channels) if channels else "两融余额没有上升。",
            margin_now["value"],
            "",
        )

    profit_now = _latest(profit)
    profit_prev = _months_before(profit, 3)
    if credit_delta is None:
        condition_8 = _condition(
            8, "主升", "信贷回升且盈利跟上", "missing",
            "信贷同比三个月上升至少 0.3 个百分点，且工业企业利润同比转正并高于三个月前",
            "缺信贷同比，这条还不能判断。",
        )
    else:
        credit_up = credit_delta >= 0.3
        earnings_up = (
            profit_now is not None and profit_prev is not None
            and profit_now["value"] > 0 and profit_now["value"] >= profit_prev["value"]
        )
        if credit_up and earnings_up:
            status = "met"
        elif credit_up:
            status = "partial"
        else:
            status = "unmet"
        profit_text = "工业企业利润未取到。"
        if profit_now is not None and profit_prev is not None:
            profit_text = f"工业企业利润同比 {_num(profit_prev['value'])}% → {_num(profit_now['value'])}%。"
        elif profit_now is not None:
            profit_text = f"工业企业利润同比 {_num(profit_now['value'])}%。"
        condition_8 = _condition(
            8, "主升", "信贷回升且盈利跟上", status,
            "信贷同比三个月上升至少 0.3 个百分点，且工业企业利润同比转正并高于三个月前",
            f"信贷同比三个月变化 {_num(credit_delta)} 个百分点（截至 {credit_now['date']}）。{profit_text}",
            credit_delta,
            "pct",
        )

    conditions = [
        condition_1, condition_2, condition_3, condition_4,
        condition_5, condition_6, condition_7, condition_8,
    ]
    stage, stage_detail = _stage(conditions)
    return {
        "stage": stage,
        "stage_detail": stage_detail,
        "met_count": sum(1 for item in conditions if item["status"] == "met"),
        "conditions": conditions,
    }


def _bear_stage(conditions) -> tuple[str, str]:
    by_id = {item["id"]: item for item in conditions}

    def met(condition_id: int) -> bool:
        return by_id[condition_id]["status"] == "met"

    def partial(condition_id: int) -> bool:
        return by_id[condition_id]["status"] == "partial"

    if met(8) and (met(1) or met(2)):
        return (
            "主跌条件",
            "信贷继续下滑，盈利也跟着掉。流动性从估值收缩走到基本面。",
        )
    if met(6) and met(7) and met(1):
        return (
            "资金离场",
            "M1 已从高位回落，并且增量资金在撤。",
        )
    if all(met(condition_id) for condition_id in (1, 2, 3, 4, 5)):
        return (
            "退潮土壤",
            "前 5 条同时满足。钱已经转紧，近一年没有新的降息降准。",
        )
    if partial(8) and (met(1) or met(6)):
        return (
            "信用先缩",
            "信贷已经下滑，盈利还没有跟着掉。主跌条件只完成了一半。",
        )
    names = {
        1: "剩余流动性转紧",
        2: "利率不再向下",
        3: "宽松中断",
        4: "钱紧、信用在掉",
        5: "没有新的宽松",
        6: "M1 见顶回落",
        7: "增量资金撤出",
        8: "信用下滑且盈利跟着掉",
    }
    missing = [names[condition_id] for condition_id in names if not met(condition_id)]
    return "条件未齐", "尚未满足：" + "、".join(missing)


def evaluate_bear_liquidity(series: dict) -> dict:
    """熊市 8 条。和牛市用同一套序列，GC001 只用最新一个点。"""
    m2 = series.get("m2_yoy") or []
    gdp = series.get("nominal_gdp_yoy") or []
    m1 = series.get("m1_yoy") or []
    lpr = series.get("lpr_1y") or []
    rrr = series.get("rrr") or []
    bond = series.get("cn_10y") or []
    credit = series.get("credit_yoy") or []
    profit = series.get("industrial_profit_yoy") or []
    margin = series.get("margin_balance") or []
    gc001 = series.get("gc001") or []

    excess = _excess_series(m2, gdp)
    excess_now = excess[-1] if excess else None
    excess_prev = None
    if excess_now is not None:
        excess_prev = next(
            (
                point for point in reversed(excess)
                if _parse(point["date"]) <= _add_months(_parse(excess_now["date"]), -3)
            ),
            None,
        )

    if excess_now is None or excess_prev is None:
        condition_1 = _condition(
            1, "退潮", "剩余流动性转紧", "missing",
            "M2 同比减名义 GDP 同比不高于 0；仍为正但低于三个月前，只算一半",
            "缺 M2 或名义 GDP，这条还不能判断。",
        )
    else:
        negative = excess_now["value"] <= 0
        narrowed = excess_now["value"] < excess_prev["value"]
        if negative:
            status = "met"
        elif narrowed:
            status = "partial"
        else:
            status = "unmet"
        condition_1 = _condition(
            1, "退潮", "剩余流动性转紧", status,
            "M2 同比减名义 GDP 同比不高于 0；仍为正但低于三个月前，只算一半",
            (
                f"最新 {_num(excess_now['value'])} 个百分点"
                f"（M2 {_num(excess_now['m2'])}% − 名义GDP {_num(excess_now['gdp'])}%），"
                f"三个月前 {_num(excess_prev['value'])} 个百分点。"
            ),
            excess_now["value"],
            "pct",
        )

    lpr_now = _latest(lpr)
    lpr_6m = _months_before(lpr, 6)
    bond_now = _latest(bond)
    bond_3m = _months_before(bond, 3)
    bond_12m = _months_before(bond, 12)
    if lpr_now is None or lpr_6m is None:
        condition_2 = _condition(
            2, "退潮", "利率不再向下", "missing",
            "一年期 LPR 六个月上行，或 LPR 不再下调且 10 年国债三个月上行至少 10bp",
            "缺一年期 LPR 历史，这条还不能判断。",
        )
    else:
        lpr_up = lpr_now["value"] > lpr_6m["value"] + 1e-9
        lpr_down = lpr_now["value"] < lpr_6m["value"] - 1e-9
        bond_up = (
            bond_now is not None and bond_3m is not None
            and bond_now["value"] >= bond_3m["value"] + 0.10
        )
        bond_down = (
            bond_now is not None and bond_3m is not None
            and bond_now["value"] <= bond_3m["value"] - 0.10
        )
        if lpr_up or ((not lpr_down) and bond_up):
            status = "met"
        elif lpr_down or bond_down:
            status = "unmet"
        else:
            status = "partial"
        bond_text = ""
        if bond_now is not None and bond_3m is not None:
            bond_text = f"10 年国债 {_num(bond_3m['value'])}% → {_num(bond_now['value'])}%。"
        condition_2 = _condition(
            2, "退潮", "利率不再向下", status,
            "一年期 LPR 六个月上行，或 LPR 不再下调且 10 年国债三个月上行至少 10bp",
            f"一年期 LPR {_num(lpr_6m['value'])}% → {_num(lpr_now['value'])}%。{bond_text}",
            lpr_now["value"],
            "%",
        )

    anchors = [item for item in (lpr_now, _latest(rrr), bond_now) if item is not None]
    if not anchors:
        condition_3 = _condition(
            3, "退潮", "宽松中断", "missing",
            "过去 12 个月没有降息、降准，同时 10 年国债收益率抬升",
            "缺 LPR 和存款准备金率，这条还不能判断。",
        )
        condition_5 = _condition(
            5, "退潮", "没有新的宽松", "missing",
            "近 3 个月没有降息、降准",
            "缺 LPR 和存款准备金率，这条还不能判断。",
        )
    else:
        until = max(_parse(item["date"]) for item in anchors)
        cuts_12m = _count_cuts(lpr, _add_months(until, -12), until) + _count_cuts(rrr, _add_months(until, -12), until)
        cuts_3m = _count_cuts(lpr, _add_months(until, -3), until) + _count_cuts(rrr, _add_months(until, -3), until)
        yield_up = (
            bond_now is not None and bond_12m is not None
            and bond_now["value"] > bond_12m["value"] + 1e-9
        )
        if cuts_12m == 0 and yield_up:
            status_3 = "met"
        elif cuts_12m == 0:
            status_3 = "partial"
        else:
            status_3 = "unmet"
        bond_12_text = "缺 12 个月前的 10 年国债，收益率是否抬升还看不了。"
        if bond_now is not None and bond_12m is not None:
            bond_12_text = f"10 年国债 {_num(bond_12m['value'])}% → {_num(bond_now['value'])}%。"
        condition_3 = _condition(
            3, "退潮", "宽松中断", status_3,
            "过去 12 个月没有降息、降准，同时 10 年国债收益率抬升",
            f"过去 12 个月降息、降准合计 {cuts_12m} 次。{bond_12_text}",
            cuts_12m,
            "次",
        )
        condition_5 = _condition(
            5, "退潮", "没有新的宽松", "met" if cuts_3m == 0 else "unmet",
            "近 3 个月没有降息、降准",
            f"近 3 个月降息、降准合计 {cuts_3m} 次。",
            cuts_3m,
            "次",
        )

    credit_now = _latest(credit)
    credit_prev = _months_before(credit, 3)
    credit_delta = None
    if credit_now is not None and credit_prev is not None:
        credit_delta = credit_now["value"] - credit_prev["value"]

    if excess_now is None or credit_delta is None:
        condition_4 = _condition(
            4, "退潮", "钱紧、信用在掉", "missing",
            "剩余流动性不高于 0，且信贷同比三个月下降超过 0.3 个百分点",
            "缺剩余流动性或信贷同比，这条还不能判断。",
        )
    else:
        credit_down = credit_delta <= -0.3
        tight_money = excess_now["value"] <= 0
        if tight_money and credit_down:
            status = "met"
        elif credit_down:
            status = "partial"
        else:
            status = "unmet"
        condition_4 = _condition(
            4, "退潮", "钱紧、信用在掉", status,
            "剩余流动性不高于 0，且信贷同比三个月下降超过 0.3 个百分点",
            (
                f"剩余流动性 {_num(excess_now['value'])} 个百分点（截至 {excess_now['date']}），"
                f"信贷同比三个月变化 {_num(credit_delta)} 个百分点（截至 {credit_now['date']}）。"
            ),
            credit_delta,
            "pct",
        )

    m1_now = _latest(m1)
    m1_prev = _months_before(m1, 3)
    if m1_now is None or m1_prev is None:
        condition_6 = _condition(
            6, "离场", "M1 见顶回落", "missing",
            "M1 同比低于三个月前，并且低于此前六个月的高点",
            "缺 M1 同比，这条还不能判断。",
        )
    else:
        window_start = _add_months(_parse(m1_now["date"]), -6)
        prior = [
            point["value"] for point in _sorted(m1)
            if window_start <= _parse(point["date"]) < _parse(m1_now["date"])
        ]
        peak = max(prior) if prior else m1_prev["value"]
        falling = m1_now["value"] < m1_prev["value"] and m1_now["value"] < peak
        condition_6 = _condition(
            6, "离场", "M1 见顶回落", "met" if falling else "unmet",
            "M1 同比低于三个月前，并且低于此前六个月的高点",
            f"M1 同比 {_num(m1_prev['value'])}% → {_num(m1_now['value'])}%，区间高点 {_num(peak)}%。",
            m1_now["value"],
            "%",
        )

    margin_now = _latest(margin)
    margin_prev = _months_before(margin, 1)
    gc001_now = _latest(gc001)
    margin_down = (
        margin_now is not None and margin_prev is not None
        and margin_now["value"] < margin_prev["value"]
    )
    gc001_tight = gc001_now is not None and gc001_now["value"] >= 5
    watched = []
    if margin_now is not None and margin_prev is not None:
        watched.append("两融余额")
    if gc001_now is not None:
        watched.append("GC001")
    if not watched:
        condition_7 = _condition(
            7, "离场", "增量资金撤出", "missing",
            "两融余额一个月下降，或 GC001 不低于 5%",
            "缺两融和 GC001，这条还不能判断。",
        )
    else:
        pieces = []
        if margin_now is not None and margin_prev is not None:
            pieces.append(f"两融余额 {_balance_text(margin_prev['value'])} → {_balance_text(margin_now['value'])}")
        if gc001_now is not None:
            pieces.append(f"GC001 {_num(gc001_now['value'], 3)}%")
        condition_7 = _condition(
            7, "离场", "增量资金撤出", "met" if margin_down or gc001_tight else "unmet",
            "两融余额一个月下降，或 GC001 不低于 5%",
            "；".join(pieces) + "。",
            gc001_now["value"] if gc001_now is not None else (margin_now or {}).get("value"),
            "",
        )

    profit_now = _latest(profit)
    profit_prev = _months_before(profit, 3)
    if credit_delta is None:
        condition_8 = _condition(
            8, "主跌", "信用下滑且盈利跟着掉", "missing",
            "信贷同比三个月下降至少 0.3 个百分点，且工业企业利润同比转负或低于三个月前",
            "缺信贷同比，这条还不能判断。",
        )
    else:
        credit_down = credit_delta <= -0.3
        earnings_down = (
            profit_now is not None and profit_prev is not None
            and (profit_now["value"] < 0 or profit_now["value"] < profit_prev["value"])
        )
        if credit_down and earnings_down:
            status = "met"
        elif credit_down:
            status = "partial"
        else:
            status = "unmet"
        profit_text = "工业企业利润未取到。"
        if profit_now is not None and profit_prev is not None:
            profit_text = f"工业企业利润同比 {_num(profit_prev['value'])}% → {_num(profit_now['value'])}%。"
        elif profit_now is not None:
            profit_text = f"工业企业利润同比 {_num(profit_now['value'])}%。"
        condition_8 = _condition(
            8, "主跌", "信用下滑且盈利跟着掉", status,
            "信贷同比三个月下降至少 0.3 个百分点，且工业企业利润同比转负或低于三个月前",
            f"信贷同比三个月变化 {_num(credit_delta)} 个百分点（截至 {credit_now['date']}）。{profit_text}",
            credit_delta,
            "pct",
        )

    conditions = [
        condition_1, condition_2, condition_3, condition_4,
        condition_5, condition_6, condition_7, condition_8,
    ]
    stage, stage_detail = _bear_stage(conditions)
    return {
        "stage": stage,
        "stage_detail": stage_detail,
        "met_count": sum(1 for item in conditions if item["status"] == "met"),
        "conditions": conditions,
    }
