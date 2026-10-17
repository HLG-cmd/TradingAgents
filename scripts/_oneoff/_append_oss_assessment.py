# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_append_oss_assessment.py
"""把开源准备度评估追加进当日记忆（避免 heredoc 转义问题）。"""
from __future__ import annotations

from pathlib import Path

MEM = Path(__file__).resolve().parents[2] / ".workbuddy-ai" / "memory" / "2026-10-16.md"

BS = chr(92)  # 反斜杠，避免源码里的转义歧义

ADD = """
---

## 开源准备度评估（用户：「这个项目到什么程度可以放 GitHub 开源」）

### 一、扫描结果（实测，399 个已跟踪文件）

| 维度 | 结果 | 判定 |
|---|---|---|
| **凭据泄露** | **0 处**（API key / token / 私钥 / 密码全无） | ✅ 干净 |
| `.env` 是否被跟踪 | **未跟踪**，且 `.gitignore` 已覆盖 | ✅ 安全 |
| `reports/`（含分析结论） | **未跟踪**（0 个） | ✅ 不入库 |
| 已跟踪大文件（>1MB） | **无** | ✅ |
| 许可证 | Apache 2.0（与上游一致） | ✅ |
| 个人信息 | 11 处命中，**逐条甄别后 9 处为占位符/说明文字** | ⚠️ 见下 |
| 内部信息（内网 IP / 私有仓库） | 0 处 | ✅ |

**11 处「个人信息」逐条甄别**：
- `your@email.com` / `admin@example.com` / `someone@qq.com` —— **占位符与文档示例**
  （在 `edgar_fundamentals.py` 的 docstring 里教用户怎么配），**保留**；
- `PCF@29.73` / `ROE@18.41` —— **正则误报**（`指标@分位` 被当成邮箱），**保留**；
- 本机 Windows 用户目录 ×2 —— 在 `collect_a_etf.py` / `collect_hk_index.py` 的注释里，
  内容是「**此前硬编码已改为统一解析**」的说明 ⇒ 只是提到、非现行配置。
  ⚠️ 但确实暴露了本机用户名，**建议改写为占位形式**；
- 本机 Unix 用户目录 ×2 —— 在 `.workbuddy-ai/memory/` 日志里（跨平台路径讨论），同上建议脱敏。

### 二、发现的**阻断项**（不放 GitHub 的硬理由）

| # | 阻断项 | 实测 | 后果 |
|---|---|---|---|
| **B1** | **`origin` 指向上游仓库** | `git remote -v` → `TauricResearch/TradingAgents.git` | **`git push` 会试图推到别人的仓库**（无权限则失败；有权限更糟）⇒ 必须改 remote 或新建仓库 |
| **B2** | **55 个已跟踪文件磁盘不存在** | 旧目录 `.workbuddy/` 30 个（改名遗留的幽灵条目） | 别人克隆后出现「已删除未提交」的脏状态，`git status` 一片红 |
| **B3** | **230 项未提交改动** | 111 未跟踪 / 64 修改 / 55 删除 | 现在推上去的是**旧快照**，不含今天的修复与新增测试 |
| **B4** | **`.box-agent/` 与 `.box-agent-scratch/` 未被忽略** | 6 + 35 个文件，含**会话 ID / task registry** | 一旦 `git add .` 就会**把 agent 运行痕迹提交上去**（含 session_id、内部路径） |

### 三、**建议项**（不阻断，但影响开源质量）

| # | 项 | 现状 |
|---|---|---|
| S1 | `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `SECURITY.md` | 全部缺失 |
| S2 | `.env.example` | **缺失** —— 没有它，别人不知道该配哪些环境变量（`SEC_USER_AGENT` 是 EDGAR 必需项） |
| S3 | `.workbuddy-ai/memory/` 是否开源 | 已跟踪 43 个文件 / 1.78 MB，含**个人工作日志**（持仓/资金/自动化习惯类词出现 38 次）⇒ **需用户决定**：开源（展示「经验沉淀」方法论）／保留但脱敏／移出仓库 |
| S4 | README 的「怎么跑」 | 本轮已补四条链路，但**「clone 到别人机器」路径未验证**（本机专用 `westock.exe`、Windows 专用 `.venv/Scripts/python.exe` 写法） |

### 四、结论（给用户的答复口径）
**代码质量与安全已达标**（凭据 0 泄露、许可证合规、无大文件、测试 868 通过、体检 12 PASS）。
**但有 4 个阻断项必须先处理**，其中 **B1（remote 指向上游）最危险** ——
照现在的配置 `git push` 会推错地方。

⇒ **「到什么程度可以开源」= 处理完 B1–B4 + 决定 S3 之后即可**（S1/S2 建议但不阻断）。
⚠️ **本轮只做扫描与评估，未改动任何仓库配置**（改 remote / 提交 / 加 .gitignore 均需用户授权）。
"""


def main() -> int:
    t = MEM.read_text(encoding="utf-8")
    MEM.write_text(t + ADD, encoding="utf-8", newline="\n")
    print(f"memory updated -> {len(t + ADD)} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
