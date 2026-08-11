"""TossOhlcvProvider facade, mirroring kis_provider.

Implements the OhlcvProvider protocol against the Toss open API, including
the same invalidate-and-refresh-once token recovery kis_provider performs for
EGW00123 — here triggered by the invalid-token/expired-token error codes.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2

from fractal_journal.kis_auth import AccessToken
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvBar,
)
from fractal_journal.schemas import WarningCode
from fractal_journal.toss_auth import (
    TossCredentials,
    create_toss_client,
    get_access_token,
    invalidate_token_cache,
)
from fractal_journal.toss_daily_history import (
    DAILY_TIMEFRAME,
    TossDailyPageFetcher,
    collect_daily_bars,
)
from fractal_journal.toss_history import (
    CANDLES_ENDPOINT,
    MINUTE_TR_ID,
    RATE_LIMIT_STATUS_CODE,
    TossHistoryPageFetcher,
    collect_historical_bars,
    default_history_throttle,
)
from fractal_journal.toss_models import TossCandle, TossCandlesPage, to_ohlcv_bar

__all__ = [
    "TossCandle",
    "TossCandlesPage",
    "TossHistoryPageFetcher",
    "TossOhlcvProvider",
    "collect_historical_bars",
]

SEOUL = ZoneInfo("Asia/Seoul")
TOSS_BASE_URL = "https://openapi.tossinvest.com"
MINIMUM_COMPLETE_BARS = 30
INVALID_ACCESS_TOKEN_ERROR_CODES = frozenset({"invalid-token", "expired-token"})
# One page covers 200 minutes; three pages cover the request model's maximum
# lookback+forward window (240+240+1 bars).
WINDOW_MAX_PAGES = 3


@dataclass(frozen=True, slots=True)
class TossOhlcvProvider:
    credentials: TossCredentials
    token_cache_path: Path
    base_url: str = TOSS_BASE_URL
    history_throttle: Callable[[], None] = default_history_throttle

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        decision_time = datetime.fromisoformat(request.decision_time_exchange)
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=SEOUL)
        request_time = decision_time + timedelta(minutes=request.forward_minutes)
        with create_toss_client(self.base_url) as client:
            token = get_access_token(client, self.credentials, self.token_cache_path)
            pages = self._fetch_window_pages(client, token, request, request_time)
            if _pages_have_invalid_access_token(pages):
                invalidate_token_cache(self.token_cache_path)
                token = get_access_token(
                    client,
                    self.credentials,
                    self.token_cache_path,
                    force_refresh=True,
                )
                pages = self._fetch_window_pages(client, token, request, request_time)
        return _to_window(request, decision_time, request_time, pages)

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        with create_toss_client(self.base_url) as client:
            result = self._collect_historical_bars(client, request)
            if not _history_has_invalid_access_token(result):
                return result
            invalidate_token_cache(self.token_cache_path)
            return self._collect_historical_bars(
                client,
                request,
                force_refresh=True,
            )

    def _collect_historical_bars(
        self,
        client: httpx2.Client,
        request: HistoricalBarsRequest,
        *,
        force_refresh: bool = False,
    ) -> HistoricalBarsResult:
        token = get_access_token(
            client,
            self.credentials,
            self.token_cache_path,
            force_refresh=force_refresh,
        )
        if request.timeframe == DAILY_TIMEFRAME:
            fetch_daily_page = TossDailyPageFetcher(
                client=client,
                token=token,
                symbol=request.provider_symbol,
            )
            return collect_daily_bars(
                request,
                fetch_daily_page,
                self.history_throttle,
            )
        fetch_page = TossHistoryPageFetcher(
            client=client,
            token=token,
            symbol=request.provider_symbol,
        )
        return collect_historical_bars(
            request,
            fetch_page,
            self.history_throttle,
        )

    def _fetch_window_pages(
        self,
        client: httpx2.Client,
        token: AccessToken,
        request: MinuteWindowRequest,
        request_time: datetime,
    ) -> tuple[TossCandlesPage, ...]:
        fetch_page = TossHistoryPageFetcher(
            client=client,
            token=token,
            symbol=request.provider_symbol,
        )
        needed_bars = request.lookback_minutes + request.forward_minutes + 1
        pages: list[TossCandlesPage] = []
        seen: set[str] = set()
        cursor = request_time.isoformat()
        for page_index in range(WINDOW_MAX_PAGES):
            page = fetch_page(cursor)
            pages.append(page)
            if page.error_code is not None or not page.candles:
                break
            seen.update(candle.timestamp for candle in page.candles)
            if (
                len(seen) >= needed_bars
                or page.next_before is None
                or page.next_before == cursor
            ):
                break
            cursor = page.next_before
            if page_index + 1 < WINDOW_MAX_PAGES:
                self.history_throttle()
        return tuple(pages)


def _history_has_invalid_access_token(result: HistoricalBarsResult) -> bool:
    return any(
        code in INVALID_ACCESS_TOKEN_ERROR_CODES
        for code in result.provenance.api_message_codes
    )


def _pages_have_invalid_access_token(pages: tuple[TossCandlesPage, ...]) -> bool:
    return any(
        page.error_code in INVALID_ACCESS_TOKEN_ERROR_CODES for page in pages
    )


def _to_window(
    request: MinuteWindowRequest,
    decision_time: datetime,
    request_time: datetime,
    pages: tuple[TossCandlesPage, ...],
) -> MinuteWindowResult:
    # Toss pages cross session boundaries (unlike KIS's single-day endpoint),
    # so returned bars are clipped to the requested lookback window.
    window_start = decision_time - timedelta(minutes=request.lookback_minutes)
    bars_by_time: dict[datetime, OhlcvBar] = {}
    for page in pages:
        for candle in page.candles:
            bar = to_ohlcv_bar(candle)
            if bar.time_utc < window_start:
                continue
            _ = bars_by_time.setdefault(bar.time_utc, bar)
    bars = tuple(bars_by_time[key] for key in sorted(bars_by_time))
    payload = "\n".join(page.model_dump_json() for page in pages)
    return MinuteWindowResult(
        provider="toss",
        endpoint=CANDLES_ENDPOINT,
        tr_id=MINUTE_TR_ID,
        request_date=request_time.strftime("%Y%m%d"),
        request_hour=request_time.strftime("%H%M%S"),
        price_basis=request.price_basis_policy,
        session_state=_session_state(request_time, bars),
        data_status=_data_status(pages, bars),
        raw_response_sha256=sha256(payload.encode("utf-8")).hexdigest(),
        bars=bars,
        warnings=_warnings(request_time, bars, pages),
    )


def _warnings(
    request_time: datetime,
    bars: tuple[OhlcvBar, ...],
    pages: tuple[TossCandlesPage, ...],
) -> tuple[WarningCode, ...]:
    warnings: list[WarningCode] = [WarningCode.PRICE_BASIS_UNVERIFIED]
    if any(page.status_code == RATE_LIMIT_STATUS_CODE for page in pages):
        warnings.append(WarningCode.RETRY_EXHAUSTED)
    if not bars:
        warnings.append(WarningCode.EMPTY_DATA)
        return tuple(warnings)
    returned_date = datetime.fromisoformat(bars[-1].time_exchange).strftime("%Y%m%d")
    if returned_date != request_time.strftime("%Y%m%d"):
        warnings.append(WarningCode.REQUEST_DATE_MISMATCH)
    if request_time.strftime("%H%M") > "1530":
        warnings.append(WarningCode.AFTER_REGULAR_CLOSE_CLAMPED)
    return tuple(warnings)


# Session-state heuristics use the KRX regular-session clock, mirroring
# kis_provider's classification for chain-consistent results.
def _session_state(request_time: datetime, bars: tuple[OhlcvBar, ...]) -> str:
    if not bars:
        return "depth_exhausted_empty"
    if request_time.strftime("%H%M") > "1530":
        return "after_regular_close_clamped"
    if request_time.strftime("%H%M") >= "1520":
        return "regular_close_edge"
    return "regular"


def _data_status(
    pages: tuple[TossCandlesPage, ...],
    bars: tuple[OhlcvBar, ...],
) -> str:
    has_error = any(page.error_code is not None for page in pages)
    if not bars:
        return "api_error" if has_error else "empty_data"
    if has_error or len(bars) < MINIMUM_COMPLETE_BARS:
        return "partial_data"
    return "ok"
