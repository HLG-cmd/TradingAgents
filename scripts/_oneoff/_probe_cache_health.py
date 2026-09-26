# lifecycle: oneoff
# created: 2026-09-26
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_cache_health.py
# 用途：一次性探针 —— 诊断 ~/.tradingagents 缓存里是否有「真正无用」的部分
#       （0 字节 / 极陈旧 / 重复），供是否清理的决策提供依据。
import pathlib
import time
from collections import Counter

ROOT = pathlib.Path.home() / ".tradingagents"
NOW = time.time()
DAY = 86400

rows = []
zero = []
for p in ROOT.rglob("*"):
    if not p.is_file():
        continue
    st = p.stat()
    age = (NOW - st.st_mtime) / DAY
    rows.append((st.st_size, age, p))
    if st.st_size == 0:
        zero.append(p)

total = sum(r[0] for r in rows)
print(f"根目录: {ROOT}")
print(f"文件总数: {len(rows)}   合计: {total/1024/1024:.1f} MB\n")

print("按目录：")
by_dir = Counter()
for size, age, p in rows:
    rel = p.relative_to(ROOT)
    key = rel.parts[0] if len(rel.parts) > 1 else "(根)"
    by_dir[key] += size
for k, v in by_dir.most_common():
    print(f"  {k:<22} {v/1024/1024:>8.1f} MB")

print("\n按最后修改时间分桶（判断是否有陈旧堆积）：")
buckets = [(7, "7 天内"), (30, "7-30 天"), (90, "30-90 天"), (10**9, "90 天以上")]
counts = Counter()
sizes = Counter()
for size, age, p in rows:
    for lim, label in buckets:
        if age <= lim:
            counts[label] += 1
            sizes[label] += size
            break
for _, label in buckets:
    print(f"  {label:<12} {counts[label]:>5} 文件  {sizes[label]/1024/1024:>8.1f} MB")

print(f"\n0 字节文件: {len(zero)} 个")
for p in zero[:10]:
    print(f"  {p.relative_to(ROOT)}")

# 大文件 top 10
print("\n最大的 10 个文件：")
for size, age, p in sorted(rows, key=lambda x: -x[0])[:10]:
    print(f"  {size/1024/1024:>7.2f} MB  {age:>6.1f} 天前  {p.relative_to(ROOT)}")
