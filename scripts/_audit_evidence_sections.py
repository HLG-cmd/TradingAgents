# lifecycle: maintenance
# 用途：审计证据包每个 section 是否"静默为空"（报成功但内容为空）
# 用法：python scripts/_audit_evidence_sections.py <evidence_md>
import re
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
lines = text.splitlines()

# 匹配 markdown 标题行
hdr = re.compile(r"^(#{1,4})\s+(.*)$")
marks = []
for i, ln in enumerate(lines):
    m = hdr.match(ln)
    if m:
        marks.append((i, m.group(1), m.group(2).strip()))

marks.append((len(lines), "", "<<EOF>>"))

print(f"file: {path}")
print(f"total_chars: {len(text)}")
print("-" * 70)
empty = []
for k in range(len(marks) - 1):
    start, lvl, title = marks[k]
    end = marks[k + 1][0]
    body = "\n".join(lines[start + 1 : end])
    stripped = body.strip()
    # 剔除纯 URL / "Link:" / 分隔线 / 围栏后再判空（铁律 35）
    probe = re.sub(r"^https?://\S+$", "", stripped, flags=re.M)
    probe = re.sub(r"^Link:.*$", "", probe, flags=re.M)
    probe = re.sub(r"^-{3,}$", "", probe, flags=re.M)
    probe = re.sub(r"^```.*$", "", probe, flags=re.M)
    probe = probe.strip()
    n = len(probe)
    flag = "EMPTY!" if n < 30 else ""
    if flag:
        empty.append(title)
    print(f"{lvl:4s} {title[:46]:46s} ... {n:6d} chars {flag}")

print("-" * 70)
print("suspicious_empty_sections:", empty if empty else "none")
