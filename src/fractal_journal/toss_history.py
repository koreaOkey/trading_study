"""Toss 1-minute candle collector, mirroring kis_history's consumer interface.

KIS pages backward by re-requesting at an explicit date/hour cursor; Toss
instead returns a nextBefore cursor that is passed verbatim as the next
request's `before` (an inclusive upper bound). The collector keeps the same
HistoricalBarsResult shape so callers cannot tell the two apart.

Retention: Toss keeps roughly four years of KR 1-minute candles. A request
whose window lies entirely outside retention comes back as an empty first
page, which is reported as EMPTY_DATA — a normal result that lets a fallback
chain try KIS instead.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import httpx2

from fractal_journal.bar_aggregation import aggregate_minute_bars
from fractal_journal.kis_auth import AccessToken
from fractal_journal.kis_history import history_status
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    HistoricalProvenance,
    HistoricalStopReason,
    OhlcvBar,
)
from fractal_journal.toss_models import (
    TossCandlesPage,
    parse_toss_candles_page,
    to_ohlcv_bar,
)

CANDLES_ENDPOINT = "/api/v1/candles"
MINUTE_INTERVAL = "1m"
MINUTE_TR_ID = "TOSS_CANDLES_1M"
PAGE_CANDLE_COUNT = 200
# The documented chart-group limit is 5 req/s, but 0.25s spacing still trips
# 429 in practice; 0.5s is the observed safe cadence.
HISTORY_THROTTLE_SECONDS = 0.5
RATE_LIMIT_STATUS_CODE = 429
RATE_LIMIT_MAX_RETRIES = 4
RETRY_AFTER_HEADER = "Retry-After"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"


def default_history_throttle() -> None:
    time.sleep(HISTORY_THROTTLE_SECONDS)


def rate_limit_delay_seconds(response: httpx2.Response, attempt: int) -> float:
    for header in (RETRY_AFTER_HEADER, RATE_LIMIT_RESET_HEADER):
        if header not in response.headers:
            continue
        try:
            delay = float(response.headers[header])
        except ValueError:
            continue
        if delay >= 0:
            return delay
    return float(attempt)


def request_with_rate_limit_retry(
    send: Callable[[], httpx2.Response],
    sleep: Callable[[float], None],
) -> httpx2.Response:
    response = send()
    for attempt in range(1, RATE_LIMIT_MAX_RETRIES + 1):
        if response.status_code != RATE_LIMIT_STATUS_CODE:
            return response
        sleep(rate_limit_delay_seconds(response, attempt))
        response = send()
    return response


def parse_cursor_datetime(cursor: str) -> datetime | None:
    try:
        return datetime.fromisoformat(cursor)
    except ValueError:
        return None


def cursor_stalled(cursor: str, next_before: str) -> bool:
    """True when following next_before cannot reach older data."""
    current = parse_cursor_datetime(cursor)
    upcoming = parse_cursor_datetime(next_before)
    if current is not None and upcoming is not None:
        return upcoming >= current
    return next_before == cursor


@dataclass(frozen=True, slots=True)
class TossHistoryPageFetcher:
    client: httpx2.Client
    token: AccessToken
    symbol: str
    sleep: Callable[[float], None] = time.sleep

    def __call__(self, before: str) -> TossCandlesPage:
        def send() -> httpx2.Response:
            return self.client.get(
                CANDLES_ENDPOINT,
                headers={"authorization": f"Bearer {self.token}"},
                params={
                    "symbol": self.symbol,
                    "interval": MINUTE_INTERVAL,
                    "count": PAGE_CANDLE_COUNT,
                    "before": before,
                    "adjusted": "true",
                },
            )

        return parse_toss_candles_page(request_with_rate_limit_retry(send, self.sleep))


def collect_historical_bars(
    request: HistoricalBarsRequest,
    fetch_page: Callable[[str], TossCandlesPage],
    throttle: Callable[[], None],
) -> HistoricalBarsResult:
    timeframe_minutes = _parse_minute_timeframe(request.timeframe)
    if timeframe_minutes is None:
        return _unsupported_history_result(request)

    decision_utc = request.decision_time_exchange.astimezone(UTC)
    cursor = request.decision_time_exchange.isoformat()
    last_cursor: datetime | None = None
    minute_bars: dict[datetime, OhlcvBar] = {}
    response_payloads: list[str] = []
    api_codes: list[str] = []
    raw_bar_count = 0
    future_bars_filtered = 0
    stop_reason = HistoricalStopReason.PAGE_CAP_REACHED

    for page_index in range(request.max_pages):
        last_cursor = parse_cursor_datetime(cursor)
        page = fetch_page(cursor)
        response_payloads.append(page.model_dump_json())
        api_codes.append(page.error_code or "ok")
        raw_bar_count += len(page.candles)
        if page.error_code is not None:
            stop_reason = (
                HistoricalStopReason.RATE_LIMITED
                if page.status_code == RATE_LIMIT_STATUS_CODE
                else HistoricalStopReason.API_ERROR
            )
            break
        if not page.candles:
            stop_reason = HistoricalStopReason.EMPTY_PAGE
            break

        page_bars = tuple(to_ohlcv_bar(candle) for candle in page.candles)
        eligible_bars = tuple(
            bar for bar in page_bars if bar.time_utc <= decision_utc
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

        if page.next_before is None:
            # Oldest retained candle reached; older history does not exist.
            stop_reason = HistoricalStopReason.EMPTY_PAGE
            break
        if cursor_stalled(cursor, page.next_before):
            stop_reason = HistoricalStopReason.NO_PROGRESS
            break
        cursor = page.next_before
        if page_index + 1 < request.max_pages:
            throttle()

    bars = aggregate_minute_bars(tuple(minute_bars.values()), timeframe_minutes)
    raw_hash = sha256("\n".join(response_payloads).encode()).hexdigest()
    return HistoricalBarsResult(
        provider="toss",
        status=history_status(stop_reason, bars, request.target_bars),
        bars=bars,
        provenance=HistoricalProvenance(
            endpoint=CANDLES_ENDPOINT,
            tr_id=MINUTE_TR_ID,
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
        provider="toss",
        status=HistoricalDataStatus.UNSUPPORTED_TIMEFRAME,
        bars=(),
        provenance=HistoricalProvenance(
            endpoint=CANDLES_ENDPOINT,
            tr_id=MINUTE_TR_ID,
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
