from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from fractal_journal.provider import MinuteWindowRequest, MinuteWindowResult, OhlcvBar
from fractal_journal.schemas import (
    CaptureId,
    CaptureRecord,
    ConfirmedMetadata,
    Decision,
    ExtractedMetadata,
    ProviderStatus,
)
from fractal_journal.scoring import score_capture


class ExpectedMetrics(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    mfe: Decimal
    mae: Decimal
    close_return: Decimal


@dataclass(frozen=True, slots=True)
class InMemoryProvider:
    window: MinuteWindowResult

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        return self.window


def test_long_scoring_uses_directional_metric_signs() -> None:
    # Given
    capture = _capture(Decision.LONG)
    provider = InMemoryProvider(_window())
    expected = ExpectedMetrics(
        mfe=Decimal("5.0000"),
        mae=Decimal("-6.0000"),
        close_return=Decimal("2.0000"),
    )

    # When
    score = score_capture(capture, provider)

    # Then
    assert score.max_favorable_excursion_pct == expected.mfe
    assert score.max_adverse_excursion_pct == expected.mae
    assert score.close_to_close_return_pct == expected.close_return


def test_short_scoring_uses_directional_metric_signs() -> None:
    # Given
    capture = _capture(Decision.SHORT)
    provider = InMemoryProvider(_window())
    expected = ExpectedMetrics(
        mfe=Decimal("6.0000"),
        mae=Decimal("-5.0000"),
        close_return=Decimal("-2.0000"),
    )

    # When
    score = score_capture(capture, provider)

    # Then
    assert score.max_favorable_excursion_pct == expected.mfe
    assert score.max_adverse_excursion_pct == expected.mae
    assert score.close_to_close_return_pct == expected.close_return


def _capture(decision: Decision) -> CaptureRecord:
    captured_at = datetime(2026, 7, 9, 1, 0, tzinfo=UTC)
    return CaptureRecord(
        id=CaptureId("capture-1"),
        created_at=captured_at,
        screenshot_sha256="abc123",
        screenshot_path="screenshots/capture-1.png",
        extracted=ExtractedMetadata(
            source_url="https://www.tradingview.com/chart/example/",
            page_title="005930 1 Samsung Electronics",
            symbol_candidate="005930",
            timeframe_candidate="1D",
            captured_at=captured_at,
        ),
        confirmed=ConfirmedMetadata(
            symbol="005930",
            provider_symbol="005930",
            market_div_code="J",
            timeframe="1D",
            decision_time_exchange="2026-07-09T10:00:00+09:00",
            provider_status=ProviderStatus.READY,
        ),
        decision=decision,
        notes="test capture",
        warnings=(),
    )


def _window() -> MinuteWindowResult:
    return MinuteWindowResult(
        endpoint="memory://bars",
        tr_id="TEST",
        request_date="20260709",
        request_hour="100000",
        price_basis="unknown_unadjusted_assumed",
        session_state="regular",
        data_status="ok",
        raw_response_sha256="abc123",
        bars=(
            _bar(0, "100", "100", "100"),
            _bar(1, "103", "96", "97"),
            _bar(2, "105", "94", "102"),
        ),
        warnings=(),
    )


def _bar(offset_minutes: int, high: str, low: str, close: str) -> OhlcvBar:
    time_utc = datetime(2026, 7, 9, 1, offset_minutes, tzinfo=UTC)
    return OhlcvBar(
        time_utc=time_utc,
        time_exchange=time_utc.isoformat(),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1000 + offset_minutes,
    )
