# lifecycle: reusable
# created: 2026-10-24
# usage: from wb_analysis._integrity import write_manifest, verify   （库；不单独运行）
"""证据包**只读性**校验：采集时落一份 sha256 清单，交付门禁时比对。

## 为什么需要（2026-10-24）

AGENT_PROTOCOL §6 明令「子智能体**不得**修改证据包、简报或 `meta.json`」，但此前**没有任何检查**：
角色把某个数字改成自己想引用的值，`_lint_drafts` 的「数字溯源」反而会以被改后的证据包为基准
⇒ **自我印证**，编造数字变成"可溯源"。这是门禁链上唯一的**无防护面**。

## 判据

- 采集器写完 `<T>_<date>.md` 后立刻写 `<T>_<date>.md.integrity.json`（sha256 + 字节数 + 采集时刻）；
- `_precheck.py` 在交付前重算 sha256 并与清单比对：不一致 ⇒ **FAIL**（证据包被改过）；
- 清单缺失 ⇒ **WARN**（无法校验，通常是旧证据包或手写测试夹具，不阻断但须说明）。

★ 清单只覆盖**基线证据包**（`<T>_<date>.md`）。`.supplement.md` / `.derived.md` 是后续
合法追加物，不在只读范围内 —— 把它们也锁住会让正常的补采流程失败。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = ["MANIFEST_SUFFIX", "manifest_path", "verify", "write_manifest"]

MANIFEST_SUFFIX = ".integrity.json"


def manifest_path(md: Path) -> Path:
    """清单与证据包同目录、同名加后缀（不用 `with_suffix`，避免多后缀被吞）。"""
    return md.parent / (md.name + MANIFEST_SUFFIX)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(md: Path) -> Path:
    """写/覆盖清单。采集器在**写完证据包之后**调用一次即可。"""
    rec = {
        "file": md.name,
        "sha256": _sha256(md),
        "bytes": md.stat().st_size,
    }
    mp = manifest_path(md)
    mp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return mp


def verify(md: Path) -> tuple[bool, str]:
    """返回 `(是否一致, 说明)`。清单缺失时返回 `(True, ...)` —— 由调用方决定升级为 WARN。"""
    mp = manifest_path(md)
    if not mp.exists():
        return True, "无完整性清单（无法校验；旧证据包或测试夹具）"
    try:
        rec = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"清单不可解析：{type(exc).__name__}"
    cur = _sha256(md)
    want = str(rec.get("sha256") or "")
    if cur != want:
        return False, f"证据包在采集后被修改（采集时 {want[:12]}… ≠ 当前 {cur[:12]}…）"
    return True, f"sha256 与采集时一致（{cur[:12]}…）"
