from datetime import datetime, timedelta

import httpx2
import pytest
from pydantic import ValidationError

from fractal_journal.kis_auth import AccessToken, AppKey, AppSecret, KisCredentials
from fractal_journal.kis_provider import (
    KisBar,
    KisHistoryPageFetcher,
    KisQuoteResponse,
    collect_historical_bars,
)
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalDataStatus,
    HistoricalStopReason,
)

DECISION_TIME = datetime.fromisoformat("2026-07-09T09:09:00+09:00")


def test_history_request_rejects_naive_decision_time() -> None:
    # Given
    naive_time = datetime.fromisoformat("2026-07-09T09:09:00")

    # When
    def build_request() -> HistoricalBarsRequest:
        return _request(decision_time=naive_time)

    # Then
    with pytest.raises(ValidationError):
        _ = build_request()


def test_history_returns_unsupported_without_fetching_for_non_numeric_tf() -> None:
    # Given
    calls = 0

    def fetch_page(_cursor: datetime) -> KisQuoteResponse:
        nonlocal calls
        calls += 1
        return _response()

    # When
    result = collect_historical_bars(_request(timeframe="1D"), fetch_page, lambda: None)

    # Then
    assert result.provider == "kis"
    assert result.status is HistoricalDataStatus.UNSUPPORTED_TIMEFRAME
    assert result.provenance.stop_reason is HistoricalStopReason.UNSUPPORTED_TIMEFRAME
    assert calls == 0


def test_history_page_request_uses_exact_cursor_and_past_data_flag() -> None:
    # Given
    captured_params: dict[str, str] = {}

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured_params.update(request.url.params)
        return httpx2.Response(
            200,
            json={"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok"},
        )

    credentials = KisCredentials(app_key=AppKey("key"), app_secret=AppSecret("secret"))
    with httpx2.Client(
        base_url="https://kis.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        fetch_page = KisHistoryPageFetcher(
            client=client,
            token=AccessToken("token"),
            credentials=credentials,
            request=_request(),
        )

        # When
        _ = fetch_page(DECISION_TIME)

    # Then
    assert captured_params["FID_INPUT_DATE_1"] == "20260709"
    assert captured_params["FID_INPUT_HOUR_1"] == "090900"
    assert captured_params["FID_PW_DATA_INCU_YN"] == "Y"


def test_history_pages_backward_and_aggregates_five_minute_bars() -> None:
    # Given
    pages = {
        DECISION_TIME: _response(*_minute_bars(DECISION_TIME, count=5)),
        DECISION_TIME - timedelta(minutes=5): _response(
            *_minute_bars(DECISION_TIME - timedelta(minutes=5), count=5),
        ),
    }
    cursors: list[datetime] = []

    def fetch_page(cursor: datetime) -> KisQuoteResponse:
        cursors.append(cursor)
        return pages[cursor]

    # When
    result = collect_historical_bars(
        _request(timeframe="5", max_pages=2),
        fetch_page,
        lambda: None,
    )

    # Then
    assert cursors == [DECISION_TIME, DECISION_TIME - timedelta(minutes=5)]
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.PAGE_CAP_REACHED
    assert [bar.time_exchange[11:16] for bar in result.bars] == ["09:00", "09:05"]
    assert result.bars[0].open == 100
    assert result.bars[0].high == 106
    assert result.bars[0].low == 99
    assert result.bars[0].close == 105
    assert result.bars[0].volume == 510


def test_history_excludes_future_bars_and_keeps_partial_decision_bucket() -> None:
    # Given
    response = _response(
        *_minute_bars(DECISION_TIME + timedelta(minutes=1), count=7),
    )

    # When
    result = collect_historical_bars(
        _request(timeframe="5", max_pages=1),
        lambda _cursor: response,
        lambda: None,
    )

    # Then
    assert result.bars[-1].time_exchange[11:16] == "09:05"
    assert result.bars[-1].close == 106
    assert all(bar.time_utc <= DECISION_TIME for bar in result.bars)
    assert result.provenance.future_bars_filtered == 1


def test_history_deduplicates_and_stops_when_page_cursor_does_not_progress() -> None:
    # Given
    duplicate_page = _response(*_minute_bars(DECISION_TIME, count=5))
    throttle_calls = 0

    def throttle() -> None:
        nonlocal throttle_calls
        throttle_calls += 1

    # When
    result = collect_historical_bars(
        _request(max_pages=5),
        lambda _cursor: duplicate_page,
        throttle,
    )

    # Then
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.NO_PROGRESS
    assert result.provenance.page_count == 2
    assert result.provenance.raw_bar_count == 10
    assert result.provenance.unique_minute_bar_count == 5
    assert throttle_calls == 1


def test_history_returns_empty_when_first_page_has_no_bars() -> None:
    # Given
    response = _response()

    # When
    result = collect_historical_bars(
        _request(),
        lambda _cursor: response,
        lambda: None,
    )

    # Then
    assert result.status is HistoricalDataStatus.EMPTY_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.EMPTY_PAGE


@pytest.mark.parametrize(
    ("message_code", "expected_status", "expected_reason"),
    [
        (
            "API001",
            HistoricalDataStatus.API_ERROR,
            HistoricalStopReason.API_ERROR,
        ),
        (
            "EGW00201",
            HistoricalDataStatus.RATE_LIMITED,
            HistoricalStopReason.RATE_LIMITED,
        ),
    ],
)
def test_history_returns_typed_api_failure_status(
    message_code: str,
    expected_status: HistoricalDataStatus,
    expected_reason: HistoricalStopReason,
) -> None:
    # Given
    response = _response(rt_cd="1", msg_cd=message_code)

    # When
    result = collect_historical_bars(
        _request(),
        lambda _cursor: response,
        lambda: None,
    )

    # Then
    assert result.status is expected_status
    assert result.provenance.stop_reason is expected_reason
    assert result.provenance.api_message_codes == (message_code,)


def test_history_stops_after_target_aggregate_bar_count() -> None:
    # Given
    decision_time = datetime.fromisoformat("2026-07-09T15:30:00+09:00")
    first_page = _response(*_minute_bars(decision_time, count=101))
    second_cursor = decision_time - timedelta(minutes=101)
    second_page = _response(*_minute_bars(second_cursor, count=100))
    pages = iter((first_page, second_page))
    throttle_calls = 0

    def fetch_page(_cursor: datetime) -> KisQuoteResponse:
        return next(pages)

    def throttle() -> None:
        nonlocal throttle_calls
        throttle_calls += 1

    # When
    result = collect_historical_bars(
        _request(decision_time=decision_time),
        fetch_page,
        throttle,
    )

    # Then
    assert result.status is HistoricalDataStatus.OK
    assert result.provenance.stop_reason is HistoricalStopReason.TARGET_REACHED
    assert len(result.bars) == 201
    assert result.bars[-1].time_utc == decision_time
    assert throttle_calls == 1


def test_history_aggregation_resets_at_each_exchange_date() -> None:
    # Given
    prior_day = datetime.fromisoformat("2026-07-08T15:29:00+09:00")
    response = _response(
        *_minute_bars(DECISION_TIME, count=5),
        *_minute_bars(prior_day, count=5),
    )

    # When
    result = collect_historical_bars(
        _request(timeframe="5", max_pages=1),
        lambda _cursor: response,
        lambda: None,
    )

    # Then
    assert [bar.time_exchange[:16] for bar in result.bars] == [
        "2026-07-08T15:25",
        "2026-07-09T09:05",
    ]


def _request(
    *,
    decision_time: datetime = DECISION_TIME,
    timeframe: str = "1",
    max_pages: int = 256,
) -> HistoricalBarsRequest:
    return HistoricalBarsRequest(
        provider_symbol="214450",
        decision_time_exchange=decision_time,
        timeframe=timeframe,
        max_pages=max_pages,
    )


def _response(
    *bars: KisBar,
    rt_cd: str = "0",
    msg_cd: str = "MCA00000",
) -> KisQuoteResponse:
    return KisQuoteResponse(
        rt_cd=rt_cd,
        msg_cd=msg_cd,
        msg1="ok" if rt_cd == "0" else "error",
        output2=bars,
    )


def _minute_bars(end: datetime, *, count: int) -> tuple[KisBar, ...]:
    return tuple(
        _bar(
            end - timedelta(minutes=offset),
            close=100 + count - offset,
        )
        for offset in range(count)
    )


def _bar(exchange_time: datetime, *, close: int) -> KisBar:
    return KisBar(
        stck_bsop_date=exchange_time.strftime("%Y%m%d"),
        stck_cntg_hour=exchange_time.strftime("%H%M%S"),
        stck_oprc=str(close - 1),
        stck_hgpr=str(close + 1),
        stck_lwpr=str(close - 2),
        stck_prpr=str(close),
        cntg_vol="102",
    )

