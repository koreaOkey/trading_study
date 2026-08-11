import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
import pytest

from fractal_journal.kis_auth import AccessToken, TokenCache
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalDataStatus,
    HistoricalStopReason,
)
from fractal_journal.toss_auth import ClientId, ClientSecret, TossCredentials
from fractal_journal.toss_daily_history import (
    DAILY_PRICE_BASIS,
    DAILY_TR_ID,
    TossDailyPageFetcher,
    collect_daily_bars,
)
from fractal_journal.toss_history import CANDLES_ENDPOINT
from fractal_journal.toss_models import TossCandle, TossCandlesPage
from fractal_journal.toss_provider import TossOhlcvProvider

SEOUL = ZoneInfo("Asia/Seoul")
INTRADAY_DECISION_TIME = datetime.fromisoformat("2026-07-09T09:09:00+09:00")
CLOSE_DECISION_TIME = datetime.fromisoformat("2026-07-09T15:30:00+09:00")


def test_daily_page_request_uses_1d_interval_and_before_cursor() -> None:
    # Given
    captured_params: dict[str, str] = {}
    captured_paths: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured_paths.append(request.url.path)
        captured_params.update(request.url.params)
        return httpx2.Response(200, json={"result": {"candles": []}})

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        fetch_page = TossDailyPageFetcher(
            client=client,
            token=AccessToken("token"),
            symbol="005930",
        )

        # When
        _ = fetch_page(CLOSE_DECISION_TIME.isoformat())

    # Then
    assert captured_paths == [CANDLES_ENDPOINT]
    assert captured_params["symbol"] == "005930"
    assert captured_params["interval"] == "1d"
    assert captured_params["count"] == "200"
    assert captured_params["before"] == "2026-07-09T15:30:00+09:00"
    assert captured_params["adjusted"] == "true"


def test_daily_bars_are_restamped_at_session_close_and_exclude_forming_bar() -> None:
    # Given
    page = _page(*_daily_candles(date(2026, 7, 9), count=3), next_before=None)

    # When
    result = collect_daily_bars(
        _request(decision_time=INTRADAY_DECISION_TIME, max_pages=1),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert [bar.time_exchange[:10] for bar in result.bars] == [
        "2026-07-07",
        "2026-07-08",
    ]
    assert result.provenance.future_bars_filtered == 1
    assert all(
        bar.time_exchange.endswith("15:30:00+09:00") for bar in result.bars
    )


def test_daily_bars_include_decision_date_bar_at_session_close() -> None:
    # Given
    page = _page(*_daily_candles(date(2026, 7, 9), count=3), next_before=None)

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert [bar.time_exchange[:10] for bar in result.bars] == [
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
    ]
    assert result.provenance.future_bars_filtered == 0
    assert result.bars[-1].time_utc == CLOSE_DECISION_TIME.astimezone(UTC)


def test_daily_pages_backward_until_target_reached() -> None:
    # Given
    second_cursor = "2026-03-30T00:00:00.000+09:00"
    pages = {
        CLOSE_DECISION_TIME.isoformat(): _page(
            *_daily_candles(date(2026, 7, 9), count=101),
            next_before=second_cursor,
        ),
        second_cursor: _page(
            *_daily_candles(date(2026, 3, 29), count=100),
            next_before="2025-12-19T00:00:00.000+09:00",
        ),
    }
    cursors: list[str] = []
    throttle_calls = 0

    def fetch_page(cursor: str) -> TossCandlesPage:
        cursors.append(cursor)
        return pages[cursor]

    def throttle() -> None:
        nonlocal throttle_calls
        throttle_calls += 1

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME),
        fetch_page,
        throttle,
    )

    # Then
    assert result.status is HistoricalDataStatus.OK
    assert result.provenance.stop_reason is HistoricalStopReason.TARGET_REACHED
    assert len(result.bars) == 201
    assert cursors == [CLOSE_DECISION_TIME.isoformat(), second_cursor]
    assert throttle_calls == 1
    assert result.bars[-1].time_utc == CLOSE_DECISION_TIME.astimezone(UTC)


def test_daily_listing_start_stops_with_partial_data() -> None:
    # Given
    page = _page(*_daily_candles(date(2026, 7, 9), count=3), next_before=None)

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=5),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.EMPTY_PAGE
    assert result.provenance.page_count == 1


@pytest.mark.parametrize(
    ("status_code", "error_code", "expected_status", "expected_reason"),
    [
        (
            500,
            "internal-error",
            HistoricalDataStatus.API_ERROR,
            HistoricalStopReason.API_ERROR,
        ),
        (
            429,
            "rate-limited",
            HistoricalDataStatus.RATE_LIMITED,
            HistoricalStopReason.RATE_LIMITED,
        ),
    ],
)
def test_daily_collection_returns_typed_api_failure_status(
    status_code: int,
    error_code: str,
    expected_status: HistoricalDataStatus,
    expected_reason: HistoricalStopReason,
) -> None:
    # Given
    page = TossCandlesPage(status_code=status_code, error_code=error_code)

    # When
    result = collect_daily_bars(
        _request(),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert result.status is expected_status
    assert result.provenance.stop_reason is expected_reason
    assert result.provenance.api_message_codes == (error_code,)


def test_daily_provenance_records_daily_source_and_price_basis() -> None:
    # Given
    page = _page(*_daily_candles(date(2026, 7, 9), count=3), next_before=None)

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert result.provider == "toss"
    assert result.provenance.endpoint == CANDLES_ENDPOINT
    assert result.provenance.tr_id == DAILY_TR_ID
    assert result.provenance.source_timeframe_minutes == 1440
    assert result.provenance.aggregated_timeframe_minutes == 1440
    assert result.provenance.price_basis == DAILY_PRICE_BASIS


def test_provider_routes_daily_timeframe_to_1d_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path, "cached-value")
    intervals: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        intervals.append(request.url.params["interval"])
        return httpx2.Response(
            200,
            json=_envelope_json(date(2026, 7, 9), count=3),
        )

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_historical_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
    )

    # Then
    assert intervals == ["1d"]
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert len(result.bars) == 3


def test_provider_refreshes_token_once_for_daily_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path, "stale-value")
    paths: list[str] = []
    authorizations: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if request.url.path == "/oauth2/token":
            return httpx2.Response(
                200,
                json={"access_token": "fresh-value", "expires_in": 86399},
            )
        authorization = request.headers["authorization"]
        authorizations.append(authorization)
        if authorization == "Bearer stale-value":
            return httpx2.Response(
                401,
                json={"error": {"code": "invalid-token", "message": "expired"}},
            )
        return httpx2.Response(
            200,
            json=_envelope_json(date(2026, 7, 9), count=3),
        )

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_historical_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
    )

    # Then
    assert paths == [CANDLES_ENDPOINT, "/oauth2/token", CANDLES_ENDPOINT]
    assert authorizations == ["Bearer stale-value", "Bearer fresh-value"]
    assert result.provenance.api_message_codes == ("ok",)


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    cache_path: Path,
    handle: Callable[[httpx2.Request], httpx2.Response],
) -> TossOhlcvProvider:
    transport = httpx2.MockTransport(handle)

    def create_client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=transport)

    monkeypatch.setattr(
        "fractal_journal.toss_provider.create_toss_client",
        create_client,
    )
    credentials = TossCredentials(
        client_id=ClientId("id"),
        client_secret=ClientSecret("secret"),
    )
    return TossOhlcvProvider(credentials, cache_path, history_throttle=lambda: None)


def _cached_token(tmp_path: Path, value: str) -> Path:
    cache_path = tmp_path / "toss-token.json"
    cache = TokenCache(
        access_token=AccessToken(value),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    return cache_path


def _request(
    *,
    decision_time: datetime = INTRADAY_DECISION_TIME,
    max_pages: int = 256,
) -> HistoricalBarsRequest:
    return HistoricalBarsRequest(
        provider_symbol="005930",
        decision_time_exchange=decision_time,
        timeframe="1D",
        max_pages=max_pages,
    )


def _page(
    *candles: TossCandle,
    next_before: str | None = None,
) -> TossCandlesPage:
    return TossCandlesPage(
        status_code=200,
        candles=candles,
        next_before=next_before,
    )


def _daily_candles(end: date, *, count: int) -> tuple[TossCandle, ...]:
    # Newest first, timestamped at exchange-local midnight like the real API.
    return tuple(
        TossCandle.model_validate(
            _candle_json(end - timedelta(days=offset), count - offset),
        )
        for offset in range(count)
    )


def _envelope_json(end: date, *, count: int) -> dict[str, Any]:
    return {
        "result": {
            "candles": [
                _candle_json(end - timedelta(days=offset), count - offset)
                for offset in range(count)
            ],
            "nextBefore": None,
        },
    }


def _candle_json(day: date, close_offset: int) -> dict[str, Any]:
    close = 100.0 + close_offset
    return {
        "timestamp": f"{day.isoformat()}T00:00:00.000+09:00",
        "openPrice": close - 1,
        "highPrice": close + 1,
        "lowPrice": close - 2,
        "closePrice": close,
        "volume": 10200.0,
        "currency": "KRW",
    }
