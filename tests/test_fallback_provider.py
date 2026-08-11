"""Toss-first fallback chain behavior."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import httpx2
import pytest

from fractal_journal.fallback_provider import (
    EmptyProviderChainError,
    FallbackOhlcvProvider,
)
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    HistoricalProvenance,
    HistoricalStopReason,
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvBar,
)

DECISION_TIME = datetime.fromisoformat("2026-07-09T15:30:00+09:00")


class StubProvider:
    def __init__(
        self,
        *,
        provider: str,
        status: HistoricalDataStatus = HistoricalDataStatus.OK,
        bar_count: int = 3,
        window_status: str = "ok",
        error: Exception | None = None,
    ) -> None:
        self.provider = provider
        self.status = status
        self.bar_count = bar_count
        self.window_status = window_status
        self.error = error
        self.historical_calls = 0
        self.window_calls = 0

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        self.window_calls += 1
        if self.error is not None:
            raise self.error
        return MinuteWindowResult(
            provider=self.provider,
            endpoint=f"fake://{self.provider}",
            tr_id="FAKE",
            request_date="20260709",
            request_hour="153000",
            price_basis=request.price_basis_policy,
            session_state="regular",
            data_status=self.window_status,
            raw_response_sha256=sha256(b"fake").hexdigest(),
            bars=_bars(self.bar_count),
            warnings=(),
        )

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        self.historical_calls += 1
        if self.error is not None:
            raise self.error
        empty = self.status is HistoricalDataStatus.EMPTY_DATA
        bars = _bars(0 if empty else self.bar_count)
        return HistoricalBarsResult(
            provider=self.provider,
            status=self.status,
            bars=bars,
            provenance=HistoricalProvenance(
                endpoint=f"fake://{self.provider}",
                tr_id="FAKE",
                request_end_exchange=request.decision_time_exchange,
                aggregated_timeframe_minutes=1,
                target_bars=request.target_bars,
                page_count=1,
                raw_bar_count=len(bars),
                unique_minute_bar_count=len(bars),
                future_bars_filtered=0,
                price_basis=request.price_basis_policy,
                api_message_codes=("ok",),
                last_cursor_exchange=None,
                raw_response_sha256=sha256(b"fake").hexdigest(),
                stop_reason=HistoricalStopReason.TARGET_REACHED,
            ),
        )


def test_first_ok_result_short_circuits_chain() -> None:
    # Given
    toss = StubProvider(provider="toss")
    kis = StubProvider(provider="kis")
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    result = chain.fetch_historical_bars(_historical_request())

    # Then
    assert result.provider == "toss"
    assert toss.historical_calls == 1
    assert kis.historical_calls == 0


def test_empty_primary_falls_back_to_secondary() -> None:
    # Given: e.g. a minute request beyond Toss's ~4y retention.
    toss = StubProvider(provider="toss", status=HistoricalDataStatus.EMPTY_DATA)
    kis = StubProvider(provider="kis")
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    result = chain.fetch_historical_bars(_historical_request())

    # Then
    assert result.provider == "kis"
    assert result.status is HistoricalDataStatus.OK
    assert toss.historical_calls == 1
    assert kis.historical_calls == 1


def test_raising_primary_falls_back_to_secondary() -> None:
    # Given
    toss = StubProvider(provider="toss", error=httpx2.ConnectError("boom"))
    kis = StubProvider(provider="kis")
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    result = chain.fetch_historical_bars(_historical_request())

    # Then
    assert result.provider == "kis"


def test_all_degraded_returns_least_degraded_result() -> None:
    # Given
    toss = StubProvider(provider="toss", status=HistoricalDataStatus.EMPTY_DATA)
    kis = StubProvider(provider="kis", status=HistoricalDataStatus.API_ERROR)
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    result = chain.fetch_historical_bars(_historical_request())

    # Then
    assert result.provider == "toss"
    assert result.status is HistoricalDataStatus.EMPTY_DATA


def test_equally_degraded_prefers_earlier_provider() -> None:
    # Given
    toss = StubProvider(provider="toss", status=HistoricalDataStatus.EMPTY_DATA)
    kis = StubProvider(provider="kis", status=HistoricalDataStatus.EMPTY_DATA)
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    result = chain.fetch_historical_bars(_historical_request())

    # Then
    assert result.provider == "toss"


def test_all_raising_reraises_last_error() -> None:
    # Given
    toss = StubProvider(provider="toss", error=httpx2.ConnectError("toss down"))
    kis = StubProvider(provider="kis", error=httpx2.ConnectError("kis down"))
    chain = FallbackOhlcvProvider((toss, kis))

    # When / Then
    with pytest.raises(httpx2.ConnectError, match="kis down"):
        _ = chain.fetch_historical_bars(_historical_request())


def test_minute_window_falls_back_on_api_error() -> None:
    # Given
    toss = StubProvider(provider="toss", window_status="api_error")
    kis = StubProvider(provider="kis")
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    window = chain.fetch_minute_window(_window_request())

    # Then
    assert window.provider == "kis"
    assert window.data_status == "ok"
    assert toss.window_calls == 1
    assert kis.window_calls == 1


def test_minute_window_first_ok_short_circuits() -> None:
    # Given
    toss = StubProvider(provider="toss")
    kis = StubProvider(provider="kis")
    chain = FallbackOhlcvProvider((toss, kis))

    # When
    window = chain.fetch_minute_window(_window_request())

    # Then
    assert window.provider == "toss"
    assert kis.window_calls == 0


def test_empty_chain_is_rejected() -> None:
    # When / Then
    with pytest.raises(EmptyProviderChainError):
        _ = FallbackOhlcvProvider(())


def _historical_request() -> HistoricalBarsRequest:
    return HistoricalBarsRequest(
        provider_symbol="005930",
        decision_time_exchange=DECISION_TIME,
        timeframe="1",
    )


def _window_request() -> MinuteWindowRequest:
    return MinuteWindowRequest(
        provider_symbol="005930",
        decision_time_exchange=DECISION_TIME.isoformat(),
    )


def _bars(count: int) -> tuple[OhlcvBar, ...]:
    return tuple(
        _bar(DECISION_TIME - timedelta(minutes=count - 1 - offset))
        for offset in range(count)
    )


def _bar(exchange_time: datetime) -> OhlcvBar:
    value = Decimal(100)
    return OhlcvBar(
        time_utc=exchange_time.astimezone(UTC),
        time_exchange=exchange_time.isoformat(),
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=1000,
    )
