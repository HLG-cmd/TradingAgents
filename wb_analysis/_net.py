# lifecycle: reusable
# created: 2026-10-21
"""统一的网络重试。

为什么需要它
------------
此前重试有三份各自为政的实现：

* ``collect.py``        ``_retry(fn, *args, retries=_NET_RETRIES, delay=1.5)``
* ``_option_source.py`` ``BACKOFF_BASE = 2.0`` + 自己的 for 循环
* ``_erp_retry.py``     自己的 6 次循环

本模块把它们收敛成一份，并且**行为可测**（见 ``tests/test_retry_behaviour.py``）。
这样一来就可以删掉 ``_selftest.py`` 里那种"读源码找字符串"的检查——它现在靠打开
``collect.py`` 的源码文本、判断是否包含 ``"_retry(fetch_option_structure"`` 来"验证
重试覆盖"（``_selftest.py:668-686``）：重构即假失败，真正的重试失效又未必发现。
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from wb_analysis._log import get_logger

__all__ = ["retry", "NET_RETRIES", "BACKOFF_BASE", "is_retryable"]

T = TypeVar("T")

NET_RETRIES = 3
BACKOFF_BASE = 1.5  # 第 n 次重试等待 BACKOFF_BASE * n 秒（线性退避）

# 明确不该重试的异常：4xx / 入参 / 数据格式类错误，重试只是浪费时间。
_NON_RETRYABLE = {
    "HTTPError",  # 4xx（例如 Cboe 403）
    "PermissionError",
    "FileNotFoundError",
    "ValueError",
    "KeyError",
    "TypeError",
}


def is_retryable(exc: BaseException) -> bool:
    """按异常类型名判断是否值得重试。"""
    return type(exc).__name__ not in _NON_RETRYABLE


def retry(
    fn: Callable[..., T],
    *args,
    retries: int = NET_RETRIES,
    delay: float = BACKOFF_BASE,
    what: str = "",
    retryable: tuple[type[Exception], ...] | type[Exception] | Callable[[BaseException], bool] | None = None,
    **kwargs,
) -> T:
    """执行 ``fn``，失败则线性退避重试；不可重试的异常立刻抛出。

    参数
    ----
    retryable:
        自定义可重试条件：
        - 传异常类型或异常元组：仅当 isinstance(exc, retryable) 为真时重试；
        - 传 Callable：传入 exc 返回 bool；
        - 为 None（默认）：使用 `is_retryable` 黑名单机制（非 HTTPError/ValueError 等）。

    最后一次仍失败时抛出**原异常**（不包装），保持调用方原有的 except 语义不变。
    """
    log = get_logger()
    label = what or getattr(fn, "__name__", "fn")
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — 重试层必须接住一切
            can_retry = False
            if retryable is None:
                can_retry = is_retryable(exc)
            elif isinstance(retryable, (tuple, list)):
                can_retry = isinstance(exc, tuple(retryable))
            elif isinstance(retryable, type) and issubclass(retryable, BaseException):
                can_retry = isinstance(exc, retryable)
            elif callable(retryable):
                can_retry = bool(retryable(exc))

            if not can_retry or attempt >= retries:
                raise
            wait = delay * attempt
            log.warning(
                "retry %d/%d %s: %s -> 等待 %.1fs",
                attempt,
                retries,
                label,
                type(exc).__name__,
                wait,
            )
            time.sleep(wait)
