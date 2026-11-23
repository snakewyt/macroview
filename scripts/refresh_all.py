"""
一键刷新本地宏观数据：
1. 先运行 fetch_public_snapshot.py 生成 data/public_snapshot.json（含 GC001）
2. 再运行 fetch_bull_liquidity.py 生成 data/bull_liquidity.json
3. 可选传 --push 自动提交并推送 data/*.json 到 GitHub

用法：
    python scripts/refresh_all.py
    python scripts/refresh_all.py --push
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_step(script_name: str) -> None:
    script_path = os.path.join(ROOT, "scripts", script_name)
    print(f"\n=== 运行 {script_name} ===")
    subprocess.run([sys.executable, script_path], cwd=ROOT, check=True)


def git_push() -> None:
    print("\n=== 提交并推送 data/*.json ===")
    subprocess.run(
        ["git", "add", "data/public_snapshot.json", "data/bull_liquidity.json"],
        cwd=ROOT,
        check=True,
    )
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )
    if diff.returncode == 0:
        print("数据无变更，跳过 commit。")
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    subprocess.run(
        ["git", "commit", "-m", f"chore(data): refresh macro snapshot {stamp}"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=ROOT, check=True)
    print("已推送到远端仓库。")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键刷新宏观仪表盘本地数据")
    parser.add_argument("--push", action="store_true", help="刷新后自动 git commit & push")
    args = parser.parse_args()

    run_step("fetch_public_snapshot.py")
    run_step("fetch_bull_liquidity.py")
    if args.push:
        git_push()
    print("\n全部刷新完成。")


if __name__ == "__main__":
    main()
