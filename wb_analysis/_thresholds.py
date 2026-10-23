# lifecycle: reusable
# created: 2026-10-10
# usage: from wb_analysis._thresholds import MAX_QUOTE_AGE_DAYS   （库；被采集器/审计器/探针 import，不单独运行）
"""跨工具共用的**判据常量**（数值阈值、市场时钟）—— 定义一次，多处引用。

## 为什么单独建这个模块（2026-10-10，全项目扫描发现）

`MAX_QUOTE_AGE_DAYS = 5` 曾被写在**三个文件里各一份**：

| 位置 | 用途 |
|---|---|
| `collect_index.py:137` | 采集时按它决定「哪些报价算新鲜」，并把值写进证据包元数据 |
| `_probe_option_dual_quote.py:21` | 探针按它判定「有双边报价 ∩ 成交新鲜」的交集 |
| `_audit_gaps.py:206/230` | 审计器按它把缺口分类为「A 上游真缺」还是「B 阈值误伤」 |

`_audit_gaps.py` 的注释当时写着「与 `collect_index.py` 的 `MAX_QUOTE_AGE_DAYS` 对齐」——
**靠注释维系的一致性不是一致性**。改一处忘一处，审计器与采集器就会对同一批报价
给出**相反结论**；而 `_audit_gaps.py` 的 docstring 记录的第一次事故正是这个：
把 170 张陈旧 60+ 天的报价误判成「B 类阈值误伤」，进而得出「数据可得、是闸门设错」
的错误结论（真相是 A 类：盘前采集，上游此刻确实不提供可用报价）。

⚠️ **为什么不直接 `import collect_index`**：`collect_index.py` 在**模块级**执行
`os.chdir(PROJECT_ROOT)` 与 `load_dotenv(PROJECT_ROOT / ".env")` —— 这两个副作用会
**改变导入方进程的工作目录与环境变量**。阈值因此必须住在**无副作用**的模块里。

⇒ 新增此类跨工具阈值时**只改这里**；同值判据不得在消费方再写一遍
（`_selftest.py` 有「契约常量不得用字面量重写」的检测器，思路相同）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只为字符串注解提供名字，运行时不导入
    import datetime


# ─────────────────────────────────────────────────────────────────────────────
# 期权报价新鲜度
# ─────────────────────────────────────────────────────────────────────────────

#: 期权「报价新鲜」的最大天数：`lastTradeDate` 距今 ≤ 此值才算**可用报价**。
#:
#: ⚠️ 保留为 5 天是**刻意的**（2026-09-17 复核）：它能正确拦住盘前/盘后采集到的
#: 陈旧快照 —— 那类快照 `bid`/`ask` 都 >0、格式完全合法，但 `lastTradeDate`
#: 已过时数周。放行条件是「新鲜样本 > 0」而非「放宽天数」，盘前场景自然为 0。
#:
#: ⚠️ 改此值会让采集器、探针、缺口审计器**同时**改变判定口径 —— 这正是目的：
#: 三处必须同值，不允许各自微调。
MAX_QUOTE_AGE_DAYS: float = 5.0

# ─────────────────────────────────────────────────────────────────────────────
# 市场时钟
# ─────────────────────────────────────────────────────────────────────────────

#: 美股所在时区的 IANA 名。凡判「现在是不是美东盘中 / 是不是当日」一律用它换算，
#: **不得用本机时区**，也不得写 `timezone(timedelta(hours=-4))` ——
#: UTC−4 只在夏令时（EDT）成立，冬季（EST）是 UTC−5，硬编码会在换季时静默错一小时。
#: （同族教训见本项目铁律 34：缓存按本机时区判「当日」⇒ 跨时区分析时永不刷新。）
MARKET_TZ_NAME: str = "America/New_York"

#: 常规交易时段边界（美东小时，**含起点不含终点**）：09:30 – 16:00。
#:
#: ⚠️ 为什么这条边界是**全局判据**而不是采集器的局部逻辑：
#: 它同时决定「期权走哪个源」（`option_source_decision`）与「报价算不算新鲜」。
#: 两处若各写一份，改一处忘一处就会出现「切了源但仍按旧口径过滤」这类静默错配。
REGULAR_SESSION_OPEN_HOUR: float = 9.5      # 09:30 美东
REGULAR_SESSION_CLOSE_HOUR: float = 16.0    # 16:00 美东

#: 美股**公休日**（NYSE 休市，2024–2027）。周末另由 `weekday() >= 5` 判定。
#:
#: ⚠️ 为什么必须内置：`market_session_phase` 原先只排除周末，于是**工作日休市日**
#:   会被判成 `in_session` ⇒ `option_source_decision` 说「用 yfinance 主源」，
#:   可那天市场根本没开，yfinance 只会返回残留挂单。
#:
#: ⚠️ 每年需按 NYSE 日历续补（本表覆盖到 2027 年底）。规则：元旦 / MLK（1 月第 3 个
#:   周一）/ 总统日（2 月第 3 个周一）/ 耶稣受难日 / 阵亡将士纪念日（5 月最后一个
#:   周一）/ 六月节 / 独立日 / 劳动节（9 月第 1 个周一）/ 感恩节（11 月第 4 个周四）/
#:   圣诞节；落在周六则前移到周五、落在周日则后移到周一。
#: ⚠️ **不含半日市**（如感恩节次日下午 1 点收盘）—— 那类日子仍按常规 16:00 判定。
US_MARKET_HOLIDAYS: frozenset[str] = frozenset({
    # 2024（10 天）
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27",
    "2024-06-19", "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
    # 2025（10 天）
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026（10 天）
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027（10 天）
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
})


def market_session_phase(now: datetime.datetime | None = None) -> str:
    """返回美股当前所处时段：`in_session` / `pre_market` / `after_hours` / `closed_day`。

    `now` 为 `None` 时取当前美东时间；**传入 aware datetime 可注入任意时点做测试**
    （期权时点分支此前无法被测试，正是因为它把 `_clock.now()` 写死在函数体里）。
    """
    import datetime as _dt
    import zoneinfo

    if now is None:
        now = _dt.datetime.now(zoneinfo.ZoneInfo(MARKET_TZ_NAME))
    elif now.tzinfo is None:
        # 裸 datetime 一律按美东解释，不做静默的 UTC 假设
        now = now.replace(tzinfo=zoneinfo.ZoneInfo(MARKET_TZ_NAME))
    else:
        now = now.astimezone(zoneinfo.ZoneInfo(MARKET_TZ_NAME))

    if now.weekday() >= 5 or now.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS:
        return "closed_day"
    h = now.hour + now.minute / 60.0
    if h < REGULAR_SESSION_OPEN_HOUR:
        return "pre_market"
    if h < REGULAR_SESSION_CLOSE_HOUR:
        return "in_session"
    return "after_hours"


def option_source_decision(now: datetime.datetime | None = None) -> tuple[bool, str]:
    """判定期权该走哪个源：返回 `(是否切 CBOE 官方延迟报价, 人读说明)`。

    **盘中走 yfinance 主源**（实时、已验证新鲜，零回归）；
    **非盘中走 CBOE 官方延迟报价**（拿的是**上一时段收盘快照**，非实时报价）。

    为什么非盘中也要给数据而不是判缺口：yfinance 在盘前/盘后只返回**残留挂单**
    （`bid`/`ask` 格式合法但 `lastTradeDate` 陈旧数周），而 CBOE 是**做市商报价链**，
    不依赖「该合约当天有没有成交」⇒ 盘前仍能重建完整期限结构。

    ⚠️ 但**不是「解除时间限制」**：CBOE 的延长时段（GTH 20:15–09:25）仅覆盖
    SPX / SPXW / XSP，**不含股票与 ETF 期权** ⇒ 盘前拿到的成交**必然止于上一交易日**。
    这是市场本身没有成交，不是接口缺陷。
    """
    phase = market_session_phase(now)
    import datetime as _dt
    import zoneinfo

    if now is None:
        now = _dt.datetime.now(zoneinfo.ZoneInfo(MARKET_TZ_NAME))
    elif now.tzinfo is None:
        now = now.replace(tzinfo=zoneinfo.ZoneInfo(MARKET_TZ_NAME))
    else:
        now = now.astimezone(zoneinfo.ZoneInfo(MARKET_TZ_NAME))

    stamp = f"{now:%Y-%m-%d %H:%M}"
    if phase == "in_session":
        return False, f"{stamp} 美东（常规交易时段）⇒ 用 yfinance 主源"
    label = {"pre_market": "盘前", "after_hours": "盘后", "closed_day": "非交易日"}[phase]
    return True, (
        f"{stamp} 美东（{label}）⇒ 切 CBOE 官方延迟报价"
        f"（拿的是**上一时段收盘快照**，非实时报价）"
    )

# ─────────────────────────────────────────────────────────────────────────────
# 期权期限结构
# ─────────────────────────────────────────────────────────────────────────────

#: ATM IV 期限曲线的**局部驼峰**判据（单位：百分点）。
#:
#: 用途：识别「期权市场把事件风险定价在某一段期限里」。判据是**同时**高出左右相邻
#: 两档 ≥ 本值 —— 而不是与端点曲线比斜率。
#:
#: 为什么不能用端点：实测 GOOG（基准 2026-10-11）ATM IV 逐档为
#: `4天 36.59 → 11天 31.15 → 32天 36.29 → 95天 32.08`，
#: 端点斜率只有 −1.98pp（看起来是「正常的正向结构」），而 32 天处比左右相邻档
#: 高 **4.2~5.1pp** —— 那才是真正的信号（与 Alphabet Q3 财报时点吻合）。
#: 端点本身含噪声（本例近端 4 天反而比 11 天高 5.4pp），故只能靠「高于相邻两档」定位。
#:
#: 取值依据（铁律 10「设阈值先测三个数」）：本曲线的正常逐档波动 ~5pp，
#: 而相邻档之间的**结构噪声**约 ≤1.5pp ⇒ 取 2.0pp 落在两者之间。
HUMP_MIN_PP: float = 2.0
