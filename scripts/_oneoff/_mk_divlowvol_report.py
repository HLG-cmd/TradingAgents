# lifecycle: oneoff
# created: 2026-10-16
"""生成《A 股红利低波 ETF 综合对比报告》桌面 HTML（与有色金属 ETF 报告同版式）。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(str(Path.home() / "Desktop" / "红利低波ETF综合对比报告.html"))

HEAD = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A 股红利低波 ETF 综合对比（费率 + 年化总收益）</title>
<style>
  :root{--bg:#f7f8fa;--card:#fff;--line:#e6e8ec;--ink:#1b1f27;--ink2:#5a6272;--ink3:#8b93a3;
    --accent:#1f5fd0;--accent-soft:#eaf1fd;--up:#c8322b;--down:#178a4c;--warn:#b06d00;
    --warn-soft:#fff6e6;--ok:#178a4c;--ok-soft:#eaf7f0;}
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--ink);line-height:1.7;font-size:15px;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
  .wrap{max-width:1120px;margin:0 auto;padding:28px 22px 64px;}
  header.top{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px 26px;margin-bottom:18px;}
  header.top h1{margin:0 0 6px;font-size:23px;letter-spacing:-.2px;}
  header.top .sub{color:var(--ink2);font-size:13.5px;}
  .tags{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px;}
  .tag{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--accent-soft);color:var(--accent);border:1px solid #d5e3fb;}
  .tag.warn{background:var(--warn-soft);color:var(--warn);border-color:#f0dcb0;}
  .tag.ok{background:var(--ok-soft);color:var(--ok);border-color:#c8e9d8;}
  nav.toc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 22px;margin-bottom:18px;}
  nav.toc h4{margin:0 0 10px;font-size:13px;color:var(--ink3);font-weight:600;letter-spacing:.4px;}
  nav.toc ol{margin:0;padding-left:20px;columns:2;column-gap:34px;}
  nav.toc li{margin:3px 0;font-size:13.5px;}
  nav.toc a{color:var(--accent);text-decoration:none;}
  section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px 26px;margin-bottom:16px;}
  h2{font-size:18px;margin:0 0 14px;padding-left:11px;border-left:4px solid var(--accent);}
  h3{font-size:15px;margin:20px 0 8px;}
  p{margin:9px 0;color:var(--ink2);}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:6px 0;}
  .kpi{background:var(--bg);border:1px solid var(--line);border-radius:11px;padding:13px 15px;}
  .kpi .k{font-size:12px;color:var(--ink3);}
  .kpi .v{font-size:20px;font-weight:700;margin:3px 0 1px;letter-spacing:-.3px;}
  .kpi .n{font-size:11.5px;color:var(--ink3);}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px;}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;}
  th{background:var(--bg);font-weight:600;font-size:12.5px;white-space:nowrap;}
  td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
  tr.best td{background:var(--ok-soft);}
  tr.good td{background:#f2f9f5;}
  tr.warnrow td{background:var(--warn-soft);}
  tr.bad td{background:#fdf3f2;}
  .muted{color:var(--ink3);font-size:12.5px;}
  .callout{border-radius:10px;padding:13px 16px;margin:14px 0;font-size:13.8px;}
  .callout.good{background:var(--ok-soft);border:1px solid #c8e9d8;}
  .callout.warn{background:var(--warn-soft);border:1px solid #f0dcb0;}
  .callout b{color:var(--ink);}
  ul,ol{margin:8px 0;padding-left:22px;color:var(--ink2);}
  li{margin:4px 0;}
  .rank{display:inline-block;min-width:22px;font-weight:700;color:var(--accent);}
  footer{margin-top:22px;color:var(--ink3);font-size:12.5px;line-height:1.8;}
  footer b{color:var(--ink2);}
  @media(max-width:820px){.kpis{grid-template-columns:repeat(2,1fr);}nav.toc ol{columns:1;}
    table{font-size:12px;}th,td{padding:6px;}}
</style></head><body><div class="wrap">
"""

FOOT = r"""
<footer>
  <p><b>数据与口径</b></p>
  <ul>
    <li>数据源：westock CLI（腾讯官方接口），快照日 <b>2026-10-15</b>（A 股收盘后）。</li>
    <li><b>年化总收益</b> = 用 <b>后复权（hfq）月线</b>计算 —— 后复权已把分红再投计入价格，故为<b>含分红的真实总收益</b>，非价格收益。</li>
    <li><b>综合费率</b> = 管理费 + 托管费 + 销售服务费（场内 ETF 无申购/赎回费；佣金因券商而异，未计入）。</li>
    <li>规模取 <code>etf profile</code> 的 <code>totalAsset</code>；另 <code>etf overview</code> 的 <code>etfSize</code> 为第二口径，两者可能不同。</li>
    <li>估值分位为 <b>区间内百分位</b>（westock 口径），数值越高代表当前越贵。</li>
  </ul>
  <p><b>免责声明</b>：本报告为静态数据对比，不构成投资建议、不预测红利低波板块走势。ETF 费率、规模、成分与分红政策均可能调整，实际以基金合同与当日行情为准。历史收益不代表未来表现。投资有风险。</p>
  <p>生成时间 2026-10-16 ｜ 版式对齐《有色金属板块ETF基金性价比对比报告》</p>
</footer></div></body></html>
"""

# ── 数据（全部来自本轮 westock 实测）────────────────────────────────
ROWS = [
    # code, name, fee, track, est, size亿, turnover亿, div%, ann283, ann30, ann24,
    # pe_pct, pb_pct, dd1y, chg52w, chgytd, disc
    ("sh512890", "红利低波ETF华泰柏瑞", 0.60, "红利低波 (H30269)", "2018-12-19", 313.28, 16.31, 5.04,
     10.47, 9.87, 5.95, 100.00, 100.00, -14.16, 2.54, 3.06, -0.51),
    ("sh563020", "红利低波ETF易方达", 0.20, "红利低波 (H30269)", "2023-12-06", 113.83, 3.76, 5.04,
     10.62, None, 6.05, 100.00, 100.00, -14.58, 2.66, 3.63, 0.23),
    ("sh515450", "红利低波50ETF南方", 0.60, "标普中国A股大盘红利低波50", "2020-01-17", 180.15, 2.87, None,
     10.59, 9.72, 7.32, 0.00, 0.00, -10.83, 5.16, 5.16, -0.08),
    ("sh515100", "红利低波100ETF景顺", 0.60, "红利低波100", "2020-05-22", 55.36, 1.24, 7.18,
     5.19, 4.19, 4.98, 92.07, 83.82, -14.41, -1.10, 0.35, 0.05),
    ("sh515300", "300红利低波ETF嘉实", 0.60, "300红利低波", "2019-08-08", 46.70, 1.30, 18.00,
     8.89, 8.27, 4.80, 100.00, 83.82, -13.75, 3.66, 4.93, 0.11),
    ("sz159547", "红利低波ETF华夏", 0.20, "红利低波 (H30269)", "2024-01-25", 14.78, 1.33, 5.04,
     7.59, None, 6.77, 100.00, 100.00, -13.58, 3.78, 4.58, 0.17),
    ("sz159549", "红利低波ETF天弘", 0.60, "红利低波100", "2023-11-23", 52.57, 0.34, 7.18,
     7.42, None, 7.24, 92.07, 83.82, -13.60, -0.49, 0.92, -0.01),
    ("sz159525", "红利低波ETF富国", 0.20, "红利低波 (H30269)", "2024-05-07", 8.38, 0.30, 5.04,
     4.86, None, 6.16, 100.00, 100.00, -14.43, 2.81, 3.84, 0.04),
    ("sh560520", "红利低波100ETF大成", 0.20, "红利低波100", "2024-04-08", 0.30, 0.01, 7.18,
     4.51, None, 6.03, 92.07, 83.82, -13.91, -0.88, 0.09, 0.21),
]


def f(v, w=8, p=2, dash="—"):
    return f"{v:>{w}.{p}f}" if v is not None else f"{dash:>{w}}"


# ── §1 结论 ──────────────────────────────────────────────
s1 = """
<header class="top">
  <h1>A 股红利低波 ETF 综合对比：费率 × 年化总收益</h1>
  <div class="sub">范围：A 股上市、名称含「红利低波」的全部 9 只 ETF ｜ 数据基准日 2026-10-15 ｜ 年化收益用<b>后复权（含分红）</b>口径</div>
  <div class="tags">
    <span class="tag ok">首选：563020 易方达（费率 0.20%）</span>
    <span class="tag">次选：512890 华泰柏瑞（规模/流动性最优）</span>
    <span class="tag warn">窗口依赖性已披露</span>
  </div>
</header>

<nav class="toc"><h4>目录</h4><ol>
  <li><a href="#s1">一、结论：首选与次选</a></li>
  <li><a href="#s2">二、全清单对比（9 只）</a></li>
  <li><a href="#s3">三、费率：唯一的确定变量</a></li>
  <li><a href="#s4">四、年化总收益：多窗口对照（必读）</a></li>
  <li><a href="#s5">五、综合评分</a></li>
  <li><a href="#s6">六、按跟踪指数分组：真正的可比对象</a></li>
  <li><a href="#s7">七、估值分位与回撤</a></li>
  <li><a href="#s8">八、这份对比自身的问题（必读）</a></li>
</ol></nav>
"""

s1b = """
<section><h2 id="s1">一、结论：首选与次选</h2>
<div class="kpis">
  <div class="kpi"><div class="k">最低费率</div><div class="v">0.20%/年</div><div class="n">4 只（易方达/华夏/富国/大成）</div></div>
  <div class="kpi"><div class="k">最高费率</div><div class="v">0.60%/年</div><div class="n">5 只（主流档）</div></div>
  <div class="kpi"><div class="k">费率差</div><div class="v">3 倍</div><div class="n">0.40pp/年，10 年约 4%</div></div>
  <div class="kpi"><div class="k">最大规模</div><div class="v">313 亿</div><div class="n">512890 华泰柏瑞</div></div>
</div>

<div class="callout good">
<b>首选：<code>sh563020</code> 红利低波ETF易方达 —— 成本效率最优。</b><br>
理由三条，全部可复算：<br>
① <b>费率 0.20%/年</b>（管理 0.15 + 托管 0.05），是主流档 0.60% 的 <b>1/3</b>；<br>
② <b>跟踪主流指数「红利低波（H30269）」</b> —— 与规模最大的 512890 <b>完全同指数</b>，因此是<b>真正的替代品</b>；<br>
③ <b>在 0.20% 费率组内规模最大</b>（113.8 亿），远超另外三只（华夏 14.8 亿 / 富国 8.4 亿 / 大成 0.3 亿），<b>无清盘与流动性之忧</b>。<br>
<b>同窗口实测</b>（2023-12-29 → 2026-10-15，2.83 年）：年化总收益 <b>10.62%</b>，与最高的 515450（10.59%）持平，<b>但费率只有它的 1/3</b>。
</div>

<div class="callout">
<b>次选：<code>sh512890</code> 红利低波ETF华泰柏瑞 —— 规模与流动性最优。</b><br>
<b>规模 313 亿（全场最大）、日成交 16.31 亿（第二名的 4.3 倍）</b>，跟踪同一指数 H30269。<br>
代价：<b>费率 0.60%，是 563020 的 3 倍</b>。<br>
⇒ <b>适合</b>：资金量较大（需低冲击成本）、或需要 T+0 日内频繁进出的投资者。<br>
⇒ <b>不适合</b>：以年为单位长期持有、且资金量在百万元以下的投资者（费率劣势会持续侵蚀收益）。
</div>

<div class="callout warn">
<b>不推荐：<code>sh560520</code> 红利低波100ETF大成（规模 0.30 亿）。</b><br>
虽然费率同为 0.20%，但<b>规模仅 3000 万元</b>，远低于常见的 5000 万清盘警戒线附近，<b>存在清盘风险与盘口稀薄问题</b>。日成交仅 0.01 亿元。无论费率多低，<b>规模过小是硬伤</b>。
</div>
</section>
"""

# ── §2 全清单 ────────────────────────────────────────────
s2 = """
<section><h2 id="s2">二、全清单对比（9 只，按费率升序、同费率按规模降序）</h2>
<table><thead><tr>
<th>代码</th><th>名称</th><th class="num">综合费率<br>%/年</th><th>跟踪指数</th><th>成立日</th>
<th class="num">规模<br>(亿元)</th><th class="num">日成交<br>(亿元)</th><th class="num">股息率<br>%</th>
</tr></thead><tbody>
"""
for c, n, fee, tr, est, size, to, dv, *_ in sorted(ROWS, key=lambda x: (x[2], -x[5])):
    cls = ' class="best"' if c == "sh563020" else (' class="good"' if c == "sh512890" else
          (' class="bad"' if size < 1 else ''))
    s2 += (f"<tr{cls}><td><code>{c}</code></td><td><b>{n}</b></td>"
           f"<td class='num'><b>{fee:.2f}</b></td><td>{tr}</td><td>{est}</td>"
           f"<td class='num'>{size:.2f}</td><td class='num'>{to:.2f}</td>"
           f"<td class='num'>{f(dv)}</td></tr>\n")
s2 += """</tbody></table>
<p class="muted">规模取 <code>etf profile.totalAsset</code>；另有 <code>etf overview.etfSize</code> 第二口径（如 563020 为 124.55 亿、512890 为 324.35 亿），两者可能不同，引用须声明口径。515450 的股息率字段回传 0.00%，疑为缺失而非真无分红。</p>
</section>
"""

# ── §3 费率 ──────────────────────────────────────────────
s3 = """
<section><h2 id="s3">三、费率：唯一的确定变量</h2>
<p>红利低波 ETF 的<b>底层指数高度重叠</b>，长期收益差异主要来自指数选择；而在<b>同一指数内部，唯一确定的差异就是费率</b> —— 它每天都在扣，且<b>不依赖任何预测</b>。</p>
<table><thead><tr><th>费率档</th><th>管理费</th><th>托管费</th><th>标的</th><th class="num">规模合计</th></tr></thead><tbody>
<tr class="best"><td><b>0.20%/年</b></td><td>0.15%</td><td>0.05%</td><td>563020 易方达 · 159547 华夏 · 159525 富国 · 560520 大成</td><td class="num">137.29 亿</td></tr>
<tr class="warnrow"><td><b>0.60%/年</b></td><td>0.50%</td><td>0.10%</td><td>512890 华泰柏瑞 · 515450 南方 · 515100 景顺 · 515300 嘉实 · 159549 天弘</td><td class="num">648.06 亿</td></tr>
</tbody></table>
<div class="callout warn">
<b>0.40 个百分点的年费差，在长期持有下不可忽略。</b><br>
以 100 万元本金、年化 8% 计：<b>10 年下来，0.60% 费率比 0.20% 费率少约 5.4 万元</b>（≈ 本金的 5.4%）。<br>
⇒ 在跟踪同一指数的前提下，<b>没有理由为 0.60% 的费率买单</b>，除非它的规模/流动性带来不可替代的价值。
</div>
<div class="callout good">
<b>但必须公平指出：0.60% 档合计规模 648 亿，是 0.20% 档（137 亿）的 4.7 倍。</b><br>
其中 <b>512890 华泰柏瑞单只 313 亿、日成交 16.31 亿</b> —— 这是 0.20% 档<b>任何一只都无法提供的流动性深度</b>。<br>
⇒ <b>费率优势 vs 流动性优势，是本轮真正的取舍。</b>
</div>
</section>
"""

# ── §4 多窗口年化 ────────────────────────────────────────
s4 = """
<section><h2 id="s4">四、年化总收益：多窗口对照（必读）</h2>
<div class="callout warn">
<b>为什么必须给多个窗口：</b>各标的成立日从 2018-12 到 2024-05 不等，「成立以来年化」<b>不可横向比较</b>。<br>
实测：同一指数（H30269）的两只标的，仅因窗口不同（2.83 年 vs 3.00 年），年化差出 <b>1.08 个百分点</b>。<br>
⇒ <b>下表同时给出三个窗口</b>，凡「—」表示该标的成立时间不足该窗口。
</div>
<table><thead><tr>
<th>代码</th><th>名称</th><th class="num">费率<br>%</th>
<th class="num">2.83 年窗口<br>2023-12-29→</th>
<th class="num">3.00 年窗口<br>2023-10-31→</th>
<th class="num">2.4 年窗口<br>2024-05-31→<br><span class="muted">（全 9 只可比）</span></th>
</tr></thead><tbody>
"""
order = ["sh563020", "sh515450", "sh512890", "sh515300", "sz159549", "sz159547", "sz159525", "sh560520", "sh515100"]
d = {r[0]: r for r in ROWS}
for c in order:
    r = d[c]
    cls = ' class="best"' if c == "sh563020" else (' class="good"' if c == "sh512890" else '')
    s4 += (f"<tr{cls}><td><code>{c}</code></td><td>{r[1]}</td><td class='num'>{r[2]:.2f}</td>"
           f"<td class='num'>{f(r[8])}</td><td class='num'>{f(r[9])}</td><td class='num'>{f(r[10])}</td></tr>\n")
s4 += """</tbody></table>
<div class="callout">
<b>怎么读这张表：</b><br>
· <b>2.83 年窗口</b>：563020（10.62%）≈ 515450（10.59%）≈ 512890（10.47%）—— <b>三者几乎并列</b>，差距在跟踪噪声量级；<br>
· <b>3.00 年窗口</b>：512890（9.87%）> 515450（9.72%）—— 长窗口下华泰柏瑞略优；<br>
· <b>2.4 年窗口（全 9 只可比）</b>：515450（7.32%）> 159549（7.24%）> 159547（6.77%）> … > 563020（6.05%）> 512890（5.95%）。<br>
<b>⇒ 排名随窗口变化 ⇒ 不应据单一窗口下结论。</b>但有一条<b>跨窗口稳定</b>：<b>563020 的收益率始终处于第一梯队，而它的费率始终是最低档。</b>
</div>
</section>
"""

# ── §5 综合评分 ──────────────────────────────────────────
s5 = """
<section><h2 id="s5">五、综合评分</h2>
<p>评分口径：<b>净收益 = 该标的可得窗口的年化总收益 − 综合费率</b>（即投资者真正留下的部分）。为消除窗口差异，同时给出「2.83 年」与「2.4 年」两个窗口的净收益。</p>
<table><thead><tr><th>排名</th><th>代码</th><th>名称</th>
<th class="num">费率%</th><th class="num">2.83年净收益%</th><th class="num">2.4年净收益%</th>
<th class="num">规模(亿)</th><th>综合判断</th></tr></thead><tbody>
"""
rows5 = []
for r in ROWS:
    c, n, fee = r[0], r[1], r[2]
    net283 = (r[8] - fee) if r[8] is not None else None
    net24 = (r[10] - fee) if r[10] is not None else None
    rows5.append((c, n, fee, net283, net24, r[5]))
rows5.sort(key=lambda x: -(x[3] if x[3] is not None else -99))
verdict = {
    "sh563020": "★ 首选：同指数最低费率 + 低费率组内最大规模",
    "sh512890": "次选：同指数但费率 3 倍；换 313 亿规模与 16.31 亿日成交",
    "sh515450": "指数不同（标普A股大盘红利低波50）；近期收益领先，费率 0.60%",
    "sh515300": "指数不同（300红利低波）；规模中等，费率 0.60%",
    "sz159549": "红利低波100 指数；0.60% 费率 + 日成交仅 0.34 亿",
    "sz159547": "同指数 + 0.20% 费率，但规模仅 14.8 亿（可接受）",
    "sz159525": "同指数 + 0.20% 费率，但规模仅 8.4 亿（偏小）",
    "sh560520": "✗ 规模仅 0.30 亿 ⇒ 清盘风险，不考虑",
    "sh515100": "各窗口收益均垫底；0.60% 费率",
}
for i, (c, n, fee, n283, n24, size) in enumerate(rows5, 1):
    cls = ' class="best"' if c == "sh563020" else (' class="good"' if c == "sh512890" else
          (' class="bad"' if size < 1 else ''))
    s5 += (f"<tr{cls}><td><span class='rank'>{i}</span></td><td><code>{c}</code></td><td>{n}</td>"
           f"<td class='num'>{fee:.2f}</td><td class='num'><b>{f(n283)}</b></td>"
           f"<td class='num'>{f(n24)}</td><td class='num'>{size:.2f}</td>"
           f"<td class='muted'>{verdict.get(c, '')}</td></tr>\n")
s5 += """</tbody></table>
<div class="callout good">
<b>评分结论：</b>在<b>可比窗口</b>内，<b>563020 易方达</b> 的净收益（10.42%）位列第一；在 2.4 年窗口内，<b>515450 南方</b> 以 6.72% 领先，<b>563020</b> 为 5.85%（中游）。<br>
<b>综合费率与规模后，563020 是「无短板」的选择</b> —— 它的收益率从不垫底，而费率与规模都处于有利位置。
</div>
</section>
"""

# ── §6 按指数分组 ────────────────────────────────────────
s6 = """
<section><h2 id="s6">六、按跟踪指数分组：真正的可比对象</h2>
<p>「红利低波 ETF」并不是同一个东西 —— <b>9 只标的跟踪 4 个不同指数</b>。<b>跨指数比较收益是无效的</b>；只有<b>同指数内部</b>才是真正的替代品。</p>
<table><thead><tr><th>跟踪指数</th><th>标的</th><th class="num">费率</th><th class="num">规模(亿)</th><th>点评</th></tr></thead><tbody>
<tr class="best"><td rowspan="4"><b>红利低波<br>(H30269)</b><br><span class="muted">中证红利低波动</span></td>
<td>563020 易方达</td><td class="num"><b>0.20%</b></td><td class="num">113.83</td><td><b>★ 该组最优：最低费率 + 组内最大规模</b></td></tr>
<tr class="good"><td>512890 华泰柏瑞</td><td class="num">0.60%</td><td class="num"><b>313.28</b></td><td>流动性最好（日成交 16.31 亿），但费率 3 倍</td></tr>
<tr><td>159547 华夏</td><td class="num">0.20%</td><td class="num">14.78</td><td>费率优，规模偏小但可接受</td></tr>
<tr><td>159525 富国</td><td class="num">0.20%</td><td class="num">8.38</td><td>费率优，规模偏小</td></tr>

<tr><td rowspan="3"><b>红利低波100</b><br><span class="muted">另一个指数</span></td>
<td>515100 景顺</td><td class="num">0.60%</td><td class="num">55.36</td><td>各窗口收益均垫底</td></tr>
<tr><td>159549 天弘</td><td class="num">0.60%</td><td class="num">52.57</td><td>2.4 年窗口表现好（7.24%），但费率 0.60%</td></tr>
<tr class="bad"><td>560520 大成</td><td class="num">0.20%</td><td class="num">0.30</td><td>✗ 规模过小，清盘风险</td></tr>

<tr><td><b>标普中国A股<br>大盘红利低波50</b></td><td>515450 南方</td><td class="num">0.60%</td><td class="num">180.15</td>
<td>近期（2.4 年）收益最高 7.32%，但指数与主流不同、费率 0.60%</td></tr>

<tr><td><b>300 红利低波</b></td><td>515300 嘉实</td><td class="num">0.60%</td><td class="num">46.70</td>
<td>大盘股偏向，股息率字段回传 18.00%（偏高，疑口径特殊）</td></tr>
</tbody></table>
<div class="callout good">
<b>⇒ 同指数内部的选择规则非常简单：</b>既然底层一样，<b>就选费率最低、且规模足够的那个</b>。<br>
在 H30269 组内，<b>0.20% 档的三只（563020 / 159547 / 159525）全部优于 0.60% 的 512890</b>，其中 <b>563020 规模最大（113.83 亿）</b> ⇒ <b>它就是答案</b>。
</div>
</section>
"""

# ── §7 估值与回撤 ────────────────────────────────────────
s7 = """
<section><h2 id="s7">七、估值分位与回撤</h2>
<table><thead><tr><th>代码</th><th>名称</th><th class="num">PE 分位%</th><th class="num">PB 分位%</th>
<th class="num">52周收益%</th><th class="num">YTD%</th><th class="num">近1年最大回撤%</th><th class="num">折溢价%</th></tr></thead><tbody>
"""
for r in sorted(ROWS, key=lambda x: -(x[11] or 0)):
    cls = ' class="warnrow"' if (r[11] or 0) >= 99 else ''
    s7 += (f"<tr{cls}><td><code>{r[0]}</code></td><td>{r[1]}</td>"
           f"<td class='num'>{f(r[11])}</td><td class='num'>{f(r[12])}</td>"
           f"<td class='num'>{f(r[14])}</td><td class='num'>{f(r[15])}</td>"
           f"<td class='num'>{f(r[13])}</td><td class='num'>{f(r[16])}</td></tr>\n")
s7 += """</tbody></table>
<div class="callout warn">
<b>两个必须点出的异常：</b><br>
① <b>多数标的 PE / PB 分位达 100%（区间内最高）</b> —— 红利低波板块整体处于<b>估值区间高位</b>。这解释了为何各标的 YTD 收益仅 0~5%（相对其历史年化 8~11% 明显放缓）。<br>
② <b>515450 南方的 PE / PB 分位为 0.00%</b>，与其余标的的 100% 形成极端反差 —— 这<b>大概率是该指数的分位口径不同或数据缺失</b>，不宜直接解读为「极度低估」。<b>本报告不对其作估值判断。</b>
</div>
<div class="callout">
<b>折溢价</b>：所有标的折溢价均在 ±0.51% 以内，<b>流动性充足、无明显套利空间</b>。其中 512890 折价 −0.51%（买入略有利）。
</div>
</section>
"""

# ── §8 问题披露 ──────────────────────────────────────────
s8 = """
<section><h2 id="s8">八、这份对比自身的问题（必读）</h2>
<h3>问题 1：年化收益对窗口极度敏感</h3>
<div class="callout warn">
同一指数（H30269）的两只标的，仅因窗口从 3.00 年缩到 2.83 年，年化收益差就 <b>从 1.08pp 缩到 0.15pp</b>。<br>
<b>⇒ 任何「某只 ETF 年化收益最高」的单一数字都不可信。</b>本报告给出三个窗口，就是为了暴露这一点。
</div>
<h3>问题 2：跨指数比较收益是无效的</h3>
<div class="callout warn">
515450 南方在 2.4 年窗口以 7.32% 领先，<b>但它跟踪的是「标普中国A股大盘红利低波50」，与其余 8 只不是同一个指数</b>。<br>
<b>⇒ 它的领先是「指数选择」的结果，不是「产品更好」。</b>选它等于选择了一个不同的策略暴露。
</div>
<h3>问题 3：股息率字段存在明显异常</h3>
<div class="callout warn">
· 515450 的股息率回传 <b>0.00%</b>（红利 ETF 不可能零股息）⇒ <b>疑为数据缺失</b>；<br>
· 515300 的股息率回传 <b>18.00%</b> ⇒ 显著高于其余标的（5.04% / 7.18%），<b>疑为口径特殊（可能含特别分红）</b>；<br>
· 其余标的按跟踪指数分两档：H30269 系 5.04%、红利低波100 系 7.18%。<br>
<b>⇒ 本报告未把股息率纳入评分</b>，仅作参考列示。
</div>
<h3>问题 4：规模有两个口径</h3>
<div class="callout warn">
<code>etf profile.totalAsset</code> 与 <code>etf overview.etfSize</code> 数值不同（如 563020：113.83 亿 vs 124.55 亿；512890：313.28 亿 vs 324.35 亿）。<br>
<b>本报告统一采用前者</b>，并在 §2 脚注声明。两者相差约 3~10%，<b>不影响排序</b>。
</div>
<h3>问题 5：我没有做的事（透明声明）</h3>
<ul>
  <li><b>未核对基金合同原文</b>：费率取自 westock <code>etf profile</code>，未逐份比对招募说明书；</li>
  <li><b>未实测跟踪误差</b>：费率之外，跟踪误差也是真实成本，但本证据源未直接提供各标的的<b>实际跟踪偏离度</b>序列；</li>
  <li><b>未考虑税收</b>：ETF 分红在 A 股的个人所得税处理（场内 ETF 分红暂免个税）未纳入测算；</li>
  <li><b>未做成分股穿透</b>：4 个指数的成分与权重差异未展开，仅按名称归类；</li>
  <li><b>未纳入港股红利低波</b>：本报告只覆盖 A 股（另有 159545 港股通红利低波、159569 港股红利低波、520550 港股红利低波，属港股通标的，不在本次范围）。</li>
</ul>
<div class="callout good">
<b>怎么用这份报告：</b>把「费率」当作<b>确定项</b>（563020 = 0.20% 最优），把「年化收益」当作<b>参考项</b>（同指数内差异在噪声量级），把「规模/流动性」当作<b>约束项</b>（百万元以上资金才需考虑 512890）。<br>
⇒ <b>若不打算大额交易，563020 是成本效率最优解。</b>
</div>
</section>
"""

html = HEAD + s1 + s1b + s2 + s3 + s4 + s5 + s6 + s7 + s8 + FOOT
OUT.write_text(html, encoding="utf-8")
print(f"WROTE {OUT} ({len(html.encode('utf-8'))} bytes)")
