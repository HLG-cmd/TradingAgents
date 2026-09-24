from datetime import datetime

from .alpha_vantage_common import _filter_csv_by_date_range, _make_api_request
from .utils import get_current_date


def get_stock(
    symbol: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Returns raw daily OHLCV values, adjusted close values, and historical split/dividend events
    filtered to the specified date range.

    Args:
        symbol: The name of the equity. For example: symbol=IBM
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing the daily adjusted time series data filtered to the date range.
    """
    # Parse dates to determine the range.
    # ⚠️ 「today」取**美股日历日**，不用本机日期：本机在 UTC+8 时本机日期比美东早一天，
    # 会让 days_from_today_to_start 多 1 天，在 100 天边界附近选错 outputsize。
    # 同族缺陷见 stockstats_utils._market_today_eastern 与铁律 34。
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.strptime(get_current_date(), "%Y-%m-%d")

    # Choose outputsize based on whether the requested range is within the latest 100 days
    # Compact returns latest 100 data points, so check if start_date is recent enough
    days_from_today_to_start = (today - start_dt).days
    outputsize = "compact" if days_from_today_to_start < 100 else "full"

    params = {
        "symbol": symbol,
        "outputsize": outputsize,
        "datatype": "csv",
    }

    response = _make_api_request("TIME_SERIES_DAILY_ADJUSTED", params)

    return _filter_csv_by_date_range(response, start_date, end_date)
