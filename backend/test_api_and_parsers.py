"""后端 API 路由、趋势工具与快照解析函数的单元测试（不访问外网）。"""

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend import main as backend_main
from scripts import fetch_public_snapshot as snap


class TrendAndParserTests(unittest.TestCase):
    def test_get_trend_invert_for_us_yield_proxy(self):
        # 美债收益率从 4.0 升到 4.5，倒挂走阔 -> invert=True 应返回 "走阔"
        history = [{"date": f"2026-10-{i:02d}", "value": 4.0} for i in range(1, 15)]
        self.assertEqual(backend_main.get_trend(4.5, history, invert=True), "走阔")
        # 美债收益率从 4.0 降到 3.5，倒挂收窄 -> invert=True 应返回 "收窄"
        self.assertEqual(backend_main.get_trend(3.5, history, invert=True), "收窄")
        self.assertEqual(backend_main.get_trend(4.02, history, invert=True), "持平")

    def test_pbc_flow_month_disambiguates_october(self):
        seen = set()
        jan = snap._flow_month("2025.1", seen)
        self.assertEqual(jan, "2025-01")
        seen.add(jan)
        october = snap._flow_month("2025.1", seen)
        self.assertEqual(october, "2025-10")

    def test_sum_through_requires_complete_ytd_months(self):
        points = [("2026-01", 100.0), ("2026-02", 200.0), ("2026-03", 300.0)]
        self.assertEqual(snap._sum_through(points, 2026, 3), 600.0)
        self.assertIsNone(snap._sum_through([("2026-01", 100.0), ("2026-03", 300.0)], 2026, 3))


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        backend_main.clear_cache()

    def test_routes_registered(self):
        paths = {getattr(route, "path", None) for route in backend_main.app.routes}
        for expected in (
            "/api/v1/health",
            "/api/v1/dashboard",
            "/api/v1/overview",
            "/api/v1/china-core",
            "/api/v1/global-macro",
            "/api/v1/fx-liquidity",
            "/api/v1/assets",
            "/api/v1/risk",
            "/api/v1/vix-history",
            "/api/v1/public-snapshot",
            "/api/v1/bull-liquidity",
            "/api/v1/brief",
            "/api/v1/events",
        ):
            self.assertIn(expected, paths)

    def test_health_endpoint(self):
        body = backend_main.health_check()
        self.assertEqual(body["status"], "ok")
        self.assertIn("public_snapshot", body)
        self.assertIn("bull_liquidity", body)

    def test_dashboard_cache_and_fx_liquidity_offline(self):
        mock_em = {
            "us_ism_pmi": {"value": 50.2, "date": "2026年10月", "source": "东方财富", "unit": ""},
            "us_cpi_yy": {"value": 2.6, "date": "2026年10月", "source": "东方财富", "unit": "%"},
            "fed_funds_rate": {"value": 4.25, "high": 4.5, "range": "4.25–4.50", "date": "2026-11", "source": "东方财富"},
            "source_note": "mock",
        }
        with patch.object(backend_main, "eastmoney_global_macro", return_value=mock_em) as mocked_em:
            payload = backend_main.get_dashboard(refresh=True)
            self.assertIn("overview", payload)
            self.assertIn("factor_details", payload["overview"])
            self.assertEqual(payload["global_macro"]["us_ism_pmi"]["value"], 50.2)

            # 第二次调用应命中 TTL 缓存，不再重复拉取东方财富
            _ = backend_main.get_overview()
            self.assertEqual(mocked_em.call_count, 1)

            # fx-liquidity 之前因 fetch_yfinance 参数个数错误会 500，这里验证正常返回，并含 10Y-2Y 利差
            fx = backend_main.get_fx_liquidity()
            self.assertIn("cn_us_10y_spread", fx)
            self.assertIn("us_10y_2y_spread", fx)

            # 简报接口应命中缓存并输出 Markdown
            brief = backend_main.get_daily_brief()
            self.assertIn("每日宏观简报", brief["markdown"])
            self.assertEqual(mocked_em.call_count, 1)

            # 宏观日历应返回未来事件列表（含央行议息会议）
            events_resp = backend_main.get_events(days=30)
            self.assertTrue(len(events_resp["events"]) >= 4)

            from datetime import date
            dec_events = backend_main.build_macro_calendar(date(2026, 11, 23), days=30)
            rate_titles = [ev["title"] for ev in dec_events if ev.get("category") == "rate"]
            self.assertTrue(any("FOMC" in t for t in rate_titles))
            self.assertTrue(any("ECB" in t for t in rate_titles))
            self.assertTrue(any("BOJ" in t for t in rate_titles))

    def test_bull_liquidity_endpoint(self):
        body = backend_main.get_bull_liquidity()
        self.assertIn("stage", body)
        self.assertIn("conditions", body)


if __name__ == "__main__":
    unittest.main()
