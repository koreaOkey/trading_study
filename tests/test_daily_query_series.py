"""KIS daily fallback for free-form chart queries."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
from fastapi.testclient import TestClient

from fractal_journal.bar_series import FileBarSeriesStore
from fractal_journal.config import Settings
from fractal_journal.daily_query_series import (
    DAILY_CACHE_DIRNAME,
    FULL_HISTORY_TARGET_BARS,
    REFRESH_TARGET_BARS,
    KisDailyQuerySource,
    last_expected_session_date,
)
from fractal_journal.hermes_query import ChartQueryAnswer
from fractal_journal.main import create_app
from fractal_journal.provider import (
    FixtureOhlcvProvider,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    HistoricalProvenance,
    HistoricalStopReason,
    OhlcvBar,
)

SEOUL = ZoneInfo("Asia/Seoul")


def _daily_bars(closes: list[float], *, end: date) -> tuple[OhlcvBar, ...]:
    bars: list[OhlcvBar] = []
    day = end
    for close in reversed(closes):
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        session_close = datetime(day.year, day.month, day.day, 15, 30, tzinfo=SEOUL)
        value = Decimal(str(round(close, 2)))
        bars.append(
            OhlcvBar(
                time_utc=session_close.astimezone(UTC),
                time_exchange=session_close.isoformat(),
                open=value,
                high=value + 1,
                low=value - 1,
                close=value,
                volume=10_000,
            ),
        )
        day -= timedelta(days=1)
    return tuple(reversed(bars))


def _result(
    bars: tuple[OhlcvBar, ...],
    request: HistoricalBarsRequest,
    *,
    stop_reason: HistoricalStopReason = HistoricalStopReason.TARGET_REACHED,
) -> HistoricalBarsResult:
    return HistoricalBarsResult(
        provider="kis",
        status=HistoricalDataStatus.OK,
        bars=bars,
        provenance=HistoricalProvenance(
            endpoint="fake://kis/daily",
            tr_id="FHKST03010100",
            request_end_exchange=request.decision_time_exchange,
            aggregated_timeframe_minutes=1440,
            target_bars=request.target_bars,
            page_count=1,
            raw_bar_count=len(bars),
            unique_minute_bar_count=len(bars),
            future_bars_filtered=0,
            price_basis="kis_daily_adjusted_requested_unverified",
            api_message_codes=("MCA00000",),
            last_cursor_exchange=None,
            raw_response_sha256=sha256(b"fake").hexdigest(),
            stop_reason=stop_reason,
        ),
    )


class FakeDailyProvider:
    def __init__(self, bars: tuple[OhlcvBar, ...]) -> None:
        self.bars = bars
        self.requests: list[HistoricalBarsRequest] = []

    def fetch_minute_window(self, request: object) -> object:  # pragma: no cover
        raise NotImplementedError

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        self.requests.append(request)
        return _result(self.bars, request)


class ErrorDailyProvider(FakeDailyProvider):
    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        self.requests.append(request)
        message = "boom"
        raise httpx2.ConnectError(message)


def _source(
    tmp_path: Path,
    provider: FakeDailyProvider | FixtureOhlcvProvider,
) -> KisDailyQuerySource:
    return KisDailyQuerySource(
        provider=provider,
        cache_store=FileBarSeriesStore(tmp_path, dirname=DAILY_CACHE_DIRNAME),
    )


def test_last_expected_session_covers_close_and_weekend() -> None:
    friday_evening = datetime(2026, 7, 31, 18, 0, tzinfo=SEOUL)
    saturday = datetime(2026, 8, 1, 11, 0, tzinfo=SEOUL)
    monday_open = datetime(2026, 8, 3, 10, 0, tzinfo=SEOUL)
    monday_close = datetime(2026, 8, 3, 15, 30, tzinfo=SEOUL)
    assert last_expected_session_date(friday_evening) == date(2026, 7, 31)
    assert last_expected_session_date(saturday) == date(2026, 7, 31)
    assert last_expected_session_date(monday_open) == date(2026, 7, 31)
    assert last_expected_session_date(monday_close) == date(2026, 8, 3)


def test_first_load_fetches_full_history_and_caches(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 18, 0, tzinfo=SEOUL)
    provider = FakeDailyProvider(
        _daily_bars([100.0 + i for i in range(250)], end=date(2026, 7, 31)),
    )
    source = _source(tmp_path, provider)

    bars = source.load("111770", now=now)

    assert bars is not None
    assert len(bars) == 250
    assert provider.requests[0].target_bars == FULL_HISTORY_TARGET_BARS
    assert provider.requests[0].timeframe == "1D"
    assert (tmp_path / DAILY_CACHE_DIRNAME / "111770_1D.csv").exists()

    # Fresh cache serves the second load without another KIS call.
    again = source.load("111770", now=now)
    assert again is not None
    assert len(again) == 250
    assert len(provider.requests) == 1


def test_stale_cache_triggers_incremental_refresh(tmp_path: Path) -> None:
    stale_now = datetime(2026, 7, 30, 18, 0, tzinfo=SEOUL)
    fresh_now = datetime(2026, 7, 31, 18, 0, tzinfo=SEOUL)
    old = _daily_bars([100.0] * 240, end=date(2026, 7, 30))
    provider = FakeDailyProvider(old)
    source = _source(tmp_path, provider)
    assert source.load("111770", now=stale_now) is not None

    provider.bars = _daily_bars([100.0] * 5, end=date(2026, 7, 31))
    refreshed = source.load("111770", now=fresh_now)

    assert refreshed is not None
    assert provider.requests[-1].target_bars == REFRESH_TARGET_BARS
    # Merge keeps the old depth and appends the newly completed session.
    assert len(refreshed) == 241
    assert refreshed[-1].time_utc.astimezone(SEOUL).date() == date(2026, 7, 31)


class RateLimitedThenFullProvider(FakeDailyProvider):
    """First fetch is cut by the KIS rate limit; the retry pages deeper."""

    def __init__(
        self,
        shallow: tuple[OhlcvBar, ...],
        deep: tuple[OhlcvBar, ...],
    ) -> None:
        super().__init__(deep)
        self.shallow = shallow

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            return _result(
                self.shallow,
                request,
                stop_reason=HistoricalStopReason.RATE_LIMITED,
            )
        return _result(self.bars, request)


def test_rate_limited_fetch_retries_and_merges(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 18, 0, tzinfo=SEOUL)
    deep = _daily_bars([100.0] * 400, end=date(2026, 7, 31))
    provider = RateLimitedThenFullProvider(deep[-120:], deep)
    sleeps: list[bool] = []
    source = KisDailyQuerySource(
        provider=provider,
        cache_store=FileBarSeriesStore(tmp_path, dirname=DAILY_CACHE_DIRNAME),
        retry_sleep=lambda: sleeps.append(True),
    )

    bars = source.load("111770", now=now)

    assert bars is not None
    assert len(bars) == 400
    assert len(provider.requests) == 2
    assert sleeps == [True]


def test_fetch_error_serves_stale_cache(tmp_path: Path) -> None:
    stale_now = datetime(2026, 7, 30, 18, 0, tzinfo=SEOUL)
    fresh_now = datetime(2026, 7, 31, 18, 0, tzinfo=SEOUL)
    seeded = FakeDailyProvider(_daily_bars([100.0] * 210, end=date(2026, 7, 30)))
    assert _source(tmp_path, seeded).load("111770", now=stale_now) is not None

    failing = _source(tmp_path, ErrorDailyProvider(()))
    stale = failing.load("111770", now=fresh_now)

    assert stale is not None
    assert len(stale) == 210


def test_fixture_provider_yields_nothing(tmp_path: Path) -> None:
    source = _source(tmp_path, FixtureOhlcvProvider())
    assert source.load("111770") is None


class _EchoQueryService:
    def ask(
        self,
        *,
        symbol: str,
        timeframe: str,
        question: str,
        bars: tuple[OhlcvBar, ...],
    ) -> ChartQueryAnswer:
        del question
        return ChartQueryAnswer(
            answer=f"{symbol} {timeframe} {len(bars)}봉 기준 서술",
            model="fake-model",
        )


def _client(tmp_path: Path, provider: object) -> tuple[TestClient, dict[str, str]]:
    token = tmp_path.name
    settings = Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        api_token=token,
    )
    app = create_app(
        settings,
        provider=provider,  # type: ignore[arg-type]
        query_service=_EchoQueryService(),  # type: ignore[arg-type]
    )
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_query_endpoint_serves_daily_via_kis_fallback(tmp_path: Path) -> None:
    provider = FakeDailyProvider(
        _daily_bars([100.0 + i for i in range(250)], end=date(2026, 7, 31)),
    )
    client, headers = _client(tmp_path, provider)
    with client:
        response = client.post(
            "/api/queries",
            json={
                "symbol": "111770",
                "timeframe": "1D",
                "question": "골든크로스 확률은?",
            },
            headers=headers,
        )
    assert response.status_code == 201
    body = response.json()["query"]
    assert body["status"] == "answered"
    assert body["bar_count"] == 250
    assert (tmp_path / DAILY_CACHE_DIRNAME / "111770_1D.csv").exists()


def test_query_endpoint_daily_unavailable_without_kis(tmp_path: Path) -> None:
    client, headers = _client(tmp_path, FixtureOhlcvProvider())
    with client:
        response = client.post(
            "/api/queries",
            json={"symbol": "111770", "timeframe": "1D", "question": "질문"},
            headers=headers,
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "daily_history_unavailable"
