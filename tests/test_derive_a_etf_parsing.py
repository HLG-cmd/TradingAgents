# lifecycle: test
"""`_derive_a_etf.py` 解析层回归测试。

## 为什么测这一层
`_derive_a_etf.py` 是 A 股 ETF 报告的**算术前提**——均线、布林、%B、ATR、HV、
累计收益、关键价位全部由它产出，12 个角色文件都引用 `0_derived.md`
（文档里明写「可直接引用」）。

它的头部注释自己记录了两次踩坑：
  1. **按 markdown 表格解析**（实际证据包 §1/§2 是代码块里的 `key: value` 行）
     ⇒ 全部解出空值却仍报「成功」——正是项目禁止的**静默失败**。
  2. `§2.1`（均线/布林）与 `§2.2`（MACD/KDJ/RSI）是**两个独立代码块**，
     要求「单块同时含 MA_5 与 RSI_6」会**永远解空**。

后者正是典型「不报错、只是悄悄不出数」的缺陷，只能靠测试抓。
本文件锁定解析层的三个契约：
  · `first_num`     —— 从「1.424 (偏离度: +0.56%)」这类混合串里取**第一个**数值
  · `kv_from_block` —— 容忍 `- ` 前缀与中英文冒号
  · `find_kv`  —— **跨块合并**必须可行（否则永远解空）
并显式验证「格式漂移会被检出」（字段计数为 0 时应能被上层判为不可信）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._derive_a_etf import (  # noqa: E402
    find_kv,
    find_table,
    first_num,
    kv_from_block,
    parse_code_blocks,
    parse_tables,
)


@pytest.mark.unit
class TestFirstNum:
    """`first_num` 取**第一个**数值 token —— 顺序错了会把偏离度当成指标值。"""

    @pytest.mark.parametrize("raw,expected", [
        ("1.424 (偏离度: +0.56%)", 1.424),   # 关键：取 1.424 而不是 0.56
        ("1.435", 1.435),
        ("  1.424  ", 1.424),
        ("-0.97%", -0.97),
        ("+0.08%", 0.08),
        ("1,234.5", 1234.5),                 # 千分位
        ("1.4464", 1.4464),
    ])
    def test_first_number_wins(self, raw, expected):
        assert first_num(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["abc", "", None, "无"])
    def test_non_numeric_returns_default(self, raw):
        assert first_num(raw) is None
        assert first_num(raw, default=-1) == -1

    def test_numeric_passthrough(self):
        assert first_num(1.5) == 1.5
        assert first_num(2) == 2.0

    def test_value_with_parens_keeps_first_number(self):
        """值形如 `1.436 (偏离度: -0.07%)` 时必须取 1.436（第一个数），而不是 -0.07。"""
        assert first_num("1.436 (偏离度: -0.07%)") == pytest.approx(1.436)

    def test_label_with_digits_breaks_first_num_documented_invariant(self):
        """★ 不变量：**调用方必须先剥离标签**再交给 first_num。

        反例（本测试锁定其行为）：`first_num("MA_5: 1.436 …")` 会取到标签里的 **5.0**，
        因为 `NUM_RE.search` 匹配到的是 `MA_5` 的 `5`。

        为什么这不是「随便写的怪用例」：
          · `_derive_a_etf.build()` 走的是 `first_num(tech.get(name))`，而 `tech` 来自
            `kv_from_block()` —— **标签已被剥离**，所以生产路径安全；
          · 但若将来有人把「整行」直接喂给 first_num（例如图省事解析新通道），
            就会静默取到标签数字，产出**看起来正常实则错误**的指标值。
          ⇒ 此用例把该不变量固化下来：first_num 只负责「取第一个数」，
             **不负责识别哪个数是值**。剥离标签是调用方的责任。
        """
        assert first_num("MA_5: 1.436 (偏离度: -0.07%)") == 5.0
        assert first_num("MA_250: 1.4338") == 250.0
        # 正确用法对照：先剥标签
        from wb_analysis._derive_a_etf import kv_from_block
        kv = kv_from_block("MA_5: 1.436 (偏离度: -0.07%)")
        assert first_num(kv["MA_5"]) == pytest.approx(1.436)


@pytest.mark.unit
class TestKvFromBlock:
    """容忍 `- ` 前缀与中英文冒号 —— 证据包的两种写法都存在。"""

    def test_bullet_prefix_and_colon(self):
        blk = "\n".join([
            "收盘价: 1.435",
            "  - 上轨: 1.4464",
            "  - 中轨: 1.4093",
            "  - 下轨: 1.3723",
        ])
        kv = kv_from_block(blk)
        assert kv["收盘价"] == "1.435"
        assert kv["上轨"] == "1.4464"
        assert kv["中轨"] == "1.4093"
        assert kv["下轨"] == "1.3723"

    def test_fullwidth_colon(self):
        assert kv_from_block("收盘价：1.435")["收盘价"] == "1.435"

    def test_value_keeps_trailing_parenthetical(self):
        """值里带括号说明时应整段保留（由 first_num 负责取数）。"""
        kv = kv_from_block("MA_5:   1.436 (偏离度: -0.07%)")
        assert kv["MA_5"].startswith("1.436")

    def test_blank_and_noise_lines_ignored(self):
        kv = kv_from_block("标题行无冒号\n\n   \n上轨: 1.4464")
        assert kv == {"上轨": "1.4464"}


@pytest.mark.unit
class TestFindKvAcrossBlocks:
    """★ 核心回归：均线与动量指标在**两个独立代码块**里，必须能跨块合并。"""

    BLOCK_A = "收盘价: 1.435\nMA_5: 1.436\nMA_10: 1.4175"
    BLOCK_B = "RSI_6: 62.4444\nRSI_12: 60.5561"

    def test_single_block_lookup_cannot_satisfy_both(self):
        """坏用法复现：要求同一个块里既有 MA_5 又有 RSI_6 ⇒ **永远解空**。"""
        blocks = [kv_from_block(self.BLOCK_A), kv_from_block(self.BLOCK_B)]
        assert find_kv(blocks, "MA_5", "RSI_6") == {}, "夹具失真：本应解空"

    def test_merged_dict_satisfies_both(self):
        """正确用法：先合并再查 ⇒ 两块都命中（这是 build() 采用的写法）。"""
        merged = {**find_kv([kv_from_block(self.BLOCK_A)], "MA_5"),
                  **find_kv([kv_from_block(self.BLOCK_B)], "RSI_6")}
        assert merged["MA_5"] == "1.436"
        assert merged["RSI_6"] == "62.4444"
        assert len(merged) >= 4

    def test_find_kv_returns_first_satisfying_block(self):
        blocks = [{"A": "1"}, {"A": "2", "B": "3"}]
        assert find_kv(blocks, "A", "B") == {"A": "2", "B": "3"}
        assert find_kv(blocks, "不存在") == {}


@pytest.mark.unit
class TestParseTables:
    """K 线表是唯一的 markdown 表格，列名必须能对上。"""

    def test_parses_header_and_rows(self):
        text = "\n".join([
            "说明文字",
            "| date | open | last | high | low |",
            "| --- | --- | --- | --- | --- |",
            "| 2026-10-15 | 1.446 | 1.435 | 1.449 | 1.424 |",
            "| 2026-10-14 | 1.432 | 1.449 | 1.450 | 1.431 |",
            "",
        ])
        tables = parse_tables(text)
        assert len(tables) == 1
        header, body = tables[0]
        assert "last" in header and "date" in header
        # ⚠️ 分隔行 `| --- |` **会进 body**（共 3 行：分隔行 + 2 数据行）。
        #    这是 `parse_tables` 的真实契约：它只做「连续 | 行分组」，不做分隔行剔除。
        #    调用方（build / find_table 的使用者）靠**列名索引**取值，
        #    分隔行的单元格（'---'）过不了 first_num 而被跳过 —— 见下一条测试。
        assert len(body) == 3
        assert body[0][0] == "---", "分隔行应位于 body[0]"

    def test_separator_row_is_skipped_by_numeric_parsing(self):
        """分隔行不产出数值 ⇒ 调用方的 `if c is None: continue` 会跳过它。"""
        text = "| date | last |\n| --- | --- |\n| 2026-01-01 | 1.5 |\n"
        _, body = parse_tables(text)[0]
        assert first_num(body[0][1]) is None, "分隔行不该产出数值"
        assert first_num(body[1][1]) == 1.5

    def test_find_table_by_required_columns(self):
        text = "\n".join([
            "| a | b |", "| --- | --- |", "| 1 | 2 |", "",
            "| date | last | high | low |", "| --- | --- | --- | --- |",
            "| 2026-01-01 | 1 | 2 | 0.5 |", "",
        ])
        header, body = find_table(parse_tables(text), "date", "last", "high", "low")
        assert header is not None and "date" in header
        # 同样含分隔行 ⇒ 2 行
        assert len(body) == 2

    def test_missing_table_returns_none(self):
        header, body = find_table(parse_tables("无表格"), "date", "last")
        assert header is None and body is None

    def test_separator_row_is_not_treated_as_header_only(self):
        """分隔行 `| --- |` 会进 body —— 调用方需按列名索引而非按位置硬取。

        这里锁定「不会把分隔行误当数据行解析出数字」的行为：其单元格非数值，
        first_num 返回 None，调用方用 `if c is None: continue` 跳过。
        """
        text = "| date | last |\n| --- | --- |\n| 2026-01-01 | 1.5 |\n"
        _, body = parse_tables(text)[0]
        assert first_num(body[0][1]) is None, "分隔行不该产出数值"
        assert first_num(body[1][1]) == 1.5


@pytest.mark.unit
class TestFormatDriftIsDetectable:
    """★ 格式漂移必须**可被检出**，而不是静默解出空值。

    `_derive_a_etf.py` 在输出里打印「解析字段数: quote=… technical=… chip=…
    （任一为 0 ⇒ 证据包格式已变，本文件不可信）」。本测试锁定：
    当证据包换成**另一种格式**（例如全部改成 markdown 表格）时，
    代码块解析路径确实解出 **0 个字段** ⇒ 上层能据此判为不可信。
    """

    def test_codeblock_parser_yields_nothing_on_table_only_evidence(self):
        # 模拟「证据包格式已变」：数据全在表格里，没有 key: value 代码块
        drifted = "\n".join([
            "| 指标 | 值 |", "| --- | --- |",
            "| 收盘价 | 1.435 |", "| MA_5 | 1.436 |", "",
        ])
        blocks = [kv_from_block(b) for b in parse_code_blocks(drifted)]
        quote = find_kv(blocks, "收盘价")
        assert quote == {}, "格式漂移时却解出了字段 —— 会导致静默使用错误数据"

    def test_codeblock_parser_works_on_valid_evidence(self):
        ok = "```\n收盘价: 1.435\nMA_5: 1.436\n```\n"
        blocks = [kv_from_block(b) for b in parse_code_blocks(ok)]
        assert find_kv(blocks, "收盘价")["收盘价"] == "1.435"

    def test_parse_code_blocks_handles_language_tag(self):
        ok = "```text\n收盘价: 1.435\n```\n"
        blocks = parse_code_blocks(ok)
        assert len(blocks) == 1
        assert "收盘价" in blocks[0]
