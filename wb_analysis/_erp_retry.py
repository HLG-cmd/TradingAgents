# lifecycle: reusable
# created: 2026-09-23
# note: 更彻底的做法是把这段重试逻辑直接并进 erp_context.py（目前 erp_context 无重试）
# usage: ./.venv/Scripts/python.exe wb_analysis/_erp_retry.py
"""ERP 计算的重试包装器。

背景：2026-09-17 本机访问 api.stlouisfed.org 出现间歇性 TimeoutError
（multpl.com 正常）。erp_context.py 的 _get 只做单次调用、timeout=30，
一次抖动即导致整次计算失败。本包装器在不改变任何计算逻辑的前提下，
只把 _get 替换为「带指数退避的重试版本」。

用法: python wb_analysis/_erp_retry.py --start 1990-01-01 [--append]
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import wb_analysis.erp_context as ec  # noqa: E402


def robust_get(url: str, timeout: int = 30) -> str:
    last = None
    for i in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = 3 * (i + 1)
            print(f"  [retry {i + 1}/6] {type(exc).__name__}: {exc} -> 等待 {wait}s", flush=True)
            time.sleep(wait)
    raise last  # type: ignore[misc]


ec._get = robust_get

if __name__ == "__main__":
    raise SystemExit(ec.main())
