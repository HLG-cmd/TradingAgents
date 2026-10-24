"""HTTP helpers shared by the vendors."""

import requests


def get_scrubbed(url: str, *, params: dict, timeout: float, secret: str, passthrough=()):
    """``requests.get`` + ``raise_for_status``，但把 ``secret`` 挡在异常之外。

    为什么需要：FRED 与 Alpha Vantage 用**查询参数**鉴权，requests 在 HTTPError /
    ConnectionError / Timeout 的文本里会引用**完整 URL**，于是 key 会被写进任何记录该
    异常的日志或 traceback（上游 #1324；本项目 2026-10-24 从上游移植）。

    做法：把 requests 异常**以同一类型重抛**，文本中的 key 替换为 ``***``，
    且**不携带** request / response（两者都持有 URL）与异常链 —— 因此 raise 必须在
    ``except`` 块**之外**，否则隐式异常链会把原始异常（含 URL）重新挂上去。

    ``passthrough`` 里的状态码不抛错，交回调用方自行处理（如 FRED 的 400 带 JSON 错误体）。
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code not in passthrough:
            response.raise_for_status()
        return response
    except requests.RequestException as exc:
        error = type(exc)(str(exc).replace(secret, "***")) if secret else exc
    raise error
