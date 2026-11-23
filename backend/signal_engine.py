"""
信号合成引擎
- 各因子打分（-2 到 +2）
- 加权合成 RISK ON/OFF（缺因子时按有效权重归一化）
- 仓位映射与观点话术
"""

from dataclasses import dataclass
from typing import List, Dict, Optional

# ============ 权重配置 ============
WEIGHTS = {
    "cn_us_spread": 0.20,   # 中美利差
    "m1_m2_spread": 0.25,   # M1-M2剪刀差
    "vix": 0.15,            # VIX
    "north_money": 0.15,    # 北向资金
    "credit_spread": 0.25,  # 信用利差
}


def infer_m1_m2_trend(spread: Optional[float], spread_6m: Optional[float]) -> str:
    """根据最新值与 6 个月前值推断 M1-M2 剪刀差趋势。"""
    if spread is None or spread_6m is None:
        return "持平"
    delta = spread - spread_6m
    if delta >= 0.5:
        return "收窄"
    if delta <= -0.5:
        return "走阔"
    return "持平"


# ============ 打分规则 ============
def score_cn_us_spread(value: Optional[float], trend: str = "持平") -> int:
    """中美利差打分（单位 bp，10Y中债 - 10Y美债，通常为负值）"""
    if value is None:
        return 0
    if value > -150:
        if trend == "收窄":
            return 2
        if trend == "持平":
            return 1
        return 0
    if -200 <= value <= -150:
        if trend == "收窄":
            return 1
        if trend == "持平":
            return 0
        return -1
    if -250 <= value < -200:
        if trend == "收窄":
            return 0
        if trend == "持平":
            return 0
        return -1
    if -300 <= value < -250:
        return 0 if trend == "收窄" else -1
    # value < -300（深度倒挂）
    if trend in ("走阔", "加速走阔"):
        return -2
    return -1


def score_m1_m2_spread(
    value: Optional[float],
    trend: str = "持平",
    spread_6m: Optional[float] = None,
) -> int:
    """M1-M2 剪刀差打分（单位 %，M1同比 - M2同比）"""
    if value is None:
        return 0
    effective_trend = trend
    if effective_trend == "持平" and spread_6m is not None:
        effective_trend = infer_m1_m2_trend(value, spread_6m)

    if effective_trend == "收窄":
        return 2 if value > -3 else 1
    if effective_trend == "走阔":
        return -2 if value <= -8 else -1
    # 持平：极端水平仍给出方向信号
    if value > -2:
        return 1
    if value <= -8:
        return -1
    return 0


def score_vix(value: Optional[float]) -> int:
    """VIX 打分"""
    if value is None:
        return 0
    if value < 14:
        return 2
    if 14 <= value < 18:
        return 1
    if 18 <= value <= 22:
        return 0
    if 22 < value <= 28:
        return -1
    return -2  # > 28


def score_north_money_3d(value: Optional[float]) -> int:
    """北向资金 3 日累计打分（单位：亿元）"""
    if value is None:
        return 0
    if value > 100:
        return 2
    if 50 < value <= 100:
        return 1
    if -50 <= value <= 50:
        return 0
    if -100 <= value < -50:
        return -1
    return -2  # < -100


def score_credit_spread(value: Optional[float]) -> int:
    """美国高收益债利差（OAS）打分（单位：bp）"""
    if value is None:
        return 0
    if value < 350:
        return 2
    if 350 <= value < 450:
        return 1
    if 450 <= value <= 550:
        return 0
    if 550 < value <= 700:
        return -1
    return -2  # > 700


# ============ 仓位映射 ============
def map_score_to_allocation(score: float) -> Dict[str, int]:
    """总分映射到仓位"""
    if score >= 1.5:
        return {"equity": 85, "bond": 10, "gold": 5, "cash": 0}
    if score >= 0.5:
        return {"equity": 65, "bond": 25, "gold": 10, "cash": 0}
    if score >= -0.5:
        return {"equity": 45, "bond": 35, "gold": 10, "cash": 10}
    if score >= -1.5:
        return {"equity": 25, "bond": 40, "gold": 15, "cash": 20}
    return {"equity": 10, "bond": 40, "gold": 20, "cash": 30}


def map_score_to_label(score: float) -> str:
    """总分映射到叙事标签"""
    if score >= 1.5:
        return "全面扩张"
    if score >= 0.5:
        return "温和复苏"
    if score >= -0.5:
        return "结构分化"
    if score >= -1.5:
        return "收缩压力"
    return "系统性风险"


def map_score_to_bias(score: float) -> str:
    """总分映射到 RISK ON/OFF"""
    if score > 0.3:
        return "RISK_ON"
    if score < -0.3:
        return "RISK_OFF"
    return "NEUTRAL"


# ============ 观点话术映射 ============
def get_view_comment(factor: str, value: Optional[float], signal: int) -> Dict[str, str]:
    """获取观点话术"""
    if value is None:
        return {"view": "缺数据", "narrative": "暂无可用数据，不计入加权评分"}

    views = {
        "cn_us_spread": {
            2: ("资本回流中国", "人民币资产吸引力上升，外资加速配置中国"),
            1: ("利差收窄", "资本外流压力边际减弱"),
            0: ("利差稳定", "中美利差维持现状，外资观望"),
            -1: ("资本外流压力", "美元资产回报率相对更高，人民币资产承压"),
            -2: ("资本外流加剧", "利差深度倒挂且走阔，外资加速撤离人民币资产"),
        },
        "m1_m2_spread": {
            2: ("资金活化", "企业投资意愿回升，流动性基础坚实"),
            1: ("资金活化迹象", "M1增速改善，资金活化度边际提高"),
            0: ("结构分化", "剪刀差变动有限，实体需求仍在观察"),
            -1: ("资金沉淀", "剪刀差走阔，企业活期意愿不足"),
            -2: ("通缩压力", "资金深度沉淀，需求偏弱"),
        },
        "vix": {
            2: ("低波动偏多", "市场风险偏好高，情绪平稳，但需留意低波动后的变盘风险"),
            1: ("风险偏好正常", "市场情绪健康，专注结构性机会"),
            0: ("波动正常区间", "VIX处于历史正常区间"),
            -1: ("风险偏好下降", "恐慌情绪升温，建议加强防御"),
            -2: ("恐慌性抛售", "市场剧烈避险，短期承压但极端峰值常对应中期底部"),
        },
        "north_money": {
            2: ("外资大幅流入", "北向资金显著回补A股头寸"),
            1: ("外资温和流入", "北向资金持续净买入"),
            0: ("外资观望", "北向资金小幅波动，等待信号明确"),
            -1: ("外资小幅流出", "外资谨慎减仓"),
            -2: ("外资大幅撤离", "外资集中流出，需警惕汇率或地缘扰动"),
        },
        "credit_spread": {
            2: ("信用畅通", "高收益债利差极低，企业融资环境宽松"),
            1: ("信用宽松", "信用环境友好，高风险企业融资顺畅"),
            0: ("信用正常", "信用环境健康，企业再融资压力可控"),
            -1: ("信用收紧", "利差走阔，高风险企业再融资承压"),
            -2: ("信用冻结", "流动性压力传导，违约风险担忧显著升温"),
        },
    }

    if factor in views and signal in views[factor]:
        signal_text, narrative = views[factor][signal]
    else:
        signal_text, narrative = "未知", "数据不足"

    return {
        "view": signal_text,
        "narrative": narrative,
    }


# ============ 信号合成主函数 ============
@dataclass
class FactorResult:
    name: str
    name_cn: str
    value: Optional[float]
    signal: int
    weight: float
    contribution: float
    trend: str
    view: str
    narrative: str


@dataclass
class ScoreResult:
    bias: str
    confidence: int
    score: float
    label: str
    primary_driver: List[str]
    suggestions: Dict[str, int]
    narrative: str
    factor_details: List[FactorResult]


def calculate_risk_score(
    cn_us_spread: Optional[float] = None,
    cn_us_spread_trend: str = "持平",
    m1_m2_spread: Optional[float] = None,
    m1_m2_spread_trend: str = "持平",
    m1_m2_spread_6m: Optional[float] = None,
    vix: Optional[float] = None,
    north_money_3d: Optional[float] = None,
    credit_spread: Optional[float] = None,
) -> ScoreResult:
    """计算 RISK ON/OFF 评分（缺失因子不参与分母，避免稀释总分）"""

    effective_m1_trend = m1_m2_spread_trend
    if effective_m1_trend == "持平" and m1_m2_spread is not None and m1_m2_spread_6m is not None:
        effective_m1_trend = infer_m1_m2_trend(m1_m2_spread, m1_m2_spread_6m)

    factor_values = {
        "cn_us_spread": cn_us_spread,
        "m1_m2_spread": m1_m2_spread,
        "vix": vix,
        "north_money": north_money_3d,
        "credit_spread": credit_spread,
    }

    signals = {
        "cn_us_spread": score_cn_us_spread(cn_us_spread, cn_us_spread_trend),
        "m1_m2_spread": score_m1_m2_spread(m1_m2_spread, effective_m1_trend, m1_m2_spread_6m),
        "vix": score_vix(vix),
        "north_money": score_north_money_3d(north_money_3d),
        "credit_spread": score_credit_spread(credit_spread),
    }

    available_weight = sum(
        weight for factor, weight in WEIGHTS.items() if factor_values[factor] is not None
    )

    factor_names = {
        "cn_us_spread": ("中美利差", "bp"),
        "m1_m2_spread": ("M1-M2剪刀差", "%"),
        "vix": ("VIX恐慌指数", ""),
        "north_money": ("北向资金3日累计", "亿"),
        "credit_spread": ("高收益债利差", "bp"),
    }

    trends = {
        "cn_us_spread": cn_us_spread_trend if cn_us_spread is not None else "缺数据",
        "m1_m2_spread": effective_m1_trend if m1_m2_spread is not None else "缺数据",
        "vix": (
            "缺数据" if vix is None
            else ("平稳" if 14 <= vix <= 22 else ("偏高" if vix > 22 else "偏低"))
        ),
        "north_money": (
            "缺数据" if north_money_3d is None
            else ("流入" if north_money_3d > 50 else ("流出" if north_money_3d < -50 else "观望"))
        ),
        "credit_spread": (
            "缺数据" if credit_spread is None
            else ("平稳" if 350 <= credit_spread <= 550 else ("走扩" if credit_spread > 550 else "收窄"))
        ),
    }

    factor_details: List[FactorResult] = []
    driver_candidates = []

    for factor, weight in WEIGHTS.items():
        value = factor_values[factor]
        signal = signals[factor]
        trend = trends[factor]
        name_cn, _ = factor_names[factor]
        eff_weight = (weight / available_weight) if (value is not None and available_weight > 0) else 0.0
        contribution = signal * eff_weight
        view_info = get_view_comment(factor, value, signal)

        if value is not None and signal != 0:
            driver_candidates.append((abs(contribution), f"{name_cn}{view_info['view']}"))

        factor_details.append(FactorResult(
            name=factor,
            name_cn=name_cn,
            value=value,
            signal=signal,
            weight=weight,
            contribution=round(contribution, 3),
            trend=trend,
            view=view_info["view"],
            narrative=view_info["narrative"],
        ))

    if available_weight <= 0:
        return ScoreResult(
            bias="NEUTRAL",
            confidence=0,
            score=0.0,
            label="因子不足",
            primary_driver=["暂无可用因子"],
            suggestions={},
            narrative="核心因子均暂无数据，仓位暂不下结论。",
            factor_details=factor_details,
        )

    raw_weighted = sum(
        signals[f] * WEIGHTS[f] for f in WEIGHTS if factor_values[f] is not None
    )
    total_score = round(raw_weighted / available_weight, 2)
    total_weight = sum(WEIGHTS.values())
    confidence = min(95, max(20, round((available_weight / total_weight) * 95)))

    bias = map_score_to_bias(total_score)
    label = map_score_to_label(total_score)
    suggestions = map_score_to_allocation(total_score)

    driver_candidates.sort(key=lambda item: item[0], reverse=True)
    primary_drivers = [text for _, text in driver_candidates[:3]]
    if not primary_drivers:
        primary_drivers = ["有效因子均呈中性"]

    narrative_parts = []
    if vix is not None:
        narrative_parts.append(f"VIX {vix:.2f}")
    if cn_us_spread is not None:
        narrative_parts.append(f"中美利差 {round(cn_us_spread)}bp")
    if m1_m2_spread is not None:
        if m1_m2_spread_6m is not None:
            narrative_parts.append(
                f"M1-M2 {m1_m2_spread:.1f}%（较6个月前{effective_m1_trend}）"
            )
        else:
            narrative_parts.append(f"M1-M2 {m1_m2_spread:.1f}%")
    if credit_spread is not None:
        narrative_parts.append(f"高收益债利差 {round(credit_spread)}bp")
    if north_money_3d is not None:
        narrative_parts.append(f"北向3日 {north_money_3d:.1f}亿")
    narrative_parts.append(f"综合评估为{label}")
    narrative = "，".join(narrative_parts) + "。"

    return ScoreResult(
        bias=bias,
        confidence=confidence,
        score=total_score,
        label=label,
        primary_driver=primary_drivers,
        suggestions=suggestions,
        narrative=narrative,
        factor_details=factor_details,
    )
