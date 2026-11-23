"""信号合成引擎的单元测试（不访问网络）。"""

import unittest

from signal_engine import (
    calculate_risk_score,
    infer_m1_m2_trend,
    score_cn_us_spread,
    score_credit_spread,
    score_m1_m2_spread,
    score_north_money_3d,
    score_vix,
)


class SignalEngineTests(unittest.TestCase):
    def test_cn_us_spread_covers_all_bands(self):
        self.assertEqual(score_cn_us_spread(-120, "收窄"), 2)
        self.assertEqual(score_cn_us_spread(-120, "持平"), 1)
        self.assertEqual(score_cn_us_spread(-180, "收窄"), 1)
        self.assertEqual(score_cn_us_spread(-220, "持平"), 0)
        self.assertEqual(score_cn_us_spread(-270, "持平"), -1)
        self.assertEqual(score_cn_us_spread(-320, "持平"), -1)
        self.assertEqual(score_cn_us_spread(-320, "走阔"), -2)
        self.assertEqual(score_cn_us_spread(-320, "加速走阔"), -2)

    def test_m1_m2_spread_and_trend_inference(self):
        self.assertEqual(infer_m1_m2_trend(-2.7, -3.6), "收窄")
        self.assertEqual(infer_m1_m2_trend(-5.0, -4.0), "走阔")
        self.assertEqual(infer_m1_m2_trend(-3.0, -3.2), "持平")

        self.assertEqual(score_m1_m2_spread(-2.7, spread_6m=-3.6), 2)
        self.assertEqual(score_m1_m2_spread(-4.5, spread_6m=-5.5), 1)
        self.assertEqual(score_m1_m2_spread(-2.0, "走阔"), -1)
        self.assertEqual(score_m1_m2_spread(-8.5, "走阔"), -2)

    def test_vix_north_credit_scoring(self):
        self.assertEqual(score_vix(13.5), 2)
        self.assertEqual(score_vix(16.0), 1)
        self.assertEqual(score_vix(20.0), 0)
        self.assertEqual(score_vix(25.0), -1)
        self.assertEqual(score_vix(32.0), -2)

        self.assertEqual(score_north_money_3d(120), 2)
        self.assertEqual(score_north_money_3d(-120), -2)

        self.assertEqual(score_credit_spread(310), 2)
        self.assertEqual(score_credit_spread(400), 1)
        self.assertEqual(score_credit_spread(500), 0)
        self.assertEqual(score_credit_spread(620), -1)
        self.assertEqual(score_credit_spread(750), -2)

    def test_all_missing_returns_insufficient(self):
        result = calculate_risk_score()
        self.assertEqual(result.bias, "NEUTRAL")
        self.assertEqual(result.confidence, 0)
        self.assertEqual(result.label, "因子不足")
        self.assertEqual(result.suggestions, {})

    def test_missing_north_money_does_not_dilute_score(self):
        # 4 个有效因子全部给 +2，归一化后总分应为 2.0，而不是被缺失的北向资金稀释成 1.7
        result = calculate_risk_score(
            cn_us_spread=-100,
            cn_us_spread_trend="收窄",
            m1_m2_spread=-2.0,
            m1_m2_spread_6m=-3.0,
            vix=12.0,
            north_money_3d=None,
            credit_spread=300,
        )
        self.assertEqual(result.score, 2.0)
        self.assertEqual(result.bias, "RISK_ON")
        self.assertEqual(result.label, "全面扩张")
        self.assertEqual(result.suggestions["equity"], 85)

    def test_risk_off_includes_negative_drivers(self):
        result = calculate_risk_score(
            cn_us_spread=-330,
            cn_us_spread_trend="走阔",
            m1_m2_spread=-9.0,
            m1_m2_spread_6m=-7.5,
            vix=30.0,
            credit_spread=720,
        )
        self.assertEqual(result.bias, "RISK_OFF")
        self.assertEqual(result.score, -2.0)
        self.assertTrue(len(result.primary_driver) > 0)
        self.assertNotIn("有效因子均呈中性", result.primary_driver)


if __name__ == "__main__":
    unittest.main()
