"""KIS daily bars for free-form chart queries.

Daily charts are deliberately not registrable from the extension — submission
evidence fetches KIS directly — so the free-query path, which reads only
registered series, could never see a daily chart. This source fills that gap:
it pulls the full adjusted daily history from KIS once, caches it as a
normalized series CSV, and refreshes incrementally whenever the cache lacks
the latest completed session.

The cache lives in its own directory rather than bar_series/ because
registered series carry TradingView-export provenance; mixing KIS bars in
would mislabel review evidence and silently switch daily reviews off their
KIS-direct path.
"""

from __future__ import annotations

import json
import time as time_module
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import InvalidOperation
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import httpx2
from pydantic import ValidationError

from fractal_journal.bar_series import BarSeriesError
from fractal_journal.kis_auth import KisTokenIssueError
from fractal_journal.kis_daily_history import DAILY_TIMEFRAME
from fractal_journal.provider import HistoricalBarsRequest, HistoricalStopReason

if TYPE_CHECKING:
    from collections.abc import Callable

    from fractal_journal.bar_series import FileBarSeriesStore
    from fractal_journal.provider import OhlcvBar, OhlcvProvider

SEOUL = ZoneInfo("Asia/Seoul")
DAILY_CACHE_DIRNAME: Final = "kis_daily_query_cache"
# HistoricalBarsRequest caps target_bars at 5000 (~20 years of sessions);
# paging stops naturally at listing start via EMPTY_PAGE before that.
FULL_HISTORY_TARGET_BARS: Final = 5000
# Request-model minimum; its three pages re-cover any staleness gap a live
# cache can accumulate between queries, and registration merges by bar time.
REFRESH_TARGET_BARS: Final = 201
SESSION_CLOSE: Final = time(15, 30)
_SATURDAY: Final = 5
# The shared 0.05s history throttle (~20 req/s) sits exactly on KIS's rate
# limit and a deep daily fetch needs 50+ pages, so it reliably trips EGW00201
# (observed: cut to 935 bars at page 10). ~3 req/s keeps a full fetch under
# half a minute while staying far from the limit.
DEEP_HISTORY_THROTTLE_SECONDS: Final = 0.35
# The KIS quota that EGW00201 protects is per-second, so a short pause is
# enough for a retried fetch to page deeper than the cut one.
RATE_LIMIT_RETRY_SLEEP_SECONDS: Final = 1.5
FETCH_ATTEMPTS: Final = 3

_FETCH_ERRORS = (
    httpx2.HTTPError,
    InvalidOperation,
    json.JSONDecodeError,
    KisTokenIssueError,
    ValidationError,
    ValueError,
)


def last_expected_session_date(now: datetime) -> date:
    """Latest KRX session whose daily bar should already be complete.

    Weekend-aware only: on a weekday holiday this names a session that never
    happened, so a fresh cache merely looks stale and costs one no-op refresh
    fetch per query — accepted over maintaining a holiday calendar.
    """
    local = now.astimezone(SEOUL)
    day = local.date()
    if local.time() < SESSION_CLOSE:
        day -= timedelta(days=1)
    while day.weekday() >= _SATURDAY:
        day -= timedelta(days=1)
    return day


def deep_history_throttle() -> None:
    time_module.sleep(DEEP_HISTORY_THROTTLE_SECONDS)


def _default_retry_sleep() -> None:
    time_module.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)


@dataclass(frozen=True, slots=True)
class KisDailyQuerySource:
    provider: OhlcvProvider
    cache_store: FileBarSeriesStore
    retry_sleep: Callable[[], None] = field(default=_default_retry_sleep)

    def load(
        self,
        symbol: str,
        *,
        now: datetime | None = None,
    ) -> tuple[OhlcvBar, ...] | None:
        resolved_now = now or datetime.now(SEOUL)
        cached = self._cached(symbol)
        if cached is not None and _is_fresh(cached, resolved_now):
            return cached
        target = FULL_HISTORY_TARGET_BARS if cached is None else REFRESH_TARGET_BARS
        fetched = self._fetch_with_retry(symbol, resolved_now, target)
        if not fetched:
            return cached
        _ = self.cache_store.register(symbol, DAILY_TIMEFRAME, fetched)
        return self.cache_store.load(symbol, DAILY_TIMEFRAME)

    def _fetch_with_retry(
        self,
        symbol: str,
        resolved_now: datetime,
        target: int,
    ) -> tuple[OhlcvBar, ...]:
        # Other tools share this KIS app key, so even the gentle throttle can
        # hit the per-second quota mid-fetch; a cut fetch still returns the
        # recent pages, so retry and keep the union of everything seen.
        merged: dict[datetime, OhlcvBar] = {}
        for attempt in range(FETCH_ATTEMPTS):
            try:
                result = self.provider.fetch_historical_bars(
                    HistoricalBarsRequest(
                        provider_symbol=symbol,
                        decision_time_exchange=resolved_now,
                        timeframe=DAILY_TIMEFRAME,
                        target_bars=target,
                    ),
                )
            except _FETCH_ERRORS:
                break
            if result.provider == "fixture":
                break
            for bar in result.bars:
                merged[bar.time_utc] = bar
            if result.provenance.stop_reason is not HistoricalStopReason.RATE_LIMITED:
                break
            if attempt + 1 < FETCH_ATTEMPTS:
                self.retry_sleep()
        return tuple(merged[key] for key in sorted(merged))

    def _cached(self, symbol: str) -> tuple[OhlcvBar, ...] | None:
        try:
            return self.cache_store.load(symbol, DAILY_TIMEFRAME)
        except BarSeriesError:
            return None


def _is_fresh(cached: tuple[OhlcvBar, ...], now: datetime) -> bool:
    last_session = cached[-1].time_utc.astimezone(SEOUL).date()
    return last_session >= last_expected_session_date(now)
