"""
宏观仪表盘主动推送脚本（支持飞书 / 企业微信 / 通用 Webhook）。

通过环境变量配置：
    ALERT_WEBHOOK_URL  Webhook 地址（为空时静默跳过，不报错）
    ALERT_MODE         "feishu"（默认）| "wecom" | "raw"
    ALERT_ONLY_ON_WARN 设为 "1" 时仅在 RISK_OFF 或 VIX >= 25 时推送；默认每日推送简报

用法：
    python scripts/send_alert.py
"""

from __future__ import annotations

import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend import main as backend_main  # noqa: E402


def build_payload(mode: str, title: str, markdown: str) -> dict:
    if mode == "wecom":
        return {"msgtype": "markdown", "markdown": {"content": markdown}}
    if mode == "raw":
        return {"title": title, "content": markdown}
    # 飞书自定义机器人默认 text 格式（兼容性最好）
    return {"msg_type": "text", "content": {"text": markdown}}


def main() -> None:
    webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        print("未配置 ALERT_WEBHOOK_URL，跳过推送。")
        return

    mode = os.getenv("ALERT_MODE", "feishu").strip().lower()
    only_warn = os.getenv("ALERT_ONLY_ON_WARN", "0").strip() == "1"

    dashboard = backend_main.get_dashboard(refresh=True)
    bull = backend_main.load_bull_liquidity_report()
    overview = dashboard.get("overview") or {}
    vix_val = ((dashboard.get("risk_monitor") or {}).get("vix") or {}).get("value")

    is_warn = (
        overview.get("bias") == "RISK_OFF"
        or (vix_val is not None and vix_val >= 25)
    )
    if only_warn and not is_warn:
        print("当前未触发预警阈值，跳过推送。")
        return

    markdown = backend_main.format_daily_brief_markdown(dashboard, bull)
    title = f"宏观简报 · {overview.get('label', '--')} ({overview.get('score', '--')})"
    payload = build_payload(mode, title, markdown)

    resp = requests.post(webhook, json=payload, timeout=15)
    resp.raise_for_status()
    print(f"Webhook 推送成功 ({resp.status_code})。")


if __name__ == "__main__":
    main()
