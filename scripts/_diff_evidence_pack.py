#!/usr/bin/env python
# lifecycle: maintenance
"""证据包等价性比对——用于 collect_index.py 拆分子模块前后的行为回归。

用法：
    python scripts/_diff_evidence_pack.py <before> <after>
      <before>/<after> 可以是单文件，也可以是目录（按相对路径配对）。

规则：忽略时间戳/日期/耗时类字段，其余逐行（JSON 逐键）严格比对。
退出码：0 = 等价；1 = 有差异；2 = 文件配对不上。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DUR = re.compile(r"(耗时|用时|elapsed|duration|took)[^\d]{0,6}[\d.]+")
TIMEKEY = re.compile(r"(time|date|at|ts|stamp|updated|generated|as_of|updated_at)$", re.I)


def norm_text(s: str) -> str:
    s = TS.sub("<TS>", s)
    s = DATE.sub("<DATE>", s)
    return DUR.sub(r"\1 <DUR>", s)


def norm_obj(o):
    if isinstance(o, dict):
        return {k: ("<MASKED>" if TIMEKEY.search(str(k)) else norm_obj(v)) for k, v in sorted(o.items())}
    if isinstance(o, list):
        return [norm_obj(v) for v in o]
    if isinstance(o, str):
        return norm_text(o)
    return o


def canon(p: Path) -> str:
    raw = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() == ".json":
        try:
            return json.dumps(norm_obj(json.loads(raw)), ensure_ascii=False, sort_keys=True, indent=1)
        except json.JSONDecodeError:
            pass
    return norm_text(raw).replace("\r\n", "\n")


def collect(p: Path) -> dict[str, Path]:
    if p.is_dir():
        return {str(f.relative_to(p)): f for f in sorted(p.rglob("*")) if f.is_file()}
    return {p.name: p}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    a, b = collect(Path(argv[1])), collect(Path(argv[2]))
    if set(a) != set(b):
        print("文件集合不一致：")
        for k in sorted(set(a) ^ set(b)):
            print("  ", k, "(仅", "before" if k in a else "after", ")")
        return 2
    bad = 0
    for key in sorted(a):
        ca, cb = canon(a[key]).splitlines(), canon(b[key]).splitlines()
        if ca == cb:
            print(f"等价  {key}")
            continue
        bad += 1
        print(f"差异  {key}")
        for i in range(max(len(ca), len(cb))):
            x = ca[i] if i < len(ca) else "<缺行>"
            y = cb[i] if i < len(cb) else "<缺行>"
            if x != y:
                print(f"   L{i+1}\n     - {x}\n     + {y}")
                break
    print(f"\n结论：{'全部等价' if not bad else f'{bad} 个文件有差异'}（已忽略时间戳/日期/耗时字段）")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
