# lifecycle: reusable
# created: 2026-10-21
"""流水线日志与"降级留痕"。

为什么需要它
------------
``wb_analysis/`` 目前没有任何 logging（全仓检索 ``import logging`` 命中 0），状态全靠
``print()``；同时 ``except Exception`` 约 100 处，多数被静默吞掉，于是"某块数据没取到"
只能靠事后的 ``_audit_gaps.py`` / ``_check_residuals.py`` 反查。

本模块提供一个统一 logger 和 :func:`log_gap`，把"这块失败但不阻断"变成可检索的记录：

    except Exception as exc:          # noqa: BLE001 — 不阻断本节，但必须留痕
        log_gap("options.realtime_close", exc)

日志同时输出到 stderr 与 run 目录下的 ``_run.log``（``*.log`` 已被 .gitignore 覆盖）。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

__all__ = ["get_logger", "log_gap", "gap_records", "gap_entries", "reset_gaps", "attach_file_log"]

_LOGGER_NAME = "wb_analysis"
_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_configured = False
_gaps: list[dict[str, str]] = []


def get_logger() -> logging.Logger:
    """返回流水线 logger。首次调用时挂 handler，重复调用不会重复挂。"""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FMT))
        logger.addHandler(handler)
        level_name = os.environ.get("WB_LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, level_name, logging.INFO))
        logger.propagate = False
        _configured = True
    return logger


def attach_file_log(path: str | Path) -> Path:
    """把日志同时写到文件（通常放在本次 run 目录下）。返回落盘路径。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FMT))
    get_logger().addHandler(handler)
    return path


def log_gap(section: str, exc: BaseException | str) -> None:
    """记录一处降级：某块数据没取到，但不阻断本次采集。

    ``section`` 用"模块.子块"的写法（如 ``options.realtime_close``），便于之后按块聚合。
    """
    detail = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    _gaps.append({"section": section, "detail": detail})
    get_logger().warning("gap[%s] %s", section, detail)


def gap_records() -> list[dict[str, str]]:
    """本次进程内所有降级记录，供报告/门禁消费（例如写进 meta 的 gaps 字段）。"""
    return list(_gaps)


def reset_gaps() -> None:
    """清空本次进程内的降级记录（测试用）。"""
    _gaps.clear()


def gap_entries() -> list[dict[str, object]]:
    """把本次进程的降级记录转成**缺口台账**的条目格式，供 `.gaps.json` 合并。

    与 `_gap_ledger.py` 的条目 schema 对齐：``cls="R"`` 表示运行期降级、
    ``decisive=False``（log_gap 只登记「没取到但不阻断」的块，是否决定性由人判定，
    不在这里替下游下结论）。
    """
    return [
        {
            "channel": r["section"],
            "label": r["section"],
            "status": "runtime",
            "cls": "R",
            "decisive": False,
            "blocks": "运行期降级：该数据块本次未取到，采集未中断",
            "remedy": "重跑该通道；持续失败则检查数据源可用性与凭证",
            "fallback": "该块以占位/缺失呈现，依赖它的结论须写成条件式",
            "kw": [r["section"]],
            "note": r["detail"],
        }
        for r in gap_records()
    ]
