# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_diag_chk_quant2.py
"""精确定位：`.env` 清空后 `chk_quant` 为何仍 PASS。

## 手法
逐层拆开，看**每一步的真实输出**：
1. 清空 `.env` 后，直接跑 `chk_quant` 用的那段代码，**打印子进程原始输出**（脱敏）；
2. 打印 `_health.run()` 的 returncode；
3. 打印 `chk_quant` 拿到的 `out`（脱敏后）与它的分支判定。

⚠️ 输出里的凭证值一律**用长度与前缀替代**，不原样打印。
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def redact(s: str) -> str:
    """把形如 SEC_USER_AGENT=... 的值替换成 <len=N>；并把邮箱打码。"""
    s = re.sub(r"SEC_USER_AGENT\s*=\s*\S+", "SEC_USER_AGENT=<redacted>", s)
    s = re.sub(r"[\w.+-]+@[\w.-]+", "<email-redacted>", s)
    return s


def main() -> int:
    spec = importlib.util.spec_from_file_location("_h_d2", ROOT / "scripts" / "_health.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    print("=" * 92)
    print("精确诊断：chk_quant 在 .env 清空后的行为")
    print("=" * 92)

    env_file = ROOT / ".env"
    orig = env_file.read_text(encoding="utf-8")

    print(f"\n① 路径一致性")
    print(f"   probe ROOT      = {ROOT}")
    print(f"   _health.ROOT    = {h.ROOT}")
    print(f"   相同: {Path(h.ROOT).resolve() == ROOT}")

    try:
        env_file.write_text("# cleared for diagnosis\n", encoding="utf-8", newline="\n")
        print(f"\n② 已清空 .env（{env_file}）")

        # ── 直接跑那段代码，看子进程原始输出 ──
        code = ("import sys; sys.path.insert(0, r'%s');"
                "from quant import screener_engine, stock_pools, edgar_fundamentals, price_history;"
                "ua = edgar_fundamentals.SEC_USER_AGENT;"
                "assert '@' in ua and 'admin@example.com' not in ua, f'SEC 凭证未配置或为默认占位符: {ua}';"
                "print('OK')" % str(ROOT))
        rc, out = h.run([h.PY, "-c", code])
        print(f"\n③ 子进程 rc = {rc}")
        print(f"   输出（脱敏，取前 300 字符）：\n   {redact(out.strip())[:300]!r}")

        # ── chk_quant 的分支判定 ──
        print(f"\n④ 分支判定")
        print(f"   'OK' in out                    : {'OK' in out}")
        print(f"   'No module named' in out       : {'No module named' in out}")
        print(f"   'ModuleNotFoundError' in out   : {'ModuleNotFoundError' in out}")
        st, msg = h.chk_quant()
        print(f"   chk_quant() → {st}：{redact(msg)[:100]}")

        print(f"\n⑤ 判定")
        if st == "PASS" and "OK" not in out:
            print("   ✗ **真 bug**：既没打印 OK，也没走缺依赖分支，却返回 PASS")
        elif st == "PASS" and "OK" in out:
            print("   ⇒ 子进程确实打印了 OK ⇒ 说明它读到了**非默认**凭证")
            print("     需再查：load_dotenv 是否从别处（外部缓存/环境）取到了值")
        else:
            print(f"   ⇒ 返回 {st}，行为合理")
    finally:
        env_file.write_text(orig, encoding="utf-8", newline="\n")
        assert env_file.read_text(encoding="utf-8") == orig
        print("\n（.env 已还原并逐字节核对）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
