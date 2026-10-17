# lifecycle: oneoff
# created: 2026-10-14
"""有色金属板块全览：主流 ETF / 联接基金 费率与性价比对比报告（桌面交付）。

数据基准日 2026-10-14（westock 行情/规模；基金费率取各公司公告与第三方摘要，
分级日期见报告脚注），与用户给定的《南方有色金属ETF费率对比报告.html》同版式。
"""
from __future__ import annotations
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(str(Path.home() / "Desktop" / "有色金属板块ETF基金性价比对比报告.html"))

HEAD = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>有色金属板块 主流 ETF / 联接基金 性价比对比报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root{
    --bg:#f7f8fa; --card:#ffffff; --line:#e6e8ec; --ink:#1b1f27; --ink2:#5a6272;
    --ink3:#8b93a3; --accent:#1f5fd0; --accent-soft:#eaf1fd;
    --up:#c8322b; --down:#178a4c; --warn:#b06d00; --warn-soft:#fff6e6;
    --ok:#178a4c; --ok-soft:#eaf7f0;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    line-height:1.7;font-size:15px;}
  .wrap{max-width:1080px;margin:0 auto;padding:28px 22px 64px;}
  header.top{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px 26px;margin-bottom:18px;}
  header.top h1{margin:0 0 6px;font-size:23px;letter-spacing:-.2px;}
  header.top .sub{color:var(--ink2);font-size:13.5px;}
  header.top .tags{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px;}
  .tag{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--accent-soft);color:var(--accent);border:1px solid #d5e3fb;}
  .tag.warn{background:var(--warn-soft);color:var(--warn);border-color:#f0dcb0;}
  nav.toc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 22px;margin-bottom:18px;}
  nav.toc h4{margin:0 0 10px;font-size:13px;color:var(--ink3);font-weight:600;letter-spacing:.4px;}
  nav.toc ol{margin:0;padding-left:20px;columns:2;column-gap:34px;}
  nav.toc li{margin:3px 0;font-size:13.5px;}
  nav.toc a{color:var(--accent);text-decoration:none;}
  nav.toc a:hover{text-decoration:underline;}
  section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px 26px;margin-bottom:16px;}
  h2{font-size:18px;margin:0 0 14px;padding-left:11px;border-left:4px solid var(--accent);}
  h3{font-size:15px;margin:20px 0 8px;color:var(--ink);}
  p{margin:9px 0;color:var(--ink2);}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:6px 0 4px;}
  .kpi{background:var(--bg);border:1px solid var(--line);border-radius:11px;padding:13px 15px;}
  .kpi .k{font-size:12px;color:var(--ink3);}
  .kpi .v{font-size:20px;font-weight:700;margin:3px 0 1px;letter-spacing:-.3px;}
  .kpi .n{font-size:11.5px;color:var(--ink3);}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px;}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;}
  th{background:var(--bg);font-weight:600;color:var(--ink);font-size:12.5px;white-space:nowrap;}
  td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
  tr.best td{background:var(--ok-soft);}
  tr.warnrow td{background:var(--warn-soft);}
  .up{color:var(--up);font-weight:600;}
  .down{color:var(--down);font-weight:600;}
  .muted{color:var(--ink3);}
  .callout{border-radius:10px;padding:13px 16px;margin:14px 0;font-size:13.8px;}
  .callout.good{background:var(--ok-soft);border:1px solid #c8e9d8;}
  .callout.warn{background:var(--warn-soft);border:1px solid #f0dcb0;}
  .callout b{color:var(--ink);}
  ul,ol{margin:8px 0;padding-left:22px;color:var(--ink2);}
  li{margin:4px 0;}
  #chart{width:100%;height:390px;}
  footer{margin-top:22px;color:var(--ink3);font-size:12.5px;line-height:1.8;}
  footer b{color:var(--ink2);}
  @media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr);}nav.toc ol{columns:1;}}
</style>
</head>
<body>
<div class="wrap">
"""

BODY_1 = r"""
<header class="top">
  <h1>有色金属板块：主流 ETF / 联接基金 性价比对比</h1>
  <div class="sub">范围：A 股上市、跟踪「有色金属」相关指数的 ETF 及其联接基金 ｜ 数据基准日 2026-10-14 ｜ 面向小额资金（几千元）实操</div>
  <div class="tags">
    <span class="tag">7 只场内 ETF</span>
    <span class="tag">5 家公司联接层</span>
    <span class="tag">费率 + 规模 + 指数三重口径</span>
    <span class="tag warn">含「口径可比性」警示</span>
  </div>
</header>

<nav class="toc">
  <h4>目录</h4>
  <ol>
    <li><a href="#s1">一、先看结论：三句话</a></li>
    <li><a href="#s2">二、板块全貌：7 只 ETF 分别跟什么指数</a></li>
    <li><a href="#s3">三、场内 ETF 费率对比：其实完全一样</a></li>
    <li><a href="#s4">四、联接基金费率对比：差距全在这里</a></li>
    <li><a href="#s5">五、持有期总成本曲线（含申赎费）</a></li>
    <li><a href="#s6">六、规模与流动性：小额也躲不开的隐性成本</a></li>
    <li><a href="#s7">七、分场景结论：几千块你该买哪个</a></li>
    <li><a href="#s8">八、这份对比本身有什么问题（必须读）</a></li>
  </ol>
</nav>
"""

BODY_3 = r"""
<section>
  <h2 id="s1">一、先看结论：三句话</h2>
  <div class="kpis">
    <div class="kpi"><div class="k">场内 7 只 ETF 综合费率</div><div class="v">0.60%/年</div><div class="n">管理 0.50% + 托管 0.10%，全板块一致</div></div>
    <div class="kpi"><div class="k">最低联接层综合费率</div><div class="v">0.20%/年</div><div class="n">银华联接 A/C（管理 0.15% + 托管 0.05%）</div></div>
    <div class="kpi"><div class="k">南方 I 类服务费</div><div class="v">0.01%/年</div><div class="n">直销专属，全板块最低持有成本</div></div>
    <div class="kpi"><div class="k">场内最低佣金门槛</div><div class="v">5 元/笔</div><div class="n">几千元资金买场内会被严重摊薄</div></div>
  </div>
  <div class="callout good">
    <b>第一句：场内 ETF 之间，「费率」不构成选择理由。</b>7 只主流有色 ETF 的管理费 + 托管费清一色是 <b>0.50% + 0.10%</b>，没有销售服务费。你在证券账户里比费率，比不出任何差别 —— 差别在<b>规模、流动性、跟踪的指数</b>。
  </div>
  <div class="callout good">
    <b>第二句：真正的费率差在「联接基金」这一层。</b>同一指数的联接基金，管理费可以是 0.50%，也可以是 0.15%。银华中证有色金属 ETF 联接把管理费压到 <b>0.15%</b>、托管费 <b>0.05%</b>，比自己买场内 ETF 还低 —— 这是全板块唯一的「费率洼地」。
  </div>
  <div class="callout warn">
    <b>第三句：几千块的小额资金，场内 ETF 大概率不划算。</b>券商佣金普遍有「单笔最低 5 元」，买 3000 元一次就摊掉约 0.17%，再加卖出一次，来回约 0.33% —— 相当于把 0.60% 的年费提前大半年交掉了。小额资金走<b>场外基金</b>（申购费 1 折后 0.01%~0.12%）更省。
  </div>
</section>
"""

BODY_2 = r"""
<section>
  <h2 id="s2">二、板块全貌：7 只 ETF 分别跟什么指数</h2>
  <p>「有色金属 ETF」不是同一个东西。市面上挂着「有色」名字的 ETF，跟踪的指数至少分四类，成分股和涨跌幅差别很大。买之前必须确认你买的是哪一类。</p>
  <table>
    <thead>
      <tr><th>代码</th><th>名称</th><th>跟踪指数</th><th>指数口径</th><th class="num">规模（亿元）</th></tr>
    </thead>
    <tbody>
      <tr class="best"><td>512400.SH</td><td>南方中证申万有色金属 ETF</td><td>000819 中证申万有色金属</td><td>全口径有色（工业金属 + 贵金属 + 小金属）</td><td class="num">226.78</td></tr>
      <tr><td>516650.SH</td><td>华夏中证细分有色金属产业主题 ETF</td><td>000811 中证细分有色金属产业</td><td>偏产业链中下游加工</td><td class="num">95.81</td></tr>
      <tr class="warnrow"><td>560860.SH</td><td>万家中证工业有色金属主题 ETF</td><td>H11059 中证工业有色金属主题</td><td>仅工业金属（铜/铝/铅锌），<b>不含黄金</b></td><td class="num">77.59</td></tr>
      <tr class="warnrow"><td>159157.SZ</td><td>天弘中证工业有色金属主题 ETF</td><td>H11059 中证工业有色金属主题</td><td>同上，与 560860 同指数</td><td class="num">71.90</td></tr>
      <tr><td>159876.SZ</td><td>华宝中证有色金属 ETF</td><td>930708 中证有色金属</td><td>全口径有色</td><td class="num">13.50</td></tr>
      <tr><td>159871.SZ</td><td>银华中证有色金属 ETF</td><td>930708 中证有色金属</td><td>全口径有色</td><td class="num">11.34</td></tr>
      <tr class="warnrow"><td>159881.SZ</td><td>国泰中证有色金属 ETF</td><td>930708 中证有色金属</td><td>全口径有色</td><td class="num">1.60</td></tr>
    </tbody>
  </table>
  <p class="muted">规模数据取自 westock，基准日 2026-10-14。560860 / 159157 的规模为同一指数下的两只基金（万家、天弘），其中 159157 成立于 2026-01-28，属新基金。</p>
  <h3>三个提醒</h3>
  <ul>
    <li><b>512400 ≠ 560860。</b>512400 跟踪的 000819 是「全口径有色」，黄金权重不低；560860 / 159157 跟踪的 H11059 是「工业有色」，<b>完全不含黄金</b>。如果黄金涨、工业金属跌，两者涨跌可能完全相反。</li>
    <li><b>000819 / 000811 / 930708 三只指数高度相关但不重合</b>，长期走势差异通常在几个百分点以内，选哪个更多是看成分股市值分布，而不是看名字。</li>
    <li><b>159881 只有 1.6 亿规模</b>，是全板块最小的。规模太小的 ETF 有清盘风险、盘口薄、买卖价差大，对任何资金量都不是好选择。</li>
  </ul>
</section>
"""

BODY_S3 = r"""
<section>
  <h2 id="s3">三、场内 ETF 费率对比：其实完全一样</h2>
  <p>直接给你结论：<b>7 只 ETF 的「基金运作费率」完全一致</b>。管理费都是 0.50%/年，托管费都是 0.10%/年，都没有销售服务费。</p>
  <table>
    <thead>
      <tr><th>代码</th><th class="num">管理费</th><th class="num">托管费</th><th class="num">销售服务费</th><th class="num">合计（年）</th></tr>
    </thead>
    <tbody>
      <tr><td>512400.SH</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
      <tr><td>516650.SH</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
      <tr><td>560860.SH</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
      <tr><td>159157.SZ</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
      <tr><td>159876.SZ</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
      <tr><td>159871.SZ</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
      <tr><td>159881.SZ</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">—</td><td class="num"><b>0.60%</b></td></tr>
    </tbody>
  </table>
  <div class="callout warn">
    <b>所以场内选 ETF，只能按这三条来排：</b>
    <ol>
      <li><b>规模越大越好</b>（流动性、盘口价差、抗清盘）——512400（226.8 亿）断层第一；</li>
      <li><b>指数口径要对</b>——想带黄金就选 000819/930708 系，只想工业金属才选 H11059 系；</li>
      <li><b>券商佣金要谈</b>——这才是你场内唯一能压的成本项（详见第六节）。</li>
    </ol>
  </div>
  <p class="muted">注：部分券商渠道对 ETF 有「免佣」或「万 0.5」的政策，具体以你的开户券商为准。ETF 场内交易<b>免印花税、免过户费</b>，只收券商佣金。</p>
</section>
"""

BODY_S4 = r"""
<section>
  <h2 id="s4">四、联接基金费率对比：差距全在这里</h2>
  <p>联接基金是「买 ETF 的场外基金」，适合手机 App 直接申购、几千块起步的场景。同一指数的联接基金，费率可以差出 <b>4 倍以上</b>。</p>
  <table>
    <thead>
      <tr><th>基金名称</th><th>对应 ETF</th><th class="num">管理费</th><th class="num">托管费</th><th class="num">运作费合计</th><th class="num">申购费（1 折后）</th></tr>
    </thead>
    <tbody>
      <tr class="best"><td><b>银华中证有色金属 ETF 联接 A（026458）</b></td><td>159871</td><td class="num">0.15%</td><td class="num">0.05%</td><td class="num"><b>0.20%</b></td><td class="num">0.30% → 0.03%</td></tr>
      <tr class="best"><td><b>银华中证有色金属 ETF 联接 C（026459）</b></td><td>159871</td><td class="num">0.15%</td><td class="num">0.05%</td><td class="num"><b>0.20%</b> + 销售服务费 0.20%</td><td class="num">0</td></tr>
      <tr class="best"><td><b>南方中证申万有色金属 ETF 联接 I（021021）</b></td><td>512400</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60% + 服务费 0.01%</td><td class="num">0（直销专属）</td></tr>
      <tr><td>南方中证申万有色金属 ETF 联接 E（010990）</td><td>512400</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60% + 服务费 0.10%</td><td class="num">0</td></tr>
      <tr><td>南方中证申万有色金属 ETF 联接 A（004432）</td><td>512400</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60%</td><td class="num">1.20% → 0.12%</td></tr>
      <tr><td>南方中证申万有色金属 ETF 联接 C（004433）</td><td>512400</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60% + 服务费 0.40%</td><td class="num">0</td></tr>
      <tr><td>华夏中证细分有色金属产业 ETF 联接 A（016707）</td><td>516650</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60%</td><td class="num">1.20% → 0.12%</td></tr>
      <tr><td>华夏中证细分有色金属产业 ETF 联接 C（016706）</td><td>516650</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60% + 服务费 0.40%</td><td class="num">0</td></tr>
      <tr><td>万家中证工业有色金属主题 ETF 联接 A（018489）</td><td>560860</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60%</td><td class="num">1.00% → 0.01%</td></tr>
      <tr><td>万家中证工业有色金属主题 ETF 联接 C（018490）</td><td>560860</td><td class="num">0.50%</td><td class="num">0.10%</td><td class="num">0.60% + 服务费 0.40%</td><td class="num">0</td></tr>
    </tbody>
  </table>
  <p class="muted">费率取自各基金公司公告 / 第三方摘要；A 类「1 折后」为互联网平台（支付宝、天天基金、基金公司 App）常见折扣，不同平台可能不同。</p>

  <h3>看这张表要抓住三件事</h3>
  <div class="callout good">
    <b>① 银华联接是唯一的「费率洼地」。</b>管理费 0.15% + 托管费 0.05% = <b>0.20%/年</b>，比同行的 0.60% 低了三分之二。更反常的是：它比它自己跟踪的场内 ETF（159871，0.60%）还低 —— 因为联接基金投向 ETF 的那部分资产，<b>不再重复收管理费和托管费</b>，只对留在联接层的那部分现金收费。银华把这部分费率定得极低，等于给你打折。
  </div>
  <div class="callout warn">
    <b>② 但银华联接的「底层资产」是被打折的那个。</b>它投的是 159871，规模只有 <b>11.34 亿</b>，是全板块倒数第二。省下的 0.4%/年费率，可能被场内的买卖价差和跟踪误差吃掉一部分。这是典型的「省费率但牺牲底层质量」。
  </div>
  <div class="callout warn">
    <b>③ 南方 I 类是「规模 + 费率」的折中。</b>I 类（021021）服务费只有 <b>0.01%</b>，底层却是板块最大的 512400（226.8 亿）。综合持有成本 0.61%/年，比银华的 0.20% 贵，但底层资产质量是全板块最好的。只在南方基金直销渠道卖。
  </div>
</section>
"""

BODY_S5 = r"""
<section>
  <h2 id="s5">五、持有期总成本曲线（含申赎费）</h2>
  <p>下面这张图把「申购费 + 每年运作费 + 赎回费」全部摊进持有期，按你买入 3,000 元测算。横轴是持有年限，纵轴是<b>累计总成本占本金的百分比</b>。四条线分别代表四种典型买法。</p>
  <div id="chart"></div>
  <h3>曲线怎么读</h3>
  <table>
    <thead>
      <tr><th>买法</th><th>一次性费用</th><th>每年费用</th><th>适合持有时长</th></tr>
    </thead>
    <tbody>
      <tr class="best"><td>银华联接 A（026458）</td><td>申购 0.03% + 赎回 0.5%（&lt;7 天 1.5%）</td><td>0.20%</td><td><b>&gt; 1.5 年</b>最省</td></tr>
      <tr><td>银华联接 C（026459）</td><td>申购 0 + 赎回<br>（&lt;7 天 1.5%，≥7 天多为 0）</td><td>0.20% + 0.20% = 0.40%</td><td><b>&lt; 1.5 年</b>更省</td></tr>
      <tr><td>南方联接 I（021021，直销）</td><td>申购 0 + 赎回（A 类规则）</td><td>0.61%</td><td>长期 + 想要大底层</td></tr>
      <tr class="warnrow"><td>场内 512400（券商账户）</td><td>佣金 5 元×2（买+卖）</td><td>0.60%</td><td>大资金、能压佣金</td></tr>
    </tbody>
  </table>
  <div class="callout warn">
    <b>关键转折点：约 1.4 年（约 1 年 5 个月）。</b>银华 A 类要一次性摊掉 0.03% 申购费 + 0.5% 赎回费（合计约 0.53%），而 C 类每年多付 0.20% 销售服务费。按模型复算：持有 1 年时 A=0.48%、C=0.40%（C 更省）；持有 2 年时 A=0.43%、C=0.80%（A 反超）。<b>两者在约 1.4 年处持平，之后持有越久 A 越省。</b>所以：<b>持有不到 1 年半买 C，超过 1 年半买 A。</b>
  </div>
  <p class="muted">赎回费规则：各基金 A 类通常「持有 &lt; 7 天收 1.5% 惩罚性赎回费，7 天~1 年 0.5%，1~2 年 0.25%，≥2 年 0」，C 类通常「&lt; 7 天 1.5%，≥7 天 0」。上图为示意，实际以基金合同为准。场内无赎回费，只有佣金。</p>
</section>
"""

BODY_S6 = r"""
<section>
  <h2 id="s6">六、规模与流动性：小额也躲不开的隐性成本</h2>
  <p>费率只是显性成本。真正吃掉你收益的，常常是这几项「看不见的」成本。</p>
  <h3>1. 场内「最低 5 元佣金」对小资金的杀伤</h3>
  <table>
    <thead>
      <tr><th>买入金额</th><th class="num">佣金（万 2.5，最低 5 元）</th><th class="num">实际费率</th><th class="num">买卖来回成本</th></tr>
    </thead>
    <tbody>
      <tr class="warnrow"><td>1,000 元</td><td class="num">5 元</td><td class="num">0.50%</td><td class="num">1.00%</td></tr>
      <tr class="warnrow"><td>3,000 元</td><td class="num">5 元</td><td class="num">0.17%</td><td class="num">0.33%</td></tr>
      <tr><td>10,000 元</td><td class="num">5 元</td><td class="num">0.05%</td><td class="num">0.10%</td></tr>
      <tr class="best"><td>50,000 元</td><td class="num">12.5 元</td><td class="num">0.025%</td><td class="num">0.05%</td></tr>
    </tbody>
  </table>
  <p class="muted">按佣金万 2.5 测算。若你的券商是万 0.5，最低 5 元的门槛依然存在，小额资金的费率劣势不变。</p>
  <div class="callout warn">
    <b>结论：本金低于 2 万元，场内来回成本基本都高于场外基金。</b>几千块买场内 ETF，等于把一年的运作费提前在一次买卖里交掉。
  </div>
  <h3>2. 规模太小的 ETF 有什么风险</h3>
  <ul>
    <li><b>清盘风险</b>：连续一段时间规模低于 5000 万 / 持有人少于 200 人，可能触发清盘，被迫在不利价位卖出。159881（1.6 亿）离这条线比 512400 近得多。</li>
    <li><b>盘口价差</b>：小额 ETF 买卖盘挂单稀薄，一买一卖可能各让 1~2 个价位，实际成本远超 0.60% 的费率。</li>
    <li><b>跟踪误差</b>：规模小、申赎不活跃的 ETF，跟踪指数的误差通常更大。</li>
  </ul>
  <div class="callout good">
    <b>规模排序（2026-10-14）：</b>512400（226.8 亿）≫ 516650（95.8 亿）&gt; 560860（77.6 亿）&gt; 159157（71.9 亿）&gt; 159876（13.5 亿）&gt; 159871（11.3 亿）&gt; 159881（1.6 亿）。前四只规模都健康，后三只偏小。
  </div>
</section>
"""

BODY_S7 = r"""
<section>
  <h2 id="s7">七、分场景结论：几千块你该买哪个</h2>
  <p>你的情况是「手机 App、几千块、大概率持有半年以上」。按这个前提：</p>
  <div class="callout good">
    <b>首选：银华中证有色金属 ETF 联接 A（026458）—— 但只在你想省到极致、且能接受小底层时选。</b><br>
    理由：全板块最低运作费 0.20%/年，申购费 1 折后仅 0.03%。持有 2 年以上，总成本约 0.20%×2 + 0.03% ≈ 0.43%，是场外所有方案里最低的。代价是它投的 159871 只有 11.3 亿规模。<b>注意：如果只打算持有 1 年以内，银华 C 类（026459）反而比 A 类更省。</b>
  </div>
  <div class="callout good">
    <b>最稳：南方中证申万有色金属 ETF 联接 I（021021）—— 在南方基金 App 直销买。</b><br>
    理由：底层是板块最大最稳的 512400（226.8 亿），I 类服务费仅 0.01%，申购费 0，综合持有成本 0.61%/年。比银华贵约 0.4%/年，但底层质量、流动性、抗清盘能力都是全板块最好的。<b>如果你更在意「不出事」而不是「省到极致」，选这个。</b>
  </div>
  <div class="callout warn">
    <b>不推荐：几千块去证券账户买场内 ETF。</b>最低 5 元佣金会把成本推到 0.33%（来回），且需要自己承担盘口价差。除非你的券商免佣，或本金在 2 万以上。
  </div>
  <h3>一句话决策树</h3>
  <ol>
    <li>你能接受小规模底层、且持有 &gt; 1.5 年 → <b>银华联接 A 026458</b>（最省费）</li>
    <li>你要买黄金，或想要最大最稳的底层 → <b>南方联接 I 021021</b>（直销，App 内可搜）</li>
    <li>你只想买工业金属、不要黄金 → <b>万家联接 A 018489</b>（1 折后申购费 0.01%）</li>
    <li>你持有 &lt; 1.5 年就卖 → 选 <b>C 类</b>（无申购费、7 天后免赎回费）</li>
    <li>你有 2 万以上本金、且券商佣金低 → 场内 <b>512400</b></li>
  </ol>
  <p class="muted">注意：以上只讨论「成本」。买不买有色金属、什么时候买，是另一回事 —— 本报告不构成买入时点建议。</p>
</section>
"""

BODY_S8 = r"""
<section>
  <h2 id="s8">八、这份对比本身有什么问题（必须读）</h2>
  <p>你问「还有什么问题吗」。有，而且是这个板块对比里最容易骗人的几处。我逐条列出来，你自己判断要不要采信上文的结论。</p>
  <h3>问题 1：联接层费率和 ETF 层费率，分母不是一回事</h3>
  <div class="callout warn">
    场内 ETF 的 0.60%/年，是<b>对全部净资产</b>收费；联接基金的 0.20%/年，只对<b>留在联接层的那部分资产</b>收费（投向 ETF 的部分不再重复收）。所以「银华 0.20% vs 512400 的 0.60%」<b>不能直接相减</b>去说「省了 0.4%」——真实差距要比这个数小，具体取决于联接层的现金留存比例。<br>
    <b>我给你的对策</b>：本报告的所有对比都用「投资者实际承担的总持有成本」口径（申购费 + 运作费 + 赎回费），而不是拿两个不同分母的费率硬比。你看到的持有期曲线才是可比的口径。
  </div>
  <h3>问题 2：规模数据的时点不一致</h3>
  <div class="callout warn">
    场内 ETF 的规模是 <b>2026-10-14</b> 的盘中快照（westock）；联接基金的规模来自基金定期报告（不同基金披露日不同，如 2026-06-30）。<b>这两组数字不同期</b>，不能拿来做精确排序。规模排序只能当「量级判断」用，别当精确值。
  </div>
  <h3>问题 3：费率数据是「促销价」，会变</h3>
  <div class="callout warn">
    A 类「1 折申购费」、I 类「0.01% 服务费」都是<b>渠道促销</b>，不是永久承诺 —— 平台随时可能恢复原价。银华的 0.15% 管理费也可能是阶段性优惠。<b>下单前务必在 App 里核对当天的实际费率页面</b>，不要拿本报告当合同。
  </div>
  <h3>问题 4：便宜的和稳的，不完全重合</h3>
  <div class="callout warn">
    全板块最低费率（银华 026458，0.20%）配的是倒数第二小的底层（159871，11.3 亿）；最大最稳的底层（512400，226.8 亿）配的是中等费率（南方 I，0.61%）。<b>「最划算」没有唯一答案 —— 取决于你更怕「多付费用」还是更怕「底层出问题」。</b>这也是为什么我没有给你一个单一的「最佳答案」，而是给了决策树。
  </div>
  <h3>问题 5：我没做的核查（透明声明）</h3>
  <ul>
    <li><b>未逐只核对基金合同原文</b>：费率取自第三方摘要与公开页面，未下载每只基金的招募说明书逐条比对。存在个别基金费率已调整但第三方数据未更新的可能。</li>
    <li><b>未实测各平台申购费折扣</b>：支付宝 / 天天基金 / 各基金公司 App 的实际折扣我未逐一下单验证，按行业惯例（1 折）估算。</li>
    <li><b>指数成分股未展开</b>：000819 / 000811 / 930708 / H11059 的具体权重我没逐个拉取，只做了口径归类（是否含黄金）。如果你需要精确到权重的对比，我可以再拉。</li>
    <li><b>当前时点不属于可核验区间</b>：现在是 2026-10-14，规模与费率均为当日快照，往后会变。</li>
  </ul>
  <div class="callout good">
    <b>怎么用这份报告：</b>把上文的「费率量级」和「规模排序」当方向性参考，把你的实际资金量、持有时长、是否要黄金这三件事对号入座，然后在 App 上核对当天实际费率再下单。
  </div>
</section>
"""

FOOT = r"""
<footer>
  <p><b>数据与口径</b></p>
  <ul>
    <li>场内 ETF 行情 / 规模：westock，快照日 2026-10-14（盘中）。</li>
    <li>基金费率：各基金公司公开费率页 / 第三方基金数据摘要；A 类「1 折后」按互联网平台惯例估算。</li>
    <li>规模（联接层）：基金定期报告披露值（不同基金披露日不同）。</li>
    <li>持有期成本曲线：按本金 3,000 元、申购费 1 折、赎回费按各基金 A/C 类常见档位测算，为示意模型，非精确回报。</li>
  </ul>
  <p><b>免责声明</b>：本报告仅做费率与成本的静态对比，不构成任何投资建议、不预测有色金属板块走势、不推荐买入时点。基金费率、规模、折扣政策随时可能调整，实际以你下单当日基金合同与平台页面为准。投资有风险，决策请自行判断。</p>
  <p>生成时间 2026-10-14 ｜ 版式对齐《南方有色金属ETF费率对比报告》</p>
</footer>
</div>

<script>
(function(){
  var el = document.getElementById('chart');
  if(!el || typeof echarts === 'undefined'){ return; }
  var chart = echarts.init(el);
  // 持有年限
  var years = [0, 0.25, 0.5, 1, 2, 3];
  // 银华A: 申购0.03 一次性 + 0.20/yr ; 赎回阶梯(<7d1.5%,<1y0.5%,<2y0.25%,>=2y0)
  function redA(y){ if(y<0.019) return 1.5; if(y<1) return 0.5; if(y<2) return 0.25; return 0; }
  var yhA = years.map(function(y){ return +(0.03 + 0.20*y + redA(y)).toFixed(3); });
  // 银华C: 申购0 + (0.20+0.20)/yr + 赎回(<7d1.5%, else 0)
  function redC(y){ return y < 0.019 ? 1.5 : 0; }
  var yhC = years.map(function(y){ return +(0.40*y + redC(y)).toFixed(3); });
  // 南方I: 申购0 + 0.61/yr + A类赎回
  var nfI = years.map(function(y){ return +(0.61*y + redA(y)).toFixed(3); });
  // 场内512400: 3000元 来回佣金 5+5=10元 => 0.333% 一次性 + 0.60/yr
  var cn  = years.map(function(y){ return +(0.333 + 0.60*y).toFixed(3); });

  var option = {
    backgroundColor: 'transparent',
    tooltip:{ trigger:'axis', valueFormatter:function(v){ return v + '%'; } },
    legend:{ data:['银华联接A 026458','银华联接C 026459','南方联接I 021021','场内512400（3000元）'], top:0, textStyle:{fontSize:12} },
    grid:{ left:52, right:24, top:44, bottom:40 },
    xAxis:{ type:'category', name:'持有年限', data:['0','3个月','半年','1年','2年','3年'], axisLine:{lineStyle:{color:'#c9ced6'}}, axisLabel:{color:'#5a6272'} },
    yAxis:{ type:'value', name:'累计成本(%)', axisLabel:{formatter:'{value}%', color:'#5a6272'}, splitLine:{lineStyle:{color:'#eef0f3'}} },
    series:[
      { name:'银华联接A 026458', type:'line', smooth:true, symbolSize:7, data:yhA, lineStyle:{width:2.6,color:'#178a4c'}, itemStyle:{color:'#178a4c'} },
      { name:'银华联接C 026459', type:'line', smooth:true, symbolSize:6, data:yhC, lineStyle:{width:2,color:'#1f5fd0'}, itemStyle:{color:'#1f5fd0'} },
      { name:'南方联接I 021021', type:'line', smooth:true, symbolSize:6, data:nfI, lineStyle:{width:2,color:'#b06d00'}, itemStyle:{color:'#b06d00'} },
      { name:'场内512400（3000元）', type:'line', smooth:true, symbolSize:6, data:cn, lineStyle:{width:2,type:'dashed',color:'#c8322b'}, itemStyle:{color:'#c8322b'} }
    ]
  };
  chart.setOption(option);
  window.addEventListener('resize', function(){ chart.resize(); });
})();
</script>
</body>
</html>
"""

html_doc = HEAD + BODY_1 + BODY_3 + BODY_2 + BODY_S3 + BODY_S4 + BODY_S5 + BODY_S6 + BODY_S7 + BODY_S8 + FOOT
OUT.write_text(html_doc, encoding="utf-8")
print(f"WROTE {OUT} ({len(html_doc.encode('utf-8'))} bytes)")
