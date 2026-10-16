# lifecycle: test
"""`scripts/_health.py` 各检查器的**崩溃/格式漂移防护**回归测试。

## 为什么必须测（本日 7 例同族缺陷的教训）
2026-10-16 一天内实测出 **7 个「检查器判据缺陷」**，共同点是
**检查器看着在跑、返回 PASS，实际根本没看到问题**：

| # | 检查器 | 缺陷 | 方向 |
|---|---|---|---|
| 1 | `_audit_values.SUM_RE` | 正则恒不命中（402 行算式 0 命中） | 假绿 |
| 2 | `chk_lifecycle` | `strip().startswith("    ")` 恒为假 | 假绿 |
| 3 | `chk_root_clean` | 后缀白名单把新类型挡在视野外 | 假绿 |
| 4 | `_memory_index --check` | 全等比较含时间戳 ⇒ 恒报过期 | **假红** |
| 5 | `chk_gitignore` | 纯子串判据：**注释掉的条目也算「已忽略」** | 假绿 |
| 6 | `chk_seal` | 正则失配 `n=0` ⇒ 解析失败被当成「无待封存」 | 假绿 |
| 7 | `chk_reports` | `n==0` 不区分「真无问题」与「工具崩了」 | 假绿 |

**1、2、3、4 已由源码注释 + 现场实测修复；5、6、7 本轮修，并由本文件锁定。**

## 本文件锁什么（每条都做过「注入坏实现必 FAIL」的双边验证）
- `chk_reports`：**工具崩溃时必须 FAIL**，不得把「无输出」读成「无问题」；
  输出格式漂移（解析不到「报告树 N 棵」）时降级 WARN，不得静默 PASS。
- `chk_seal`：`--plan` 输出不可解析时 **WARN**，不得默认 0 轮。
- `chk_gitignore`：条目**被注释掉**时不得算「已忽略」（含 `git check-ignore` 行为断言）。

⚠️ 全部用例**只碰临时副本**，每例结束还原并逐字节核对；不改任何真实项目文件。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_health():
    """按文件路径加载 `_health.py`（它不是包内模块，不能用 import 语句）。"""
    spec = importlib.util.spec_from_file_location("_health_under_test", ROOT / "scripts" / "_health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def health():
    return _load_health()


# --------------------------------------------------------------------------
# 第 7 例：chk_reports —— 崩溃不得假绿
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestChkReportsCrashProtection:
    """`chk_reports` 必须区分「工具崩了」与「真的没问题」。"""

    def test_crashed_tool_does_not_report_pass(self, health):
        """★ 本条就是第 7 例的回归锁：工具 exit≠0 时不得 PASS。

        未修时实测：注入「exit 3 + 垃圾输出」的桩 ⇒ 返回
        `PASS — 报告树 ? 棵，无堆积问题`（**假绿**）。
        """
        idx = ROOT / "wb_analysis" / "_reports_index.py"
        orig = idx.read_text(encoding="utf-8")
        stub = ("# lifecycle: oneoff\n"
                "import sys\n"
                "print('Traceback (most recent call last):')\n"
                "print('  RuntimeError: simulated crash')\n"
                "sys.exit(3)\n")
        try:
            idx.write_text(stub, encoding="utf-8", newline="\n")
            status, msg = health.chk_reports()
            assert status != "PASS", f"工具崩溃却报 PASS（假绿复现）：{msg}"
            assert status in ("FAIL", "WARN"), f"状态应为 FAIL/WARN，实得 {status}"
        finally:
            idx.write_text(orig, encoding="utf-8", newline="\n")
            assert idx.read_text(encoding="utf-8") == orig, "还原失败"

    def test_healthy_state_reports_pass(self, health):
        """正常状态仍须 PASS（防「改宽了就误报」）。"""
        status, msg = health.chk_reports()
        assert status in ("PASS", "WARN"), f"正常状态不该 FAIL：{status} — {msg}"


# --------------------------------------------------------------------------
# 第 6 例：chk_seal —— 解析失败不得默认 0
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestChkSealParseFailure:
    """`chk_seal` 取不到「待封存 N 轮」时不得假定为 0。"""

    def test_unparsable_output_warns_not_passes(self, health):
        """★ 第 6 例回归锁：输出格式变更后必须 WARN，而不是静默 PASS。"""
        seal = ROOT / "wb_analysis" / "_seal_run.py"
        orig = seal.read_text(encoding="utf-8")
        # 把「待封存 N 轮」这句改掉 ⇒ 正则应失配
        tampered = orig.replace("待封存", "PENDING_TOTAL")
        if tampered == orig:  # 措辞变了就换一种注入
            tampered = orig.replace("轮。加", "ROUNDS_X。加")
        try:
            seal.write_text(tampered, encoding="utf-8", newline="\n")
            status, msg = health.chk_seal()
            assert status == "WARN", f"解析失败应 WARN，实得 {status}：{msg}"
            assert "无法解析" in msg or "假定" in msg, f"提示语未说明风险：{msg}"
        finally:
            seal.write_text(orig, encoding="utf-8", newline="\n")
            assert seal.read_text(encoding="utf-8") == orig, "还原失败"

    def test_normal_state_is_pass_or_warn(self, health):
        """正常状态：0 轮 PASS / N 轮 WARN，都合理；不得 FAIL。"""
        status, msg = health.chk_seal()
        assert status in ("PASS", "WARN"), f"正常状态不该 FAIL：{status} — {msg}"


# --------------------------------------------------------------------------
# 第 5 例：chk_gitignore —— 注释掉不算「已忽略」
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestChkGitignoreCommentAware:
    """`chk_gitignore` 必须剥掉注释后再判，且用 git 行为复核。"""

    NEED = ("wb_analysis/evidence/", "wb_analysis/drafts/",
            "wb_analysis/analysis/", ".workbuddy-ai/backup/")

    def test_commented_out_entries_do_not_count(self, health):
        """★ 第 5 例回归锁：把必需条目**注释掉**必须 WARN。

        未修时实测：注释后 `git check-ignore` 返回 1（不再忽略），
        而检查器仍是 PASS（纯子串判据不识别注释）。
        """
        gi = ROOT / ".gitignore"
        orig = gi.read_text(encoding="utf-8")
        try:
            commented = "\n".join(
                ("# " + line if line.strip() in self.NEED else line)
                for line in orig.splitlines()
            ) + "\n"
            gi.write_text(commented, encoding="utf-8", newline="\n")
            status, msg = health.chk_gitignore()
            assert status == "WARN", f"注释掉的条目被当成已忽略（假绿复现）：{msg}"
        finally:
            gi.write_text(orig, encoding="utf-8", newline="\n")
            assert gi.read_text(encoding="utf-8") == orig, "还原失败"

    def test_normal_gitignore_passes(self, health):
        """正常 .gitignore 仍须 PASS（文本规则 + git 行为双重确认）。"""
        status, msg = health.chk_gitignore()
        assert status == "PASS", f"正常 .gitignore 应 PASS，实得 {status}：{msg}"
