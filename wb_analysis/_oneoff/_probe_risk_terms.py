# lifecycle: oneoff
# created: 2026-09-26
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_probe_risk_terms.py
# 用途：一次性探针 —— 定位三个风险角色文件中的五档英文词位置（本轮复核用，事后留痕不删）
import re
import pathlib

base = pathlib.Path(r'wb_analysis/drafts/GOOG_2026-09-25')
targets = ['risk_aggressive.md', 'risk_conservative.md', 'risk_neutral.md']

report = []
for fn in targets:
    fp = base / fn
    raw = fp.read_text(encoding='utf-8')
    lines = raw.split('\n')
    hits = []
    for i, ln in enumerate(lines):
        for w in ['Buy', 'Overweight', 'Hold', 'Underweight', 'Sell']:
            if re.search(r'\b' + w + r'\b', ln):
                hits.append((i, w, ln[:200]))
    report.append(f'===== {fn} ({len(hits)} hits) =====')
    for i, w, ln in hits:
        report.append(f'  line {i} [{w}]: {ln}')
    report.append('')

(base.parent / '_oneoff').mkdir(exist_ok=True)
pathlib.Path(r'wb_analysis/_oneoff/_probe_risk_terms.txt').write_text('\n'.join(report), encoding='utf-8')
print('written')
