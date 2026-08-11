from datetime import datetime, timedelta
from decimal import Decimal

import httpx2
import pytest

from fractal_journal.kis_auth import AccessToken
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalDataStatus,
    HistoricalStopReason,
)
from fractal_journal.toss_history import (
    TossHistoryPageFetcher,
    collect_historical_bars,
)
from fractal_journal.toss_models import (
    TossCandle,
    TossCandlesPage,
    parse_toss_candles_page,
    to_ohlcv_bar,
)

DECISION_TIME = datetime.fromisoformat("2026-07-09T09:09:00+09:00")
CLOSE_DECISION_TIME = datetime.fromisoformat("2026-07-09T15:30:00+09:00")


def test_parse_candles_page_normalizes_camelcase_payload() -> None:
    # Given
    response = httpx2.Response(
        200,
        json={
            "result": {
                "candles": [
                    {
                        "timestamp": "2026-07-09T09:09:00.000+09:00",
                        "openPrice": 71000.0,
                        "highPrice": 71200.0,
                        "lowPrice": 70900.5,
                        "closePrice": 71100.0,
                        "volume": 12345.0,
                        "currency": "KRW",
                    },
                ],
                "nextBefore": "2026-07-09T09:08:00.000+09:00",
            },
        },
    )

    # When
    page = parse_toss_candles_page(response)

    # Then
    assert page.error_code is None
    assert page.next_before == "2026-07-09T09:08:00.000+09:00"
    candle = page.candles[0]
    assert candle.open_price == Decimal("71000.0")
    assert candle.low_price == Decimal("70900.5")
    bar = to_ohlcv_bar(candle)
    assert bar.time_exchange == "2026-07-09T09:09:00+09:00"
    assert bar.close == Decimal("71100.0")
    assert bar.volume == 12345


def test_parse_candles_page_flattens_error_envelope() -> None:
    # Given
    response = httpx2.Response(
        401,
        json={"error": {"code": "invalid-token", "message": "expired"}},
    )

    # When
    page = parse_toss_candles_page(response)

    # Then
    assert page.status_code == 401
    assert page.error_code == "invalid-token"
    assert page.candles == ()


def test_page_fetcher_sends_symbol_interval_count_before_and_bearer() -> None:
    # Given
    captured_params: dict[str, str] = {}
    captured_headers: dict[str, str] = {}

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured_params.update(request.url.params)
        captured_headers["authorization"] = request.headers["authorization"]
        return httpx2.Response(200, json={"result": {"candles": []}})

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        fetch_page = TossHistoryPageFetcher(
            client=client,
            token=AccessToken("token"),
            symbol="005930",
        )

        # When
        _ = fetch_page(DECISION_TIME.isoformat())

    # Then
    assert captured_params["symbol"] == "005930"
    assert captured_params["interval"] == "1m"
    assert captured_params["count"] == "200"
    assert captured_params["before"] == "2026-07-09T09:09:00+09:00"
    assert captured_params["adjusted"] == "true"
    assert captured_headers["authorization"] == "Bearer token"


def test_history_first_cursor_is_decision_time_and_follows_next_before() -> None:
    # Given
    second_cursor = (DECISION_TIME - timedelta(minutes=5)).isoformat()
    pages = {
        DECISION_TIME.isoformat(): _page(
            *_minute_candles(DECISION_TIME, count=5),
            next_before=second_cursor,
        ),
        second_cursor: _page(
            *_minute_candles(DECISION_TIME - timedelta(minutes=5), count=5),
            next_before=None,
        ),
    }
    cursors: list[str] = []

    def fetch_page(cursor: str) -> TossCandlesPage:
        cursors.append(cursor)
        return pages[cursor]

    # When
    result = collect_historical_bars(_request(), fetch_page, lambda: None)

    # Then
    assert cursors == [DECISION_TIME.isoformat(), second_cursor]
    assert result.provider == "toss"
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.EMPTY_PAGE
    assert len(result.bars) == 10


def test_history_target_reached_across_pages() -> None:
    # Given
    second_cursor = (CLOSE_DECISION_TIME - timedelta(minutes=101)).isoformat()
    pages = {
        CLOSE_DECISION_TIME.isoformat(): _page(
            *_minute_candles(CLOSE_DECISION_TIME, count=101),
            next_before=second_cursor,
        ),
        second_cursor: _page(
            *_minute_candles(CLOSE_DECISION_TIME - timedelta(minutes=101), count=100),
            next_before=(CLOSE_DECISION_TIME - timedelta(minutes=201)).isoformat(),
        ),
    }
    throttle_calls = 0

    def throttle() -> None:
        nonlocal throttle_calls
        throttle_calls += 1

    # When
    result = collect_historical_bars(
        _request(decision_time=CLOSE_DECISION_TIME),
        lambda cursor: pages[cursor],
        throttle,
    )

    # Then
    assert result.status is HistoricalDataStatus.OK
    assert result.provenance.stop_reason is HistoricalStopReason.TARGET_REACHED
    assert len(result.bars) == 201
    assert result.bars[-1].time_utc == CLOSE_DECISION_TIME
    assert throttle_calls == 1


def test_history_out_of_retention_returns_empty_data() -> None:
    # Given: a window older than Toss's ~4y minute retention comes back empty.
    empty_page = _page(next_before=None)

    # When
    result = collect_historical_bars(
        _request(),
        lambda _cursor: empty_page,
        lambda: None,
    )

    # Then
    assert result.status is HistoricalDataStatus.EMPTY_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.EMPTY_PAGE
    assert result.provider == "toss"


def test_history_excludes_future_bars() -> None:
    # Given
    page = _page(
        *_minute_candles(DECISION_TIME + timedelta(minutes=1), count=7),
        next_before=None,
    )

    # When
    result = collect_historical_bars(
        _request(),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert all(bar.time_utc <= DECISION_TIME for bar in result.bars)
    assert result.provenance.future_bars_filtered == 1


def test_history_stops_when_next_before_does_not_progress() -> None:
    # Given
    def fetch_page(cursor: str) -> TossCandlesPage:
        return _page(
            *_minute_candles(DECISION_TIME, count=5),
            next_before=cursor,
        )

    # When
    result = collect_historical_bars(_request(max_pages=5), fetch_page, lambda: None)

    # Then
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.NO_PROGRESS
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
def test_history_returns_typed_api_failure_status(
    status_code: int,
    error_code: str,
    expected_status: HistoricalDataStatus,
    expected_reason: HistoricalStopReason,
) -> None:
    # Given
    page = TossCandlesPage(status_code=status_code, error_code=error_code)

    # When
    result = collect_historical_bars(
        _request(),
        lambda _cursor: page,
        lambda: None,
    )

    # Then
    assert result.status is expected_status
    assert result.provenance.stop_reason is expected_reason
    assert result.provenance.api_message_codes == (error_code,)


def test_history_returns_unsupported_without_fetching_for_non_numeric_tf() -> None:
    # Given
    calls = 0

    def fetch_page(_cursor: str) -> TossCandlesPage:
        nonlocal calls
        calls += 1
        return _page()

    # When
    result = collect_historical_bars(_request(timeframe="1D"), fetch_page, lambda: None)

    # Then
    assert result.provider == "toss"
    assert result.status is HistoricalDataStatus.UNSUPPORTED_TIMEFRAME
    assert calls == 0


def test_fetcher_retries_after_rate_limit_using_retry_after_header() -> None:
    # Given
    sleeps: list[float] = []
    request_count = 0

    def handle(_request: httpx2.Request) -> httpx2.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx2.Response(429, headers={"Retry-After": "2"})
        return httpx2.Response(
            200,
            json={"result": {"candles": [], "nextBefore": None}},
        )

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        fetch_page = TossHistoryPageFetcher(
            client=client,
            token=AccessToken("token"),
            symbol="005930",
            sleep=sleeps.append,
        )

        # When
        page = fetch_page(DECISION_TIME.isoformat())

    # Then
    assert request_count == 2
    assert sleeps == [2.0]
    assert page.error_code is None


def test_fetcher_uses_rate_limit_reset_header_when_retry_after_missing() -> None:
    # Given
    sleeps: list[float] = []
    request_count = 0

    def handle(_request: httpx2.Request) -> httpx2.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx2.Response(429, headers={"X-RateLimit-Reset": "1.5"})
        return httpx2.Response(200, json={"result": {"candles": []}})

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        fetch_page = TossHistoryPageFetcher(
            client=client,
            token=AccessToken("token"),
            symbol="005930",
            sleep=sleeps.append,
        )

        # When
        _ = fetch_page(DECISION_TIME.isoformat())

    # Then
    assert sleeps == [1.5]


def test_fetcher_gives_up_after_max_retries_with_attempt_backoff() -> None:
    # Given
    sleeps: list[float] = []
    request_count = 0

    def handle(_request: httpx2.Request) -> httpx2.Response:
        nonlocal request_count
        request_count += 1
        return httpx2.Response(429, json={"error": {"code": "rate-limited"}})

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        fetch_page = TossHistoryPageFetcher(
            client=client,
            token=AccessToken("token"),
            symbol="005930",
            sleep=sleeps.append,
        )

        # When
        page = fetch_page(DECISION_TIME.isoformat())

    # Then
    assert request_count == 5
    assert sleeps == [1.0, 2.0, 3.0, 4.0]
    assert page.status_code == 429
    assert page.error_code == "rate-limited"


def _request(
    *,
    decision_time: datetime = DECISION_TIME,
    timeframe: str = "1",
    max_pages: int = 256,
) -> HistoricalBarsRequest:
    return HistoricalBarsRequest(
        provider_symbol="005930",
        decision_time_exchange=decision_time,
        timeframe=timeframe,
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


def _minute_candles(end: datetime, *, count: int) -> tuple[TossCandle, ...]:
    # Newest first, matching the real API's descending order.
    return tuple(
        _candle(end - timedelta(minutes=offset), close=100 + count - offset)
        for offset in range(count)
    )


def _candle(exchange_time: datetime, *, close: float) -> TossCandle:
    return TossCandle.model_validate(
        {
            "timestamp": exchange_time.isoformat(timespec="milliseconds"),
            "openPrice": close - 1,
            "highPrice": close + 1,
            "lowPrice": close - 2,
            "closePrice": close,
            "volume": 102.0,
            "currency": "KRW",
        },
    )
