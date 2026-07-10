import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import assert_never
from zoneinfo import ZoneInfo

import httpx2

from fractal_journal.bar_aggregation import aggregate_minute_bars
from fractal_journal.kis_auth import AccessToken, KisCredentials
from fractal_journal.kis_models import (
    KisQuoteResponse,
    parse_kis_quote_response,
    to_ohlcv_bar,
)
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    HistoricalProvenance,
    HistoricalStopReason,
    OhlcvBar,
)

SEOUL = ZoneInfo("Asia/Seoul")
HISTORY_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
HISTORY_TR_ID = "FHKST03010230"
RATE_LIMIT_MESSAGE_CODE = "EGW00201"
HISTORY_THROTTLE_SECONDS = 0.05


def default_history_throttle() -> None:
    time.sleep(HISTORY_THROTTLE_SECONDS)


@dataclass(frozen=True, slots=True)
class KisHistoryPageFetcher:
    client: httpx2.Client
    token: AccessToken
    credentials: KisCredentials
    request: HistoricalBarsRequest

    def __call__(self, cursor: datetime) -> KisQuoteResponse:
        response = self.client.get(
            HISTORY_ENDPOINT,
            headers={
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.token}",
                "appkey": self.credentials.app_key,
                "appsecret": self.credentials.app_secret,
                "tr_id": HISTORY_TR_ID,
            },
            params={
                "FID_COND_MRKT_DIV_CODE": self.request.market_div_code,
                "FID_INPUT_ISCD": self.request.provider_symbol,
                "FID_INPUT_HOUR_1": cursor.strftime("%H%M%S"),
                "FID_INPUT_DATE_1": cursor.strftime("%Y%m%d"),
                "FID_PW_DATA_INCU_YN": "Y",
                "FID_FAKE_TICK_INCU_YN": "",
            },
        )
        return parse_kis_quote_response(response)


def collect_historical_bars(
    request: HistoricalBarsRequest,
    fetch_page: Callable[[datetime], KisQuoteResponse],
    throttle: Callable[[], None],
) -> HistoricalBarsResult:
    timeframe_minutes = _parse_minute_timeframe(request.timeframe)
    if timeframe_minutes is None:
        return _unsupported_history_result(request)

    cursor = request.decision_time_exchange.astimezone(SEOUL)
    last_cursor: datetime | None = None
    minute_bars: dict[datetime, OhlcvBar] = {}
    response_payloads: list[str] = []
    api_codes: list[str] = []
    raw_bar_count = 0
    future_bars_filtered = 0
    stop_reason = HistoricalStopReason.PAGE_CAP_REACHED

    for page_index in range(request.max_pages):
        last_cursor = cursor
        response = fetch_page(cursor)
        response_payloads.append(response.model_dump_json())
        api_codes.append(response.msg_cd)
        raw_bar_count += len(response.output2)
        if response.rt_cd != "0":
            stop_reason = (
                HistoricalStopReason.RATE_LIMITED
                if response.msg_cd == RATE_LIMIT_MESSAGE_CODE
                else HistoricalStopReason.API_ERROR
            )
            break
        if not response.output2:
            stop_reason = HistoricalStopReason.EMPTY_PAGE
            break

        page_bars = tuple(to_ohlcv_bar(bar) for bar in response.output2)
        eligible_bars = tuple(
            bar
            for bar in page_bars
            if bar.time_utc <= request.decision_time_exchange.astimezone(UTC)
        )
        future_bars_filtered += len(page_bars) - len(eligible_bars)
        for bar in eligible_bars:
            _ = minute_bars.setdefault(bar.time_utc, bar)

        aggregated = aggregate_minute_bars(
            tuple(minute_bars.values()),
            timeframe_minutes,
        )
        if len(aggregated) >= request.target_bars:
            stop_reason = HistoricalStopReason.TARGET_REACHED
            break

        earliest_exchange = min(bar.time_utc for bar in page_bars).astimezone(SEOUL)
        next_cursor = earliest_exchange - timedelta(minutes=1)
        if next_cursor >= cursor:
            stop_reason = HistoricalStopReason.NO_PROGRESS
            break
        cursor = next_cursor
        if page_index + 1 < request.max_pages:
            throttle()

    bars = aggregate_minute_bars(tuple(minute_bars.values()), timeframe_minutes)
    raw_hash = sha256("\n".join(response_payloads).encode()).hexdigest()
    return HistoricalBarsResult(
        provider="kis",
        status=_history_status(stop_reason, bars, request.target_bars),
        bars=bars,
        provenance=HistoricalProvenance(
            endpoint=HISTORY_ENDPOINT,
            tr_id=HISTORY_TR_ID,
            request_end_exchange=request.decision_time_exchange,
            aggregated_timeframe_minutes=timeframe_minutes,
            target_bars=request.target_bars,
            page_count=len(response_payloads),
            raw_bar_count=raw_bar_count,
            unique_minute_bar_count=len(minute_bars),
            future_bars_filtered=future_bars_filtered,
            price_basis=request.price_basis_policy,
            api_message_codes=tuple(api_codes),
            last_cursor_exchange=last_cursor,
            raw_response_sha256=raw_hash,
            stop_reason=stop_reason,
        ),
    )


def _parse_minute_timeframe(timeframe: str) -> int | None:
    if not timeframe.isascii() or not timeframe.isdecimal():
        return None
    minutes = int(timeframe)
    return minutes if minutes > 0 else None


def _unsupported_history_result(
    request: HistoricalBarsRequest,
) -> HistoricalBarsResult:
    return HistoricalBarsResult(
        provider="kis",
        status=HistoricalDataStatus.UNSUPPORTED_TIMEFRAME,
        bars=(),
        provenance=HistoricalProvenance(
            endpoint=HISTORY_ENDPOINT,
            tr_id=HISTORY_TR_ID,
            request_end_exchange=request.decision_time_exchange,
            aggregated_timeframe_minutes=None,
            target_bars=request.target_bars,
            page_count=0,
            raw_bar_count=0,
            unique_minute_bar_count=0,
            future_bars_filtered=0,
            price_basis=request.price_basis_policy,
            api_message_codes=(),
            last_cursor_exchange=None,
            raw_response_sha256=sha256(b"").hexdigest(),
            stop_reason=HistoricalStopReason.UNSUPPORTED_TIMEFRAME,
        ),
    )


def _history_status(
    stop_reason: HistoricalStopReason,
    bars: tuple[OhlcvBar, ...],
    target_bars: int,
) -> HistoricalDataStatus:
    match stop_reason:
        case HistoricalStopReason.TARGET_REACHED:
            return (
                HistoricalDataStatus.OK
                if len(bars) >= target_bars
                else HistoricalDataStatus.PARTIAL_DATA
            )
        case HistoricalStopReason.API_ERROR:
            return HistoricalDataStatus.API_ERROR
        case HistoricalStopReason.RATE_LIMITED:
            return HistoricalDataStatus.RATE_LIMITED
        case (
            HistoricalStopReason.PAGE_CAP_REACHED
            | HistoricalStopReason.NO_PROGRESS
            | HistoricalStopReason.EMPTY_PAGE
        ):
            return (
                HistoricalDataStatus.PARTIAL_DATA
                if bars
                else HistoricalDataStatus.EMPTY_DATA
            )
        case HistoricalStopReason.UNSUPPORTED_TIMEFRAME:
            return HistoricalDataStatus.UNSUPPORTED_TIMEFRAME
        case HistoricalStopReason.PROVIDER_UNAVAILABLE:
            return HistoricalDataStatus.PROVIDER_UNAVAILABLE
    assert_never(stop_reason)
