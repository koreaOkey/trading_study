import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
import pytest

from fractal_journal.kis_auth import (
    AccessToken,
    AppKey,
    AppSecret,
    KisCredentials,
    TokenCache,
)
from fractal_journal.kis_daily_history import (
    DAILY_ENDPOINT,
    DAILY_PRICE_BASIS,
    DAILY_TR_ID,
    KisDailyPageFetcher,
    collect_daily_bars,
)
from fractal_journal.kis_models import KisDailyBar, KisDailyChartResponse
from fractal_journal.kis_provider import KisOhlcvProvider
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalDataStatus,
    HistoricalStopReason,
)

SEOUL = ZoneInfo("Asia/Seoul")
INTRADAY_DECISION_TIME = datetime.fromisoformat("2026-07-09T09:09:00+09:00")
CLOSE_DECISION_TIME = datetime.fromisoformat("2026-07-09T15:30:00+09:00")


def test_daily_page_request_uses_daily_chart_endpoint_and_adjusted_flag() -> None:
    # Given
    captured_params: dict[str, str] = {}
    captured_paths: list[str] = []
    captured_tr_ids: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured_paths.append(request.url.path)
        captured_tr_ids.append(request.headers["tr_id"])
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
        fetch_page = KisDailyPageFetcher(
            client=client,
            token=AccessToken("token"),
            credentials=credentials,
            request=_request(),
        )

        # When
        _ = fetch_page(date(2026, 2, 20), date(2026, 7, 9))

    # Then
    assert captured_paths == [DAILY_ENDPOINT]
    assert captured_tr_ids == [DAILY_TR_ID]
    assert captured_params["FID_INPUT_DATE_1"] == "20260220"
    assert captured_params["FID_INPUT_DATE_2"] == "20260709"
    assert captured_params["FID_PERIOD_DIV_CODE"] == "D"
    assert captured_params["FID_ORG_ADJ_PRC"] == "0"


def test_daily_bars_exclude_decision_date_bar_before_session_close() -> None:
    # Given
    response = _response(*_daily_bars(date(2026, 7, 9), count=3))

    # When
    result = collect_daily_bars(
        _request(decision_time=INTRADAY_DECISION_TIME, max_pages=1),
        lambda _start, _end: response,
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
    response = _response(*_daily_bars(date(2026, 7, 9), count=3))

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
        lambda _start, _end: response,
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
    calls: list[tuple[date, date]] = []
    page_counts = iter((101, 100))
    throttle_calls = 0

    def fetch_page(start: date, end: date) -> KisDailyChartResponse:
        calls.append((start, end))
        return _response(*_daily_bars(end, count=next(page_counts)))

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
    assert len(calls) == 2
    assert throttle_calls == 1
    first_start, first_end = calls[0]
    second_start, second_end = calls[1]
    assert first_end == date(2026, 7, 9)
    assert first_start == first_end - timedelta(days=139)
    assert second_end == first_end - timedelta(days=101)
    assert second_start == second_end - timedelta(days=139)
    assert result.bars[-1].time_utc == CLOSE_DECISION_TIME.astimezone(UTC)


def test_daily_collection_stops_without_progress_on_duplicate_page() -> None:
    # Given
    duplicate = _response(*_daily_bars(date(2026, 7, 9), count=3))

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=5),
        lambda _start, _end: duplicate,
        lambda: None,
    )

    # Then
    assert result.status is HistoricalDataStatus.PARTIAL_DATA
    assert result.provenance.stop_reason is HistoricalStopReason.NO_PROGRESS
    assert result.provenance.page_count == 2
    assert result.provenance.unique_minute_bar_count == 3


def test_daily_collection_returns_empty_when_first_page_has_no_bars() -> None:
    # Given
    response = _response()

    # When
    result = collect_daily_bars(
        _request(),
        lambda _start, _end: response,
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
def test_daily_collection_returns_typed_api_failure_status(
    message_code: str,
    expected_status: HistoricalDataStatus,
    expected_reason: HistoricalStopReason,
) -> None:
    # Given
    response = _response(rt_cd="1", msg_cd=message_code)

    # When
    result = collect_daily_bars(
        _request(),
        lambda _start, _end: response,
        lambda: None,
    )

    # Then
    assert result.status is expected_status
    assert result.provenance.stop_reason is expected_reason
    assert result.provenance.api_message_codes == (message_code,)


def test_daily_provenance_records_daily_source_and_price_basis() -> None:
    # Given
    response = _response(*_daily_bars(date(2026, 7, 9), count=3))

    # When
    result = collect_daily_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
        lambda _start, _end: response,
        lambda: None,
    )

    # Then
    assert result.provenance.endpoint == DAILY_ENDPOINT
    assert result.provenance.tr_id == DAILY_TR_ID
    assert result.provenance.source_timeframe_minutes == 1440
    assert result.provenance.aggregated_timeframe_minutes == 1440
    assert result.provenance.price_basis == DAILY_PRICE_BASIS


def test_provider_routes_daily_timeframe_to_daily_chart_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path, "cached-value")
    paths: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        response = _response(*_daily_bars(date(2026, 7, 9), count=3))
        return httpx2.Response(200, json=response.model_dump(mode="json"))

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_historical_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
    )

    # Then
    assert paths == [DAILY_ENDPOINT]
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
        if request.url.path == "/oauth2/tokenP":
            return httpx2.Response(
                200,
                json={"access_token": "fresh-value", "expires_in": 3600},
            )
        authorization = request.headers["authorization"]
        authorizations.append(authorization)
        response = (
            _response(rt_cd="1", msg_cd="EGW00123")
            if authorization == "Bearer stale-value"
            else _response(*_daily_bars(date(2026, 7, 9), count=3))
        )
        return httpx2.Response(200, json=response.model_dump(mode="json"))

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_historical_bars(
        _request(decision_time=CLOSE_DECISION_TIME, max_pages=1),
    )

    # Then
    assert paths == [DAILY_ENDPOINT, "/oauth2/tokenP", DAILY_ENDPOINT]
    assert authorizations == ["Bearer stale-value", "Bearer fresh-value"]
    assert result.provenance.api_message_codes == ("MCA00000",)


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    cache_path: Path,
    handle: Callable[[httpx2.Request], httpx2.Response],
) -> KisOhlcvProvider:
    transport = httpx2.MockTransport(handle)

    def create_client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=transport)

    monkeypatch.setattr("fractal_journal.kis_provider.create_kis_client", create_client)
    credentials = KisCredentials(app_key=AppKey("key"), app_secret=AppSecret("secret"))
    return KisOhlcvProvider(credentials, cache_path, history_throttle=lambda: None)


def _cached_token(tmp_path: Path, value: str) -> Path:
    cache_path = tmp_path / "token.json"
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
        provider_symbol="214450",
        decision_time_exchange=decision_time,
        timeframe="1D",
        max_pages=max_pages,
    )


def _response(
    *bars: KisDailyBar,
    rt_cd: str = "0",
    msg_cd: str = "MCA00000",
) -> KisDailyChartResponse:
    return KisDailyChartResponse(
        rt_cd=rt_cd,
        msg_cd=msg_cd,
        msg1="ok" if rt_cd == "0" else "error",
        output2=bars,
    )


def _daily_bars(end: date, *, count: int) -> tuple[KisDailyBar, ...]:
    return tuple(
        KisDailyBar(
            stck_bsop_date=(end - timedelta(days=offset)).strftime("%Y%m%d"),
            stck_oprc=str(99 + count - offset),
            stck_hgpr=str(101 + count - offset),
            stck_lwpr=str(98 + count - offset),
            stck_clpr=str(100 + count - offset),
            acml_vol="10200",
        )
        for offset in range(count)
    )
