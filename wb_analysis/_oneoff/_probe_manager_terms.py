# lifecycle: oneoff
# created: 2026-09-26
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_probe_manager_terms.py
# 用途：一次性探针 —— 定位 manager.md 中的五档英文词位置（本轮复核用，事后留痕不删）
import re
raw = open(r'wb_analysis/drafts/GOOG_2026-09-25/manager.md', encoding='utf-8').read()
out = []
for w in ['Buy', 'Overweight', 'Underweight', 'Sell', 'Hold']:
    for m in re.finditer(r'\b' + w + r'\b', raw):
        line_no = raw[:m.start()].count('\n')
        ctx = raw[max(0, m.start() - 100):m.end() + 60].replace('\n', ' | ')
        out.append(f'[{w}] line {line_no}: ...{ctx}...')
open('wb_analysis/_oneoff/_probe_manager_terms.txt', 'w', encoding='utf-8').write('\n\n'.join(out))
print('total hits:', len(out))
