"""Toss daily candle collector, mirroring kis_daily_history.

Where KIS pages daily bars by explicit 140-day date windows, Toss uses the
same nextBefore cursor as its minute endpoint with interval=1d. Daily
retention covers the full listing history (005930 back to 1975), so paging
stops at the listing start via a null nextBefore / empty page.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import httpx2

from fractal_journal.kis_auth import AccessToken
from fractal_journal.kis_history import history_status
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalProvenance,
    HistoricalStopReason,
    OhlcvBar,
)
from fractal_journal.toss_history import (
    CANDLES_ENDPOINT,
    PAGE_CANDLE_COUNT,
    RATE_LIMIT_STATUS_CODE,
    cursor_stalled,
    parse_cursor_datetime,
    request_with_rate_limit_retry,
)
from fractal_journal.toss_models import (
    TossCandlesPage,
    daily_bar_to_ohlcv,
    parse_toss_candles_page,
)

DAILY_INTERVAL = "1d"
DAILY_TR_ID = "TOSS_CANDLES_1D"
DAILY_TIMEFRAME = "1D"
DAILY_TIMEFRAME_MINUTES = 1440
# adjusted=true is Toss's default; it is pinned explicitly so SMA/VWMA windows
# spanning corporate actions stay comparable even if the server default moves.
# The stored price basis remains provenance, not verification.
DAILY_PRICE_BASIS = "toss_daily_adjusted_requested_unverified"


@dataclass(frozen=True, slots=True)
class TossDailyPageFetcher:
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
                    "interval": DAILY_INTERVAL,
                    "count": PAGE_CANDLE_COUNT,
                    "before": before,
                    "adjusted": "true",
                },
            )

        return parse_toss_candles_page(request_with_rate_limit_retry(send, self.sleep))


def collect_daily_bars(
    request: HistoricalBarsRequest,
    fetch_page: Callable[[str], TossCandlesPage],
    throttle: Callable[[], None],
) -> HistoricalBarsResult:
    decision_utc = request.decision_time_exchange.astimezone(UTC)
    cursor = request.decision_time_exchange.isoformat()
    last_cursor: datetime | None = None
    daily_bars: dict[datetime, OhlcvBar] = {}
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

        page_bars = tuple(daily_bar_to_ohlcv(candle) for candle in page.candles)
        # A daily bar becomes evidence at its session close, so an intraday
        # decision time excludes that date's still-forming bar.
        eligible_bars = tuple(
            bar for bar in page_bars if bar.time_utc <= decision_utc
        )
        future_bars_filtered += len(page_bars) - len(eligible_bars)
        for bar in eligible_bars:
            _ = daily_bars.setdefault(bar.time_utc, bar)
        if len(daily_bars) >= request.target_bars:
            stop_reason = HistoricalStopReason.TARGET_REACHED
            break

        if page.next_before is None:
            # Listing start reached; older history does not exist.
            stop_reason = HistoricalStopReason.EMPTY_PAGE
            break
        if cursor_stalled(cursor, page.next_before):
            stop_reason = HistoricalStopReason.NO_PROGRESS
            break
        cursor = page.next_before
        if page_index + 1 < request.max_pages:
            throttle()

    bars = tuple(
        bar for _, bar in sorted(daily_bars.items())
    )
    raw_hash = sha256("\n".join(response_payloads).encode()).hexdigest()
    return HistoricalBarsResult(
        provider="toss",
        status=history_status(stop_reason, bars, request.target_bars),
        bars=bars,
        provenance=HistoricalProvenance(
            endpoint=CANDLES_ENDPOINT,
            tr_id=DAILY_TR_ID,
            request_end_exchange=request.decision_time_exchange,
            source_timeframe_minutes=DAILY_TIMEFRAME_MINUTES,
            aggregated_timeframe_minutes=DAILY_TIMEFRAME_MINUTES,
            target_bars=request.target_bars,
            page_count=len(response_payloads),
            raw_bar_count=raw_bar_count,
            unique_minute_bar_count=len(daily_bars),
            future_bars_filtered=future_bars_filtered,
            price_basis=DAILY_PRICE_BASIS,
            api_message_codes=tuple(api_codes),
            last_cursor_exchange=last_cursor,
            raw_response_sha256=raw_hash,
            stop_reason=stop_reason,
        ),
    )
