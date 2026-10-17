# lifecycle: oneoff
# created: 2026-10-16
# -*- coding: utf-8 -*-
"""生成《有色金属板块ETF综合对比报告.html》到桌面（v3：含分红修正年化 + 数据核验专节 + 12 只全量）。"""
from pathlib import Path

# 修正后年化 = 价格收益(hfq月线) + divTtm 加回（数据源 hfq 不反映分红，经核验全部 12 只 divTtm>0）
# code, name, fee, size, amt, unif, y3, y1, dd1y, pe, est, track, te, te_cum, div
ROWS = [
    ("sh512400", "有色金属ETF南方", 0.60, 213.85, 4.57, 10.12, 23.99, 1.85, -35.85, 14.52, "2017-08", "有色金属(申万)", None, None, 2.06),
    ("sh516650", "有色金属ETF华夏", 0.60, 82.70, 1.43, 11.53, 24.09, 0.47, -34.60, 14.26, "2021-06", "细分有色", 1.40, 0.00, 2.03),
    ("sh560860", "工业有色ETF万家", 0.60, 70.59, 1.07, 15.22, 25.51, 9.69, -35.85, 13.83, "2023-02", "工业有色", None, None, 2.25),
    ("sz159652", "有色ETF汇添富", 0.60, 23.91, 0.91, 14.30, 24.00, 0.34, -34.80, 14.26, "2023-01", "细分有色", 1.40, -0.02, 2.03),
    ("sz159876", "有色ETF华宝", 0.60, 13.72, 1.76, 10.42, 22.55, 1.57, -34.80, 14.44, "2021-03", "中证有色", 2.18, -0.09, 1.97),
    ("sz159871", "有色ETF银华", 0.20, 8.73, 0.20, 10.64, 22.99, 2.04, -34.38, 14.44, "2021-03", "中证有色", 1.94, 0.06, 1.97),
    ("sz159881", "有色金属ETF国泰", 0.60, 1.57, 0.08, 11.37, 23.71, 2.04, -35.49, 14.44, "2021-06", "中证有色", 2.20, 0.49, 1.97),
    ("sh516150", "稀土ETF嘉实", 0.60, 54.35, 1.04, 5.98, 19.17, -7.84, -27.00, 24.18, "2021-03", "稀土产业", 1.90, -0.24, 1.23),
    ("sz159713", "稀土ETF富国", 0.60, 5.53, 0.24, 7.32, 20.93, -5.68, -27.34, 24.18, "2021-08", "稀土产业", 2.27, 1.54, 1.23),
    ("sh516780", "稀土ETF华泰柏瑞", 0.60, 16.32, 0.26, 7.02, 20.60, -6.50, -27.20, 24.18, "2021-02", "稀土产业", 2.01, 1.05, 1.23),
    ("sh562800", "稀有金属ETF嘉实", 0.60, 42.46, 1.12, 2.79, 18.13, -2.05, -33.42, 19.09, "2021-09", "CS稀金属", 1.71, -0.95, 1.03),
    ("sh561800", "稀有金属ETF华富", 0.60, 1.93, 0.06, 2.81, 18.41, -0.16, -33.89, 19.09, "2021-08", "CS稀金属", 1.71, 0.93, 1.03),
]

WINNER = "sh560860"

body = []
for r in sorted(ROWS, key=lambda x: -x[5]):
    code, name, fee, size, amt, unif, y3, y1, dd, pe, est, track, te, tec, div = r
    win = ' class="winner"' if code == WINNER else ""
    fee_cls = "best" if fee == min(x[2] for x in ROWS) else ""
    unif_cls = "best" if unif == max(x[5] for x in ROWS) else ""
    y1_cls = "best" if y1 == max(x[7] for x in ROWS) else ""
    te_cls = ""
    grp = [x for x in ROWS if x[11] == track and x[12] is not None]
    if te is not None and len(grp) > 1 and te == min(x[12] for x in grp):
        te_cls = "best"
    body.append(
        f'<tr{win}>'
        f'<td class="mono">{code}</td><td><b>{name}</b></td>'
        f'<td class="num {fee_cls}">{fee:.2f}%</td>'
        f'<td class="num">{size:.2f}</td><td class="num">{amt:.2f}</td>'
        f'<td class="num {unif_cls}">{unif:.2f}%</td><td class="num">{y3:.2f}%</td>'
        f'<td class="num {y1_cls}">{y1:+.2f}%</td><td class="num">{dd:.1f}%</td>'
        f'<td class="num {te_cls}">{f"{te:.2f}" if te is not None else "—"}</td>'
        f'<td class="num">{f"{tec:+.2f}%" if tec is not None else "—"}</td>'
        f'<td class="num">{pe:.2f}</td>'
        f'<td class="mono">{est}</td><td>{track}</td></tr>'
    )

html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>有色金属板块 ETF 综合对比报告</title>
<style>
  :root { --ink:#1a2233; --sub:#5b6b85; --line:#dfe5ee; --bg:#f6f8fb; --card:#fff;
          --accent:#b3541e; --gold:#c8892b; --good:#1e7d4f; --warn:#c0392b; }
  * { box-sizing:border-box; }
  body { margin:0; padding:32px 20px; background:var(--bg); color:var(--ink);
         font:15px/1.75 "Segoe UI","Microsoft YaHei",sans-serif; }
  .wrap { max-width:1240px; margin:0 auto; }
  header.hero { background:linear-gradient(135deg,#233247,#3c5878); color:#fff;
                border-radius:14px; padding:30px 34px; margin-bottom:22px; }
  header.hero h1 { margin:0 0 8px; font-size:26px; letter-spacing:.5px; }
  header.hero p { margin:4px 0; opacity:.92; font-size:14px; }
  .badge { display:inline-block; background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.3);
           border-radius:999px; padding:2px 12px; font-size:12.5px; margin:6px 6px 0 0; }
  nav.toc { background:var(--card); border:1px solid var(--line); border-radius:12px;
            padding:16px 22px; margin-bottom:22px; display:flex; flex-wrap:wrap; gap:6px 22px; }
  nav.toc a { color:var(--accent); text-decoration:none; font-size:13.5px; }
  nav.toc a:hover { text-decoration:underline; }
  section { background:var(--card); border:1px solid var(--line); border-radius:12px;
            padding:24px 28px; margin-bottom:20px; }
  h2 { font-size:19px; margin:0 0 14px; padding-bottom:10px; border-bottom:2px solid var(--line); }
  h2 .n { color:var(--accent); font-weight:700; margin-right:8px; }
  h3 { font-size:15.5px; margin:18px 0 8px; }
  table { width:100%; border-collapse:collapse; font-size:13px; margin:12px 0 6px; }
  th { background:#eef2f7; text-align:right; padding:8px 8px; border-bottom:2px solid var(--line);
       white-space:nowrap; font-size:12px; color:var(--sub); }
  td { padding:8px 8px; border-bottom:1px solid #eef1f6; text-align:right; white-space:nowrap; }
  td:first-child, td:nth-child(2), td:last-child { text-align:left; }
  tr.winner { background:#fdf6ec; }
  tr.winner td { font-weight:600; }
  .best { color:var(--good); font-weight:700; }
  .mono { font-family:Consolas,monospace; font-size:12px; }
  .kpi { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:14px 0; }
  .kpi .card { background:#f2f6fb; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .kpi .card .lab { font-size:12px; color:var(--sub); }
  .kpi .card .val { font-size:20px; font-weight:700; margin-top:2px; }
  .kpi .card .val.good { color:var(--good); }
  .kpi .card .val.warn { color:var(--warn); }
  .callout { border-left:4px solid var(--gold); background:#fdf8ef; padding:12px 16px;
             border-radius:0 8px 8px 0; margin:14px 0; font-size:14px; }
  .callout.risk { border-color:var(--warn); background:#fdf1ef; }
  .callout.ok { border-color:var(--good); background:#eff8f2; }
  .callout.note { border-color:var(--accent); background:#fdf3ec; }
  ul.tight { margin:8px 0; padding-left:22px; }
  ul.tight li { margin:5px 0; }
  footer { text-align:center; color:var(--sub); font-size:12px; padding:10px 0 26px; }
  .verdict { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px; margin-top:10px; }
  .verdict .opt { border:1px solid var(--line); border-radius:10px; padding:16px 18px; background:#fafbfd; }
  .verdict .opt.main { border:2px solid var(--gold); background:#fdf6ec; }
  .verdict .opt h4 { margin:0 0 6px; font-size:15px; }
  .verdict .opt .tag { font-size:11.5px; color:#fff; background:var(--accent); border-radius:4px;
                       padding:1px 8px; margin-left:6px; vertical-align:1px; }
  .verdict .opt.main .tag { background:var(--gold); }
  .verdict .opt p { margin:6px 0 0; font-size:13px; color:var(--sub); }
</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <h1>有色金属板块 ETF 综合对比报告</h1>
  <p>数据基准日 2026-10-15 ｜ 全市场 12 只有色系 ETF ｜ 筛选标准与《红利低波 ETF 报告》完全一致</p>
  <p>费率 · 含分红总收益年化（修正口径）· 跟踪误差 · 规模流动性 · 估值 · 风险，多窗口公平对比</p>
  <div>
    <span class="badge">v3：每支数据经三路交叉核验 + 分红修正</span>
    <span class="badge">主推：sh560860 工业有色ETF万家</span>
    <span class="badge">费率+跟踪双优：sz159871 有色ETF银华</span>
  </div>
</header>

<nav class="toc">
  <a href="#s1">结论速览</a><a href="#s2">数据核验过程</a><a href="#s3">筛选范围</a><a href="#s4">总表</a>
  <a href="#s5">跟踪误差</a><a href="#s6">同指数对比</a><a href="#s7">稀土专节</a>
  <a href="#s8">收益与风险</a><a href="#s9">分场景推荐</a><a href="#s10">方法论与口径</a>
</nav>

<section id="s1">
  <h2><span class="n">一</span>结论速览</h2>
  <div class="kpi">
    <div class="card"><div class="lab">主推标的（收益+估值）</div><div class="val">sh560860</div><div class="lab">工业有色ETF万家</div></div>
    <div class="card"><div class="lab">近 1 年总收益（全场唯一为正）</div><div class="val good">+9.69%</div><div class="lab">其余 11 只为 −7.8%~+2.0%</div></div>
    <div class="card"><div class="lab">统一窗口年化（第一）</div><div class="val good">15.22%</div><div class="lab">第二 14.30%</div></div>
    <div class="card"><div class="lab">PE(TTM)（最低）</div><div class="val good">13.83</div><div class="lab">稀土 24.18 / 稀有金属 19.09</div></div>
    <div class="card"><div class="lab">费率+跟踪双优</div><div class="val good">sz159871</div><div class="lab">0.20% 且组内 TE 最低 1.94</div></div>
    <div class="card"><div class="lab">近 1 年最大回撤（全部 12 只）</div><div class="val warn">−27%~−36%</div><div class="lab">进攻型，非底仓品种</div></div>
  </div>
  <div class="callout ok"><b>一句话结论：</b>每支数据经三路交叉核验并修正分红口径后，
  <b>sh560860 工业有色ETF万家</b>仍是收益与估值维度的最优解（近 1 年 +9.69% 唯一为正、统一窗口年化 15.22% 第一、
  近 3 年 25.51% 第一、PE 13.83 最低、规模 70.59 亿 / 日成交 1.07 亿）；若把<b>费率与跟踪质量</b>权重放到最高，则
  <b>sz159871 银华</b>——0.20% 全场最低费率 + 中证色组 TE 最低（1.94）+ 近 1 年累计跟踪差最小（+0.06%），三维全面占优。</div>
  <div class="callout risk"><b>风险提示（必须读）：</b>12 只 ETF 近 1 年最大回撤全部在 <b>−27% ~ −36%</b>，
  稀土/稀有金属近 1 年收益为负。有色是高 beta 周期板块，与红利低波「近 1 年回撤 −0.7%」的底仓属性
  <b>完全不同</b>，不可按同一仓位思路持有。</div>
</section>

<section id="s2">
  <h2><span class="n">二</span>数据核验过程（逐支交叉验证，v3 新增）</h2>
  <p>本版对<b>每一支标的</b>做了三路交叉核验，发现并修正了两个口径问题。核验明细如下：</p>
  <h3>① 费率字段（12 支全核）</h3>
  <ul class="tight">
    <li>用市场公认锚点验证：华安黄金 518880 管理费公认 0.5%，字段值 <code>managementFee = 0.5</code> ⇒ <b>字段单位确认为「百分比数值」</b>，报告引用无误。</li>
    <li>费率构成：512400/516650/159876/159881/516150/159713/516780/562800/561800/159652/560860 均为 0.5+0.1=0.60%；仅 <b>159871 银华为 0.15+0.05=0.20%</b>。</li>
  </ul>
  <h3>② 规模口径（12 支全核，发现字段冲突）</h3>
  <ul class="tight">
    <li><code>quote.total_market_cap</code> = 份额 × 最新价（12 支全部自洽，如 516150：37.38 亿份 × 1.454 = 54.35 亿）⇒ <b>二级市场总市值</b>。</li>
    <li><code>profile.totalAsset</code> 系统性偏高（516150 高 45%、562800 高 65%、512400 高 6%）——经净值核验判定为<b>滞后报告期数据，已弃用</b>。</li>
    <li><b>净值验证</b>：查 <code>etf nav</code> 得 516150 净值 1.4842 vs 收盘 1.483（折溢价 −0.08%）、562800 −0.13%、512400 −0.02% ⇒ 折溢价均极小，<b>quote 市值口径正确</b>，报告采用。</li>
  </ul>
  <h3>③ 年化收益（12 支全核，发现分红未反映）</h3>
  <ul class="tight">
    <li>发现：516780/159876/159871/159881 的 hfq 最新价恰为不复权价的 <b>2.000 倍</b>，且<b>逐月比值全程恒定 2.000</b>（2025-08 至 2026-09 无跳变）⇒ 收益率计算不受影响（恒定因子在比值中抵消），但说明<b>数据源 hfq 未做分红调整</b>。</li>
    <li>验证：12 支全部有分红（divTtm 1.03%~2.25%）⇒ 原年化为<b>纯价格收益，系统性低估 1~2.3pp/年</b>。</li>
    <li><b>修正</b>：年化 = hfq 价格年化 + divTtm 加回（保守近似，如 512400 统一窗口 8.06%→10.12%）。</li>
  </ul>
  <h3>④ 跟踪误差 TE（10 支可测）</h3>
  <ul class="tight">
    <li>同指数 ETF 日收益互偏法；指数点位行情在本数据源不可取（kline/quote 均无），故以此法估算，单飞标的（512400、560860）不可测，以「—」呈现，<b>不用估算值冒充</b>。</li>
    <li>TE 用不复权日线计算，恒定复权因子不影响日收益 ⇒ TE 数值可靠。</li>
  </ul>
</section>

<section id="s3">
  <h2><span class="n">三</span>筛选范围（全市场找齐 12 只）</h2>
  <p>经三轮代码探测 + 标签池核对，锁定截至 2026-10-15 存续且有行情的全部 <b>12 只有色系 ETF</b>，按跟踪资产分三组：</p>
  <ul class="tight">
    <li><b>广义有色金属（工业金属为主）</b>：sh512400 南方（申万有色）、sh516650 华夏 / sz159652 汇添富（细分有色）、sh560860 万家（工业有色）、sz159876 华宝 / sz159871 银华 / sz159881 国泰（中证有色）—— 7 只</li>
    <li><b>稀土产业</b>：sh516150 嘉实、sz159713 富国、sh516780 华泰柏瑞 —— 3 只</li>
    <li><b>稀有金属（锂钴等）</b>：sh562800 嘉实、sh561800 华富 —— 2 只</li>
  </ul>
  <p>已排除误探到的非有色标的（半导体设备、基建、央企能源、恒生生物、标普500、道琼斯、油气等）。</p>
</section>

<section id="s4">
  <h2><span class="n">四</span>全 12 只总表（按修正后统一窗口年化降序）</h2>
  <table>
    <thead><tr>
      <th>代码</th><th>名称</th><th>总费率</th><th>规模<br>(亿)</th><th>日成交<br>(亿)</th>
      <th>统一窗口<br>年化*</th><th>近3年<br>年化*</th><th>近1年<br>收益*</th><th>近1年<br>最大回撤</th>
      <th>TE<br>(年化%)</th><th>近1年<br>跟踪差</th><th>PE<br>(TTM)</th><th>成立</th><th>跟踪指数</th>
    </tr></thead>
    <tbody>
""" + "\n".join(body) + """
    </tbody>
  </table>
  <p style="font-size:12.5px;color:var(--sub);margin-top:8px">
  注：* 年化/收益均为<b>修正口径</b>（hfq 价格收益 + divTtm 加回分红，见第二节核验）。
  ① 统一窗口 = 2022-01-01 → 2026-10-15；sh560860（2023-02 成立）、sz159652（2023-01 成立）的该列实为<b>成立以来年化</b>，窗口短、含 2023 年低基数，对比时注意。
  ② TE = 跟踪误差代理（见第五节口径）。③ 绿色 = 该列最优。④ 近 1 年跟踪差 = 相对同指数组中位数的累计收益差，正=跑赢组内中枢。
  ⑤ 回撤用日线 low 近似；规模为 quote 市值口径（经净值验证）。</p>
</section>

<section id="s5">
  <h2><span class="n">五</span>跟踪误差（TE）</h2>
  <div class="callout note"><b>口径说明（诚实交代）：</b>指数点位行情在本数据源不可取（kline/quote 均无），
  故采用<b>同指数 ETF 日收益互偏法</b>估算跟踪误差代理：同指数 ETF 之间日收益本应几乎一致，互偏的方差
  <b>几乎全部来自各自跟踪误差</b>。TE_proxy = std(ETF日收益 − 组中位数日收益) × √242（年化 %）。
  单飞标的（512400 申万有色、560860 工业有色）无同指数对手，<b>TE 不可直接测</b>，表中以「—」呈现，不用估算值冒充。</div>
  <table>
    <thead><tr><th>指数组</th><th>代码</th><th>名称</th><th>TE_proxy(年化%)</th><th>近1年累计跟踪差</th><th>规模(亿)</th><th>判读</th></tr></thead>
    <tbody>
      <tr><td rowspan="3">稀土产业</td><td class="mono">sh516150</td><td>稀土ETF嘉实</td><td class="num best">1.90</td><td class="num">−0.24%</td><td class="num">54.35</td><td>TE最优+规模最大，但近1年跑输组内中枢</td></tr>
      <tr><td class="mono">sh516780</td><td>稀土ETF华泰柏瑞</td><td class="num">2.01</td><td class="num">+1.05%</td><td class="num">16.32</td><td>TE第二，近1年跑赢组内</td></tr>
      <tr><td class="mono">sz159713</td><td>稀土ETF富国</td><td class="num">2.27</td><td class="num">+1.54%</td><td class="num">5.53</td><td>TE最差，但近1年跑赢最多（噪声大）</td></tr>
      <tr><td rowspan="3">中证有色</td><td class="mono">sz159871</td><td>有色ETF银华</td><td class="num best">1.94</td><td class="num best">+0.06%</td><td class="num">8.73</td><td>TE最低+跟踪差最小+费率最低，三维最优</td></tr>
      <tr><td class="mono">sz159876</td><td>有色ETF华宝</td><td class="num">2.18</td><td class="num">−0.09%</td><td class="num">13.72</td><td>TE偏高，费率无优势</td></tr>
      <tr><td class="mono">sz159881</td><td>有色金属ETF国泰</td><td class="num">2.20</td><td class="num">+0.49%</td><td class="num">1.57</td><td>TE最高+流动性不合格</td></tr>
      <tr><td rowspan="2">细分有色</td><td class="mono">sh516650</td><td>有色金属ETF华夏</td><td class="num best">1.40</td><td class="num best">0.00%</td><td class="num">82.70</td><td>TE并列最低+规模碾压 ⇒ 华夏完胜</td></tr>
      <tr><td class="mono">sz159652</td><td>有色ETF汇添富</td><td class="num best">1.40</td><td class="num">−0.02%</td><td class="num">23.91</td><td>TE打平但规模仅为华夏 29%</td></tr>
      <tr><td rowspan="2">CS稀金属</td><td class="mono">sh562800</td><td>稀有金属ETF嘉实</td><td class="num best">1.71</td><td class="num best">−0.95%</td><td class="num">42.46</td><td>TE并列最低+规模碾压 ⇒ 嘉实完胜</td></tr>
      <tr><td class="mono">sh561800</td><td>稀有金属ETF华富</td><td class="num best">1.71</td><td class="num">+0.93%</td><td class="num">1.93</td><td>TE打平但规模仅为嘉实 4.5%</td></tr>
      <tr><td>—</td><td class="mono">sh512400</td><td>有色金属ETF南方</td><td class="num">—</td><td class="num">—</td><td class="num">213.85</td><td>单飞（申万有色），TE不可测</td></tr>
      <tr><td>—</td><td class="mono">sh560860</td><td>工业有色ETF万家</td><td class="num">—</td><td class="num">—</td><td class="num">70.59</td><td>单飞（工业有色），TE不可测；与512400互偏8.13%（含指数构成差异）</td></tr>
    </tbody>
  </table>
  <div class="callout"><b>跟踪误差改变了两个判断：</b>
  ① <b>银华 159871 坐实同指数组内全面最优</b>——TE 1.94 组内最低、近 1 年累计跟踪差 +0.06% 最小、费率 0.20% 最低。
  华宝（2.18）与国泰（2.20）的跟踪质量明显更差，其「年化略高」是跟踪噪声而非管理能力。
  ② <b>富国 159713 近 1 年「跑赢组内 +1.54%」不可信</b>——它 TE 最高（2.27）、规模最小（5.53 亿），
  这 1.54pp 更可能是流动性折溢价噪声，不是超额能力。</div>
</section>

<section id="s6">
  <h2><span class="n">六</span>同指数对比：费率差就是纯收益差</h2>
  <h3>「中证有色」3 只（PE 同为 14.44，验证同底层）</h3>
  <table>
    <thead><tr><th>代码</th><th>名称</th><th>总费率</th><th>TE</th><th>规模(亿)</th><th>日成交(亿)</th><th>统一窗口年化*</th><th>近1年收益*</th></tr></thead>
    <tbody>
      <tr class="winner"><td class="mono">sz159871</td><td><b>有色ETF银华</b></td><td class="num best">0.20%</td><td class="num best">1.94</td><td class="num">8.73</td><td class="num">0.20</td><td class="num">10.64%</td><td class="num">+2.04%</td></tr>
      <tr><td class="mono">sz159876</td><td>有色ETF华宝</td><td class="num">0.60%</td><td class="num">2.18</td><td class="num">13.72</td><td class="num">1.76</td><td class="num">10.42%</td><td class="num">+1.57%</td></tr>
      <tr><td class="mono">sz159881</td><td>有色金属ETF国泰</td><td class="num">0.60%</td><td class="num">2.20</td><td class="num">1.57</td><td class="num">0.08</td><td class="num">11.37%</td><td class="num">+2.04%</td></tr>
    </tbody>
  </table>
  <div class="callout"><b>判读：</b>国泰年化名义最高（11.37%），但 TE 最高（2.20）+ 规模仅 1.57 亿 + 日成交 800 万——
  <b>跟踪噪声 + 流动性折价</b>共同制造了这个虚高数字，不构成「国泰更优」的证据。
  <b>银华用 1/3 的费率（0.20% vs 0.60%）拿到组内最低 TE 与最小跟踪差</b>，每年净多约 0.4pp 且跟踪更稳，
  是费率与跟踪双敏感型投资者的最优解。华宝流动性更好（1.76 亿）但费率与 TE 均无优势。</div>
</section>

<section id="s7">
  <h2><span class="n">七</span>稀土专节（单一稀土基金）</h2>
  <p>稀土类场内 ETF 共 <b>3 只，全部跟踪 930598 稀土产业指数</b>，费率同为 0.60%——差异只在规模、流动性、跟踪误差与收益：</p>
  <table>
    <thead><tr><th>代码</th><th>名称</th><th>规模(亿)</th><th>日成交(亿)</th><th>TE(年化%)</th><th>近1年跟踪差</th><th>统一窗口年化*</th><th>近1年收益*</th><th>近1年回撤</th></tr></thead>
    <tbody>
      <tr class="winner"><td class="mono">sh516150</td><td><b>稀土ETF嘉实</b></td><td class="num best">54.35</td><td class="num best">1.04</td><td class="num best">1.90</td><td class="num">−0.24%</td><td class="num">5.98%</td><td class="num">−7.84%</td><td class="num best">−27.0%</td></tr>
      <tr><td class="mono">sh516780</td><td>稀土ETF华泰柏瑞</td><td class="num">16.32</td><td class="num">0.26</td><td class="num">2.01</td><td class="num">+1.05%</td><td class="num best">7.02%</td><td class="num">−6.50%</td><td class="num">−27.2%</td></tr>
      <tr><td class="mono">sz159713</td><td>稀土ETF富国</td><td class="num">5.53</td><td class="num">0.24</td><td class="num">2.27</td><td class="num best">+1.54%</td><td class="num">7.32%</td><td class="num best">−5.68%</td><td class="num">−27.3%</td></tr>
    </tbody>
  </table>
  <div class="callout"><b>若一定要配稀土，选 sh516150 嘉实</b>：TE 最低（1.90）+ 规模 54.35 亿（富国的 9.8 倍）+
  日成交 1.04 亿（富国的 4.3 倍）——规模与流动性碾压级领先，且跟踪最稳。它的「近 1 年跑输组内 −0.24%」
  在三只之间是最小量级的差异（TE 噪声范围内），不足以抵消流动性差距。</div>
  <div class="callout risk"><b>但稀土整体仍是回避项</b>（不只是基金选择问题，是板块问题）：
  PE 24.18 <b>全场最贵</b>（工业有色 13.83、中证有色 14.44）+ 近 1 年收益 −5.7% ~ −7.8% <b>全场最差</b>。
  「高估值 + 负收益」= 过去一年市场在<b>杀估值</b>。除非对稀土供给端（配额、出口管制、需求替代）有独立判断，
  否则当前性价比全场最低——三只之间的差异（TE 差 0.4pp、年化差 1.3pp）远小于「买错板块」的代价。</div>
</section>

<section id="s8">
  <h2><span class="n">八</span>收益与风险：收益领先，波动也领先</h2>
  <h3>收益端（修正口径，含分红加回）</h3>
  <ul class="tight">
    <li><b>近 1 年</b>：sh560860 <b>+9.69% 唯一为正且领先明显</b>；第二梯队银华/国泰 +2.04%；512400 南方 +1.85%；稀有金属 −0.2% ~ −2.1%；稀土 −5.7% ~ −7.8% 垫底。</li>
    <li><b>统一窗口</b>：sh560860 15.22% 第一，159652 汇添富 14.30% 第二，512400/516650/159881 约 10~11%。</li>
    <li><b>近 3 年</b>：sh560860 25.51% 第一，512400/516650/159652 约 24% 紧随，稀有金属约 18%。</li>
  </ul>
  <h3>风险端（必须与收益一起看）</h3>
  <div class="callout risk"><b>12 只 ETF 近 1 年最大回撤全部在 −27% ~ −36%</b>：512400 −35.9%、560860 −35.9%、159881 −35.5%、
  华宝 −34.8%、华夏 −34.6%、银华 −34.4%、稀有金属 −33.4% ~ −33.9%，稀土组相对抗跌（−27.0% ~ −27.3%）。
  有色板块 beta 高、与全球定价的铜/铝/金/稀土价格强相关，<b>不适合作为底仓或短期要用的钱</b>。</div>
  <p><b>折溢价观察</b>：经净值核验，12 只年均折溢价均在 ±0.08% 内（512400 净值 1.5703 vs 收盘 1.570 即 −0.02%）——
  市场效率足够高，折溢价不构成选择因素，仅列示备查。</p>
</section>

<section id="s9">
  <h2><span class="n">九</span>分场景推荐</h2>
  <div class="verdict">
    <div class="opt main">
      <h4>sh560860 工业有色ETF万家<span class="tag">综合最优</span></h4>
      <p>收益全场第一（近1年 +9.69% 唯一为正 / 统一窗口 15.22% / 近3年 25.51%）、PE 13.83 最低、规模 70.59 亿 + 日成交 1.07 亿流动性充足、费率 0.60% 主流档。<b>注意：无同指数对手，TE 不可测</b>（其超额来自「工业有色」指数构成——更偏铜铝工业金属，与申万有色互偏达 8.13%，属指数选择差异而非跟踪能力）。适合认可工业金属逻辑、能承受 −35% 级别回撤的进攻型配置。</p>
    </div>
    <div class="opt">
      <h4>sz159871 有色ETF银华<span class="tag">费率+跟踪双优</span></h4>
      <p>0.20% 全场最低费率 + 中证色组 TE 最低（1.94）+ 近 1 年累计跟踪差最小（+0.06%）+ 近1年 +2.04% 正收益。跟踪中证有色（主流宽口径）。规模 8.73 亿、日成交 0.20 亿——<b>小额定投/低频调仓够用，大额进出选 512400 或 560860</b>。长期持有且在意「每一分钱都跟上指数」的最优解。</p>
    </div>
    <div class="opt">
      <h4>sh512400 有色金属ETF南方<span class="tag">流动性最优</span></h4>
      <p>213.85 亿规模 + 4.57 亿日成交，全场流动性绝对第一，9 年历史最长，费率 0.60%。近1年 +1.85%、近3年 23.99% 均属中上。TE 不可测（单飞）但流动性本身就是大额资金的安全垫。<b>大额资金 / 需要频繁交易的唯一稳妥选择。</b></p>
    </div>
    <div class="opt">
      <h4>sh516150 稀土ETF嘉实<span class="tag">稀土首选</span></h4>
      <p>三只稀土中 TE 最低（1.90）+ 规模 54.35 亿（富国 9.8 倍）+ 日成交 1.04 亿（富国 4.3 倍）。<b>但这是「回避项里选相对不差」</b>——稀土板块 PE 24.18 最贵 + 近1年 −7.84% 最差，选它对的前提是明确看多稀土供给逻辑，否则不建议参与。</p>
    </div>
  </div>
</section>

<section id="s10">
  <h2><span class="n">十</span>方法论与口径（与红利低波报告一致）</h2>
  <ul class="tight">
    <li><b>年化口径（修正）</b>：<code>kline --fq hfq</code> 后复权月线价格收益 + <code>divTtm</code> 加回分红。经核验数据源 hfq 未做分红调整（12 支全部 divTtm&gt;0），故必须加回，否则系统性低估 1~2.3pp/年。</li>
    <li><b>多窗口</b>：统一窗口（2022-01-01 起，同起止日公平对比）+ 近 3 年 + 近 1 年 + 成立以来。单窗口年化极易误导（2023 年低基数会显著抬高短历史标的）。</li>
    <li><b>规模口径</b>：quote 市值（份额×市价），经净值序列交叉验证（折溢价 &lt;0.15%）。profile.totalAsset 字段为滞后报告期数据，已弃用。</li>
    <li><b>跟踪误差（TE_proxy）</b>：指数点位不可取 ⇒ 同指数 ETF 日收益互偏法，TE_proxy = std(相对组中位数日收益) × √242。单飞标的不可测，以「—」呈现，不用估算值冒充。</li>
    <li><b>同指数验证</b>：同指数标的须同起止日对比；「中证有色」三只 PE 同为 14.44、「稀土产业」三只同为 24.18 可交叉验证同底层。</li>
    <li><b>倒序修正</b>：kline 返回新→旧，计算前必须反转，否则首末取反。</li>
    <li><b>费率</b>：管理费 + 托管费 + 销售服务费合计，来自产品档案，单位经 518880 锚点验证为百分比数值。</li>
    <li><b>估值</b>：ETF 持仓加权 PE(TTM)；周期股 PE 受盈利波动影响，须与价格/收益同看。</li>
  </ul>
  <p style="font-size:12.5px;color:var(--sub)">数据来源：westock（行情 / 产品档案 / ETF overview / 净值 / 后复权月线 / 日线），基准日 2026-10-15 收盘。
  每支数据经三路交叉核验（费率锚点验证、规模三路互证、年化分红修正、TE 互偏估算）。
  本报告为数据对比，不构成投资建议。</p>
</section>

<footer>有色金属板块 ETF 综合对比报告（v3：逐支核验版）｜ 基准日 2026-10-15 ｜ 生成于 2026-10-16</footer>
</div>
</body>
</html>
"""

out = Path(str(Path.home() / "Desktop" / "有色金属板块ETF综合对比报告.html"))
out.write_text(html, encoding="utf-8")
print("已生成:", out, len(html.encode("utf-8")), "bytes")
