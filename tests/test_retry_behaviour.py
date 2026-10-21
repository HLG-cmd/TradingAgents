"""``wb_analysis/_net.retry`` 的行为测试。

它取代 ``wb_analysis/_selftest.py:668-686`` 那种"读 collect.py 源码、判断是否包含某个
字符串"的检查：那种做法重构即假失败（比如把 _retry 换成装饰器），而真正的重试失效
又未必发现。这里直接测行为。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis import _net  # noqa: E402


@pytest.fixture()
def no_sleep(monkeypatch):
    """重试测试不能真的等 1.5s、3s、4.5s。"""
    monkeypatch.setattr(_net.time, "sleep", lambda *_: None)


def test_retry_succeeds_after_transient_failures(no_sleep):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"

    assert _net.retry(flaky) == "ok"
    assert len(calls) == 3


def test_retry_gives_up_and_reraises_original(no_sleep):
    calls = []

    def always_fail():
        calls.append(1)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _net.retry(always_fail, retries=2)
    assert len(calls) == 2


def test_retry_does_not_retry_non_retryable(no_sleep):
    calls = []

    def bad_args():
        calls.append(1)
        raise ValueError("4xx 类错误不该重试")

    with pytest.raises(ValueError):
        _net.retry(bad_args, retries=5)
    assert len(calls) == 1


def test_retry_passes_args_and_kwargs(no_sleep):
    assert _net.retry(lambda a, b=0: a + b, 2, b=3) == 5


def test_retry_logs_a_gap_warning(no_sleep, caplog):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("transient")
        return "ok"

    with caplog.at_level("WARNING", logger="wb_analysis"):
        assert _net.retry(flaky, what="options.realtime_close") == "ok"
    assert any("options.realtime_close" in r.getMessage() for r in caplog.records)


def test_retry_with_custom_retryable_tuple(no_sleep):
    """当用户显式指定 retryable=(ValueError,) 时，原本非重试的 ValueError 也能按需重试。"""
    calls = []

    def flaky_value_error():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("flaky scraping error")
        return "recovered"

    assert _net.retry(flaky_value_error, retries=3, retryable=(ValueError,)) == "recovered"
    assert len(calls) == 3


def test_retry_with_custom_retryable_callable(no_sleep):
    """支持传入谓词函数动态判定异常是否可重试。"""
    calls = []

    def custom_flaky():
        calls.append(1)
        if len(calls) < 2:
            raise KeyError("transient_missing_key")
        return "key_ok"

    def pred(exc):
        return isinstance(exc, KeyError) and "transient" in str(exc)
    assert _net.retry(custom_flaky, retries=2, retryable=pred) == "key_ok"
    assert len(calls) == 2

