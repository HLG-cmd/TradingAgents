# lifecycle: test
"""`_precheck.py` 回归测试 —— 锁住「门禁本身坏了要能识别」。

## 为什么测它
`_precheck.py` 是**交付前唯一入口**（7 项检查汇总成一张表）。
它坏了，所有交付都失去保护，而且**是静默失去**——
因为「非零退出码 = 检出了问题」这个朴素判断会产生两个方向的错误：

  · 检测器**崩溃后返回非零** ⇒ 看起来像「检出问题」（方向对但原因是错的，
    于是人去修不存在的问题，真正的问题被掩盖）；
  · 检测器**崩溃后返回 0** ⇒ 被当成「通过」（**最危险**）。

源码注释把这叫做「**坏掉的检测器伪装成干净的检测器**」——这与本日修复的
三个 bug（`SUM_RE` 恒不命中、`chk_lifecycle` 判据恒假、`chk_root_clean` 漏检后缀）
是**同一类**，所以必须锁住识别机制本身。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._precheck import crashed, run  # noqa: E402


@pytest.mark.unit
class TestCrashedDetection:
    """`crashed()` 必须能区分「工具崩了」与「工具检出了问题」。"""

    @pytest.mark.parametrize("out", [
        "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: boom",
        "前置输出\nTraceback (most recent call last):\n  ...",
    ])
    def test_traceback_is_detected(self, out):
        assert crashed(out) is True

    @pytest.mark.parametrize("out", [
        "✓ 全部通过",
        "✗ 评级词不合规：manager.md",
        "FAIL 2 项",
        "",                                   # 空输出
        "ValueError: 这是被工具捕获后打印的摘要，不是崩溃",   # 无 Traceback 头
    ])
    def test_normal_output_is_not_crash(self, out):
        """正常输出（含「检出了问题」的输出）**不得**被误判为崩溃。

        否则真问题会被当成工具故障而被忽略。
        """
        assert crashed(out) is False

    def test_crash_word_without_traceback_is_not_crash(self):
        """只有 'Traceback' 头才算 —— 正文里提到「崩溃」二字不算。"""
        assert crashed("本轮子智能体崩溃过一次，已恢复") is False


@pytest.mark.unit
class TestRunContract:
    """`run()` 的 cwd 固定与编码设置 —— 保证「从任何目录调用结果一致」。"""

    def test_returns_tuple_of_rc_and_output(self):
        rc, out = run([sys.executable, "-c", "print('hello')"])
        assert rc == 0
        assert "hello" in out

    def test_nonzero_rc_is_propagated(self):
        rc, _ = run([sys.executable, "-c", "import sys; sys.exit(7)"])
        assert rc == 7

    def test_stderr_is_merged_into_output(self):
        """stderr 必须并入返回值 —— 否则崩溃信息会丢。"""
        rc, out = run([sys.executable, "-c",
                       "import sys; print('to-stderr', file=sys.stderr); sys.exit(1)"])
        assert rc == 1
        assert "to-stderr" in out

    def test_crash_is_detectable_from_run_output(self):
        """端到端：真崩溃能被 crashed() 识别（两个函数协同）。"""
        rc, out = run([sys.executable, "-c", "raise ValueError('deliberate')"])
        assert rc != 0
        assert crashed(out) is True

    def test_runs_in_project_root(self):
        """cwd 固定为项目根：用相对路径读一个只在项目根存在的文件来验证。"""
        rc, out = run([sys.executable, "-c",
                       "from pathlib import Path; print(Path('pyproject.toml').exists())"])
        assert rc == 0
        assert "True" in out, "cwd 未固定在项目根"

    def test_utf8_encoding_is_forced(self):
        """强制 UTF-8：中文输出不应出现替换字符。"""
        rc, out = run([sys.executable, "-c",
                       "print('中文输出测试 均线 布林')"])
        assert rc == 0
        assert "中文输出测试" in out
        assert "\ufffd" not in out, "出现替换字符 ⇒ 编码被破坏"


@pytest.mark.unit
class TestMissingToolMustFailLoudly:
    """前置自检：工具缺失必须**显式失败**，不能被误读成「检出了问题」。

    源码注释记录的原因：`python 缺失的脚本.py` 只往 stderr 打一行
    「can't open file」并返回 2 —— 与「检出 2 个问题」的退出码无法区分。
    """

    def test_missing_script_yields_nonzero_and_recognizable_message(self):
        rc, out = run([sys.executable, "这个脚本不存在_zzz.py"])
        assert rc != 0
        low = out.lower()
        assert ("can't open file" in low or "no such file" in low
                or "not found" in low), f"缺失工具的报错不可识别：{out[:200]}"

    def test_missing_script_does_not_look_like_traceback_crash(self):
        """它是「没跑起来」，不是「跑起来后崩了」—— 两者需区分以便正确报错。"""
        _, out = run([sys.executable, "这个脚本不存在_zzz.py"])
        assert crashed(out) is False
