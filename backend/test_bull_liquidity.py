"""A股牛市流动性条件的规则测试。不访问网络。"""

import unittest

from bull_liquidity import evaluate_bear_liquidity, evaluate_bull_liquidity


def _monthly(start, values):
    year, month = start
    points = []
    for value in values:
        points.append({"date": f"{year:04d}-{month:02d}", "value": value})
        month += 1
        if month == 13:
            month = 1
            year += 1
    return points


class BullLiquidityTests(unittest.TestCase):
    def test_launch_soil_when_first_five_hold(self):
        report = evaluate_bull_liquidity({
            "m2_yoy": _monthly((2024, 1), [7.0, 7.2, 7.5, 7.8, 8.0, 8.2, 8.4, 8.6]),
            "nominal_gdp_yoy": [
                {"date": "2024-03", "value": 4.0},
                {"date": "2024-06", "value": 4.0},
                {"date": "2024-09", "value": 4.0},
            ],
            "m1_yoy": _monthly((2024, 1), [2.0, 1.8, 1.5, 1.2, 1.0, 0.9, 0.8, 0.7]),
            "lpr_1y": _monthly((2024, 1), [3.45, 3.45, 3.45, 3.45, 3.45, 3.45, 3.35, 3.25]),
            "rrr": [
                {"date": "2024-02", "value": 10.5},
                {"date": "2024-05", "value": 10.0},
                {"date": "2024-08", "value": 9.5},
            ],
            "cn_10y": _monthly((2024, 1), [2.40, 2.35, 2.30, 2.28, 2.20, 2.15, 2.12, 2.05]),
            "credit_yoy": _monthly((2024, 1), [8.5, 8.5, 8.5, 8.5, 8.5, 8.5, 8.5, 8.5]),
            "industrial_profit_yoy": _monthly((2024, 1), [-8, -7, -6, -5, -4, -4, -3, -2]),
            "margin_balance": _monthly((2024, 1), [15000, 15000, 15000, 15000, 15000, 15000, 15000, 15000]),
        })
        status = {item["id"]: item["status"] for item in report["conditions"]}
        self.assertEqual(report["stage"], "启动土壤")
        self.assertEqual([status[i] for i in (1, 2, 3, 4, 5)], ["met"] * 5)
        self.assertEqual(status[6], "unmet")
        self.assertEqual(status[7], "unmet")
        self.assertEqual(status[8], "unmet")

    def test_main_uptrend_when_credit_and_earnings_follow(self):
        report = evaluate_bull_liquidity({
            "m2_yoy": _monthly((2024, 1), [8.0, 8.2, 8.4, 8.6, 8.8, 9.0, 9.2, 9.4]),
            "nominal_gdp_yoy": [{"date": "2024-06", "value": 5.0}],
            "m1_yoy": _monthly((2024, 1), [0.2, 0.1, 0.0, 0.4, 1.0, 1.8, 2.4, 3.0]),
            "lpr_1y": _monthly((2024, 1), [3.45, 3.45, 3.35, 3.35, 3.25, 3.10, 3.10, 3.00]),
            "rrr": [
                {"date": "2024-03", "value": 10.0},
                {"date": "2024-07", "value": 9.5},
            ],
            "cn_10y": _monthly((2024, 1), [2.30, 2.25, 2.20, 2.10, 2.00, 1.90, 1.85, 1.80]),
            "credit_yoy": _monthly((2024, 1), [8.0, 8.0, 7.8, 7.9, 8.2, 8.6, 9.0, 9.4]),
            "industrial_profit_yoy": _monthly((2024, 1), [-6, -4, -2, -1, 1, 3, 4, 6]),
            "margin_balance": _monthly((2024, 1), [14000, 14100, 14200, 14300, 14500, 14800, 15200, 15600]),
        })
        self.assertEqual(report["stage"], "主升条件")
        status = {item["id"]: item["status"] for item in report["conditions"]}
        self.assertEqual(status[8], "met")
        self.assertEqual(status[6], "met")
        self.assertEqual(status[7], "met")

    def test_tight_liquidity_stays_incomplete(self):
        report = evaluate_bull_liquidity({
            "m2_yoy": _monthly((2023, 10), [7.0, 6.8, 6.6, 6.4, 6.2, 6.0, 5.8, 5.6]),
            "nominal_gdp_yoy": [
                {"date": "2023-12", "value": 8.0},
                {"date": "2024-03", "value": 8.0},
            ],
            "lpr_1y": _monthly((2023, 10), [2.80, 2.90, 3.00, 3.10, 3.20, 3.30, 3.40, 3.50]),
            "rrr": [{"date": "2023-10", "value": 10.5}, {"date": "2024-05", "value": 10.5}],
            "cn_10y": _monthly((2023, 10), [2.10, 2.20, 2.30, 2.40, 2.50, 2.60, 2.70, 2.80]),
            "credit_yoy": _monthly((2023, 10), [8.4, 8.6, 8.8, 9.0, 9.2, 9.4, 9.6, 9.8]),
        })
        self.assertEqual(report["stage"], "条件未齐")
        status = {item["id"]: item["status"] for item in report["conditions"]}
        self.assertEqual(status[1], "unmet")
        self.assertEqual(status[2], "unmet")
        self.assertEqual(status[3], "unmet")
        self.assertEqual(status[5], "unmet")


class BearLiquidityTests(unittest.TestCase):
    def test_bear_soil_when_first_five_hold(self):
        report = evaluate_bear_liquidity({
            "m2_yoy": _monthly((2023, 1), [5.0] * 16),
            "nominal_gdp_yoy": [
                {"date": "2023-03", "value": 8.0},
                {"date": "2023-12", "value": 8.0},
                {"date": "2024-03", "value": 8.0},
            ],
            "m1_yoy": _monthly((2023, 1), [i * 0.2 for i in range(16)]),
            "lpr_1y": _monthly((2023, 1), [3.0] * 16),
            "rrr": [{"date": "2023-01", "value": 10.5}],
            "cn_10y": _monthly((2023, 1), [round(2.0 + i * 0.05, 2) for i in range(16)]),
            "credit_yoy": _monthly((2023, 1), [9.0] * 12 + [8.5, 8.0, 7.5, 7.0]),
            "industrial_profit_yoy": _monthly((2023, 1), [5.0] * 16),
            "margin_balance": _monthly((2023, 1), [15000] * 16),
            "gc001": [{"date": "2024-04", "value": 1.4}],
        })
        status = {item["id"]: item["status"] for item in report["conditions"]}
        self.assertEqual(report["stage"], "退潮土壤")
        self.assertEqual([status[i] for i in (1, 2, 3, 4, 5)], ["met"] * 5)
        self.assertEqual(status[6], "unmet")
        self.assertEqual(status[7], "unmet")
        self.assertEqual(status[8], "partial")

    def test_main_downtrend_when_credit_and_earnings_fall(self):
        report = evaluate_bear_liquidity({
            "m2_yoy": _monthly((2023, 1), [6.0] * 16),
            "nominal_gdp_yoy": [{"date": "2023-03", "value": 8.0}],
            "m1_yoy": _monthly((2023, 1), [4.0, 4.2, 4.4, 4.6, 4.8, 5.0, 4.6, 4.2, 3.8, 3.4, 3.0, 2.6, 2.2, 1.8, 1.4, 1.0]),
            "lpr_1y": _monthly((2023, 1), [3.0 + i * 0.05 for i in range(16)]),
            "rrr": [{"date": "2023-01", "value": 10.5}],
            "cn_10y": _monthly((2023, 1), [2.0 + i * 0.05 for i in range(16)]),
            "credit_yoy": _monthly((2023, 1), [9.0] * 12 + [8.4, 8.0, 7.4, 6.8]),
            "industrial_profit_yoy": _monthly((2023, 1), [6, 5, 4, 3, 2, 1, 0, -1, -1, -2, -2, -3, -3, -4, -4, -5]),
            "margin_balance": _monthly((2023, 1), [16000 - i * 50 for i in range(16)]),
            "gc001": [{"date": "2024-04", "value": 6.2}],
        })
        status = {item["id"]: item["status"] for item in report["conditions"]}
        self.assertEqual(report["stage"], "主跌条件")
        self.assertEqual(status[8], "met")
        self.assertEqual(status[6], "met")
        self.assertEqual(status[7], "met")
        self.assertEqual(status[1], "met")

    def test_positive_narrowing_excess_is_only_partial(self):
        report = evaluate_bear_liquidity({
            "m2_yoy": _monthly((2024, 1), [9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6]),
            "nominal_gdp_yoy": [{"date": "2024-03", "value": 6.0}],
            "lpr_1y": _monthly((2024, 1), [3.45, 3.35, 3.25, 3.10, 3.00, 3.00, 3.00, 3.00]),
            "cn_10y": _monthly((2024, 1), [2.40, 2.30, 2.20, 2.10, 2.00, 1.90, 1.80, 1.70]),
            "credit_yoy": _monthly((2024, 1), [8.0] * 8),
        })
        status = {item["id"]: item["status"] for item in report["conditions"]}
        self.assertEqual(status[1], "partial")
        self.assertEqual(status[2], "unmet")
        self.assertEqual(report["stage"], "条件未齐")


if __name__ == "__main__":
    unittest.main()
