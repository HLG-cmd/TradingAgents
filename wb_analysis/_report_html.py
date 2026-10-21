# lifecycle: reusable
# created: 2026-10-10
"""单页自包含 HTML 报告渲染器（吸收上游 v0.6.0 设计）

特点：
1. 零外部依赖：纯内联 CSS、无外部 JS/字体 CDN、受 Content-Security-Policy 保护。
2. 响应式与自适应：自动适配深色/浅色模式（prefers-color-scheme），完美支持手机、桌面与打印（print CSS）。
3. 现代化投研排版：侧边/顶部多角色目录跳转、表头元信息快照、评级徽章色调映射。
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path
from wb_analysis import _clock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from markdown_it import MarkdownIt
    _HAS_MARKDOWN_IT = True
except ImportError:
    _HAS_MARKDOWN_IT = False


_CSS = """
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  --bg-page: #f8fafc;
  --bg-card: #ffffff;
  --text-main: #0f172a;
  --text-muted: #64748b;
  --border-rule: #e2e8f0;
  --accent: #2563eb;
  --accent-light: #eff6ff;
  --color-buy: #059669;
  --color-hold: #d97706;
  --color-sell: #dc2626;
  --code-bg: #f1f5f9;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg-page: #0b0f19;
    --bg-card: #131b2e;
    --text-main: #f1f5f9;
    --text-muted: #94a3b8;
    --border-rule: #26334d;
    --accent: #3b82f6;
    --accent-light: #172554;
    --color-buy: #10b981;
    --color-hold: #f59e0b;
    --color-sell: #ef4444;
    --code-bg: #1e293b;
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-page);
  color: var(--text-main);
  line-height: 1.6;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
}

.container {
  max-width: 1080px;
  margin: 2rem auto;
  padding: 0 1.5rem;
}

.report-header {
  background: var(--bg-card);
  border: 1px solid var(--border-rule);
  border-radius: 12px;
  padding: 2.5rem;
  margin-bottom: 2rem;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-rule);
  padding-bottom: 1.5rem;
}

.ticker-title {
  font-size: 2.25rem;
  font-weight: 800;
  letter-spacing: -0.025em;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.badge {
  display: inline-block;
  padding: 0.35rem 0.85rem;
  border-radius: 9999px;
  font-size: 0.875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.badge-buy { background: rgba(5, 150, 105, 0.15); color: var(--color-buy); border: 1px solid var(--color-buy); }
.badge-hold { background: rgba(217, 119, 6, 0.15); color: var(--color-hold); border: 1px solid var(--color-hold); }
.badge-sell { background: rgba(220, 38, 38, 0.15); color: var(--color-sell); border: 1px solid var(--color-sell); }
.badge-neutral { background: var(--accent-light); color: var(--accent); border: 1px solid var(--accent); }

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.25rem;
  font-size: 0.9rem;
}

.meta-item dt { color: var(--text-muted); font-size: 0.8rem; font-weight: 600; text-transform: uppercase; margin-bottom: 0.25rem; }
.meta-item dd { font-weight: 600; color: var(--text-main); }

.nav-index {
  background: var(--bg-card);
  border: 1px solid var(--border-rule);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 2rem;
}

.nav-index h3 {
  font-size: 1rem;
  margin-bottom: 1rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.nav-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  list-style: none;
}

.nav-pills a {
  display: inline-block;
  padding: 0.4rem 0.8rem;
  background: var(--bg-page);
  border: 1px solid var(--border-rule);
  border-radius: 6px;
  color: var(--text-main);
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.15s ease;
}

.nav-pills a:hover {
  background: var(--accent);
  color: #ffffff;
  border-color: var(--accent);
}

.section-card {
  background: var(--bg-card);
  border: 1px solid var(--border-rule);
  border-radius: 12px;
  padding: 2rem 2.5rem;
  margin-bottom: 2rem;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
}

.section-card h2 {
  font-size: 1.5rem;
  font-weight: 700;
  margin-top: 1rem;
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 2px solid var(--border-rule);
  color: var(--text-main);
}

.section-card h3 {
  font-size: 1.25rem;
  font-weight: 600;
  margin-top: 2rem;
  margin-bottom: 1rem;
  color: var(--accent);
}

.section-card h4 {
  font-size: 1.05rem;
  font-weight: 600;
  margin-top: 1.5rem;
  margin-bottom: 0.75rem;
}

.section-card p, .section-card ul, .section-card ol {
  margin-bottom: 1.1rem;
}

.section-card ul, .section-card ol {
  padding-left: 1.5rem;
}

.section-card li {
  margin-bottom: 0.35rem;
}

.section-card blockquote {
  border-left: 4px solid var(--accent);
  background: var(--accent-light);
  padding: 0.75rem 1.25rem;
  border-radius: 0 8px 8px 0;
  margin: 1.25rem 0;
  color: var(--text-main);
}

.section-card pre {
  background: var(--code-bg);
  padding: 1rem 1.25rem;
  border-radius: 8px;
  overflow-x: auto;
  margin: 1.25rem 0;
  font-family: var(--font-mono);
  font-size: 0.88rem;
  border: 1px solid var(--border-rule);
}

.section-card code {
  font-family: var(--font-mono);
  background: var(--code-bg);
  padding: 0.15rem 0.35rem;
  border-radius: 4px;
  font-size: 0.9em;
}

.section-card table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5rem 0;
  font-size: 0.88rem;
}

.section-card th, .section-card td {
  padding: 0.65rem 0.85rem;
  border: 1px solid var(--border-rule);
  text-align: left;
}

.section-card th {
  background: var(--code-bg);
  font-weight: 600;
}

.section-card hr {
  border: 0;
  border-top: 1px solid var(--border-rule);
  margin: 2rem 0;
}

footer {
  text-align: center;
  padding: 2.5rem 0;
  color: var(--text-muted);
  font-size: 0.85rem;
  border-top: 1px solid var(--border-rule);
}

@media print {
  body { background: #ffffff; color: #000000; font-size: 11pt; }
  .container { max-width: 100%; padding: 0; margin: 0; }
  .report-header, .section-card { box-shadow: none; border: 1px solid #ccc; padding: 1.5rem; page-break-inside: avoid; }
  .nav-index { display: none; }
}
"""


def _get_markdown_parser():
    if not _HAS_MARKDOWN_IT:
        return None
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    return md


def render_markdown(text: str) -> str:
    md = _get_markdown_parser()
    if md is not None:
        return md.render(text)
    # 极简 fallback：段落换行与粗体转义
    safe = html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\*(.+?)\*", r"<em>\1</em>", safe)
    safe = re.sub(r"`(.+?)`", r"<code>\1</code>", safe)
    paragraphs = [f"<p>{p.strip()}</p>" for p in safe.split("\n\n") if p.strip()]
    return "\n".join(paragraphs)


def render_html_report(data: dict) -> str:
    """把报告树字典渲染为自包含的美观单页 HTML。"""
    ticker = data.get("ticker", "UNKNOWN")
    as_of = data.get("as_of", "")
    ratings = data.get("ratings") or {}
    pm_rating = ratings.get("portfolio_manager") or ratings.get("research_manager") or "Hold"

    # 确定徽章色彩
    badge_cls = "badge-neutral"
    u = pm_rating.upper()
    if "BUY" in u or "OVERWEIGHT" in u:
        badge_cls = "badge-buy"
    elif "SELL" in u or "UNDERWEIGHT" in u:
        badge_cls = "badge-sell"
    elif "HOLD" in u:
        badge_cls = "badge-hold"

    # 组织各分析师章节
    sections = [
        ("1. 分析师研判 (Analysts)", [
            ("市场量化 (Market)", (data.get("analysts") or {}).get("market", "")),
            ("情绪指标 (Sentiment)", (data.get("analysts") or {}).get("sentiment", "")),
            ("新闻事件 (News)", (data.get("analysts") or {}).get("news", "")),
            ("基本面分析 (Fundamentals)", (data.get("analysts") or {}).get("fundamentals", "")),
        ]),
        ("2. 多空辩论 (Research Debate)", [
            ("看多立场 (Bull)", (data.get("research") or {}).get("bull", "")),
            ("看空立场 (Bear)", (data.get("research") or {}).get("bear", "")),
            ("研究经理 (Research Manager)", (data.get("research") or {}).get("manager", "")),
        ]),
        ("3. 交易计划 (Trading Strategy)", [
            ("执行交易员 (Trader)", (data.get("trading") or {}).get("trader", "")),
        ]),
        ("4. 风险评估与终局决策 (Risk & Decision)", [
            ("激进风控 (Aggressive Risk)", (data.get("risk") or {}).get("aggressive", "")),
            ("保守风控 (Conservative Risk)", (data.get("risk") or {}).get("conservative", "")),
            ("中性风控 (Neutral Risk)", (data.get("risk") or {}).get("neutral", "")),
            ("投资组合经理 (Portfolio Manager)", (data.get("risk") or {}).get("portfolio_manager", "")),
        ]),
    ]

    # 构建导航目录与正文
    nav_links = []
    body_sections = []
    sec_idx = 1

    for group_title, items in sections:
        body_parts = [f'<div class="section-card" id="group-{sec_idx}">', f'<h2>{html.escape(group_title)}</h2>']
        for item_title, item_body in items:
            sub_id = f"sec-{sec_idx}-{len(body_parts)}"
            nav_links.append(f'<li><a href="#{sub_id}">{html.escape(item_title)}</a></li>')
            body_parts.append(f'<h3 id="{sub_id}">{html.escape(item_title)}</h3>')
            body_parts.append(render_markdown(item_body.strip() or "*暂无正文*"))
        body_parts.append('</div>')
        body_sections.append("\n".join(body_parts))
        sec_idx += 1

    generated_time = _clock.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
  <title>{html.escape(ticker)} 深度投研决策报告 ({html.escape(as_of)})</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="container">
    <header class="report-header">
      <div class="header-top">
        <div class="ticker-title">
          <span>{html.escape(ticker)}</span>
          <span class="badge {badge_cls}">{html.escape(pm_rating)}</span>
        </div>
        <div style="font-size: 0.9rem; color: var(--text-muted);">
          基准日期：<strong>{html.escape(as_of or "—")}</strong>
        </div>
      </div>
      <dl class="meta-grid">
        <div class="meta-item">
          <dt>组合经理决策</dt>
          <dd>{html.escape(ratings.get('portfolio_manager', '—'))}</dd>
        </div>
        <div class="meta-item">
          <dt>交易员建议</dt>
          <dd>{html.escape(ratings.get('trader_action', '—'))}</dd>
        </div>
        <div class="meta-item">
          <dt>研究经理建议</dt>
          <dd>{html.escape(ratings.get('research_manager', '—'))}</dd>
        </div>
        <div class="meta-item">
          <dt>报告生成时间</dt>
          <dd>{html.escape(generated_time)}</dd>
        </div>
      </dl>
    </header>

    <nav class="nav-index">
      <h3>快捷导航 / Quick Navigation</h3>
      <ul class="nav-pills">
        {"".join(nav_links)}
      </ul>
    </nav>

    <main>
      {"".join(body_sections)}
    </main>

    <footer>
      TradingAgents · 深度量化与基本面投研智能体系统 · 离线全量审计报告
    </footer>
  </div>
</body>
</html>
"""
