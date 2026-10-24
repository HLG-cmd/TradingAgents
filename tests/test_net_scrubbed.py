"""`get_scrubbed` 的脱敏保证（移植自上游 #1324）。

为什么必须有测试：这类修复**没有可见症状**——不修也能跑、日志也不报错，
只是 key 悄悄写进了 traceback。所以必须把「不打码 = 漏洞」钉成断言：
1. 异常文本里出现 `***`，且**不含**原 key；
2. 异常**不携带** request / response（两者都持有完整 URL）；
3. 异常**没有** `__cause__` 链（`raise` 写在 except 块外，否则隐式链会把原异常挂回去）。
"""
from __future__ import annotations

import pytest
import requests

from tradingagents.dataflows.net import get_scrubbed

SECRET = "SUPER_SECRET_KEY_123"
URL = "https://api.stlouisfed.org/fred/series"
FULL = f"{URL}?api_key={SECRET}"


@pytest.mark.unit
class TestGetScrubbed:
    def test_success_returns_response(self, monkeypatch):
        class _R:
            status_code = 200

            def raise_for_status(self):
                return None      # 200 时 requests 不会抛错

        monkeypatch.setattr(requests, "get", lambda *a, **k: _R())
        assert get_scrubbed(URL, params={"api_key": SECRET}, timeout=5, secret=SECRET).status_code == 200

    def test_http_error_message_is_scrubbed(self, monkeypatch):
        def boom(*a, **k):
            raise requests.HTTPError(f"500 Server Error for url: {FULL}")

        monkeypatch.setattr(requests, "get", boom)
        with pytest.raises(requests.HTTPError) as ei:
            get_scrubbed(URL, params={"api_key": SECRET}, timeout=5, secret=SECRET)
        msg = str(ei.value)
        assert SECRET not in msg
        assert "***" in msg

    def test_connection_and_timeout_errors_scrubbed(self, monkeypatch):
        for cls in (requests.ConnectionError, requests.Timeout):
            def boom(*a, _c=cls, **k):
                raise _c(f"failed for url: {FULL}")

            monkeypatch.setattr(requests, "get", boom)
            with pytest.raises(cls) as ei:
                get_scrubbed(URL, params={"api_key": SECRET}, timeout=5, secret=SECRET)
            assert SECRET not in str(ei.value)

    def test_no_request_response_or_cause_attached(self, monkeypatch):
        def boom(*a, **k):
            raise requests.ConnectionError(f"failed for url: {FULL}")

        monkeypatch.setattr(requests, "get", boom)
        with pytest.raises(requests.ConnectionError) as ei:
            get_scrubbed(URL, params={"api_key": SECRET}, timeout=5, secret=SECRET)
        exc = ei.value
        assert getattr(exc, "request", None) is None
        assert getattr(exc, "response", None) is None
        assert exc.__cause__ is None          # 隐式链会把原异常（含 URL）挂回来

    def test_passthrough_status_is_returned(self, monkeypatch):
        class _R:
            status_code = 400
            text = '{"error_message": "bad series"}'

            def raise_for_status(self):
                raise AssertionError("passthrough 状态不应抛错")

        monkeypatch.setattr(requests, "get", lambda *a, **k: _R())
        r = get_scrubbed(URL, params={"api_key": SECRET}, timeout=5, secret=SECRET, passthrough=(400,))
        assert r.status_code == 400

    def test_empty_secret_still_raises(self, monkeypatch):
        """key 未配置时（secret 为空串）不能因为 replace("") 而崩掉。"""
        def boom(*a, **k):
            raise requests.ConnectionError("failed")

        monkeypatch.setattr(requests, "get", boom)
        with pytest.raises(requests.ConnectionError):
            get_scrubbed(URL, params={}, timeout=5, secret="")
