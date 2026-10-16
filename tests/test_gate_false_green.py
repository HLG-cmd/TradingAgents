# lifecycle: test
"""本轮新增修复的回归测试（第 8、9 例）。

## 锁定的两个 bug（2026-10-16 实测复现）
### 第 8 例：`_health.chk_quant` —— 凭证检查**假绿**
判据原为 `if "OK" in out`，而被执行代码末句是 `print('OK')`。
**断言失败时 traceback 会回显整行源码**，那行里就含 `print('OK')` ⇒ 子串命中 ⇒
`.env` 清空（凭证失效）时仍报 PASS。
⇒ 假绿后果严重：体检说「凭证读取正常」，而 EDGAR 实际会 403（铁律 3 静默失败）。

### 第 9 例：`_check_role_files` —— 空草稿被判「通过」
`if not files: print("（尚无角色文件）")` 只提示、**不计入 `bad`**
⇒ 末尾 `return 1 if bad else 0` 得 0 ⇒ **零个角色文件也能过检**。
实测与 `_verify_ratings.py` 结论相反（同一空目录：本脚本 rc=0 / 后者 rc=1）。

⚠️ 全部用例只碰临时副本或临时目录，结束即还原并逐字节核对。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_health():
    spec = importlib.util.spec_from_file_location("_health_rt2", ROOT / "scripts" / "_health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# --------------------------------------------------------------------------
# 第 8 例：chk_quant 凭证检查不得假绿
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestChkQuantCredentialNotFalseGreen:
    """凭证缺失时必须 FAIL，不得因「源码回显含 OK」而 PASS。"""

    def test_missing_credentials_fails(self, monkeypatch):
        """★ 第 8 例回归锁：凭证缺失 ⇒ 必须 FAIL。

        未修时实测（**干净解释器**）：断言失败（rc=1）但输出里因 traceback 回显源码而含 "OK"
        ⇒ 判据命中 ⇒ 返回 `PASS：自建包可导入，且 .env 凭证读取正常`（假绿）。

        ⚠️ **只清空 `.env` 不够**：`chk_quant` 起子进程时用 `env=dict(os.environ, ...)`
        ⇒ **继承父进程环境变量**；而 pytest 会话里某个项目模块在导入时调了 `load_dotenv()`
        ⇒ 凭证已进 `os.environ` ⇒ 清空 `.env` 对它无效（此时报 PASS 是**正确的**）。
        ⇒ 因此必须**同时删掉环境变量**，才能真模拟「凭证缺失」。
           （这是测试缺陷，不是产品 bug —— 已在 `_diag_chk_quant_in_pytest.py` 证实。）
        """
        health = _load_health()
        env = ROOT / ".env"
        if not env.exists():
            pytest.skip("项目无 .env，无法构造凭证缺失场景")
        orig = env.read_text(encoding="utf-8")
        monkeypatch.delenv("SEC_USER_AGENT", raising=False)
        try:
            env.write_text("# cleared by test\n", encoding="utf-8", newline="\n")
            status, msg = health.chk_quant()
            assert status != "PASS", f"凭证缺失却报 PASS（假绿复现）：{msg}"
        finally:
            env.write_text(orig, encoding="utf-8", newline="\n")
            assert env.read_text(encoding="utf-8") == orig, "还原失败"

    def test_normal_state_passes(self):
        """正常 `.env` 仍须 PASS（防「改严了就误报」）。"""
        health = _load_health()
        status, msg = health.chk_quant()
        assert status == "PASS", f"正常状态应 PASS，实得 {status}：{msg}"


# --------------------------------------------------------------------------
# 第 9 例：_check_role_files 空目录不得判「通过」
# --------------------------------------------------------------------------
@pytest.mark.unit
class TestRoleFilesEmptyDraftNotPass:
    """零个角色文件的草稿目录必须判失败（与 `_verify_ratings` 对齐）。"""

    def test_empty_draft_dir_fails(self, tmp_path: Path):
        """★ 第 9 例回归锁：空目录 ⇒ rc≠0。

        未修时实测：rc=0，输出「（尚无角色文件）／总计问题项: 0」= 通过。
        """
        name = tmp_path.name
        script = ROOT / "wb_analysis" / "_check_role_files.py"
        # 该脚本按 `DRAFTS/<argv>` 解析 ⇒ 传一个**不存在**的名字会走「目录不存在」分支，
        # 那已是 rc≠0，测不出本 bug。⇒ 必须在真实 DRAFTS 下造空目录。
        target = ROOT / "wb_analysis" / "drafts" / f"ZZTEST_{name}"
        try:
            target.mkdir(parents=True, exist_ok=True)
            rc, out = _run([PY, str(script), target.name])
            assert rc != 0, f"空草稿目录被判通过（rc=0）：{out.strip()[-200:]}"
        finally:
            for sub in sorted([x for x in target.rglob("*") if x.is_dir()],
                              key=lambda x: len(x.parts), reverse=True):
                try:
                    sub.rmdir()
                except OSError:
                    pass
            try:
                target.rmdir()
            except OSError:
                pass

    def test_nonexistent_dir_still_fails(self):
        """不存在的目录同样 rc≠0（原有行为不得回退）。"""
        script = ROOT / "wb_analysis" / "_check_role_files.py"
        rc, _ = _run([PY, str(script), "ZZ_NO_SUCH_DRAFT_DIR_2026"])
        assert rc != 0, "不存在的目录竟判通过"
