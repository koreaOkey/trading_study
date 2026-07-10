from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from fractal_journal.provider import (
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvProvider,
)
from fractal_journal.schemas import CaptureRecord, Decision, WarningCode

MINIMUM_SCORE_BARS = 2
NEGATIVE_ONE = Decimal(-1)
PERCENT_MULTIPLIER = Decimal(100)


class ScoreResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    capture_id: str
    score_version: str = "score.v0"
    provider_window: MinuteWindowResult
    horizon_bars: int
    max_favorable_excursion_pct: Decimal | None
    max_adverse_excursion_pct: Decimal | None
    close_to_close_return_pct: Decimal | None
    invalidation_breached: bool | None
    invalidation_breach_time_utc: datetime | None
    metric_null_reasons: tuple[str, ...]
    warnings: tuple[WarningCode, ...]


def score_capture(capture: CaptureRecord, provider: OhlcvProvider) -> ScoreResult:
    request = MinuteWindowRequest(
        provider_symbol=capture.confirmed.provider_symbol or capture.confirmed.symbol,
        market_div_code=capture.confirmed.market_div_code,
        decision_time_exchange=capture.confirmed.decision_time_exchange,
        price_basis_policy=capture.confirmed.price_basis,
    )
    window = provider.fetch_minute_window(request)
    reasons = _null_reasons(window)
    mfe, mae, close_return = _excursions(capture.decision, window)
    return ScoreResult(
        capture_id=str(capture.id),
        provider_window=window,
        horizon_bars=request.forward_minutes,
        max_favorable_excursion_pct=mfe,
        max_adverse_excursion_pct=mae,
        close_to_close_return_pct=close_return,
        invalidation_breached=None,
        invalidation_breach_time_utc=None,
        metric_null_reasons=reasons,
        warnings=(*capture.warnings, *window.warnings),
    )


def _null_reasons(window: MinuteWindowResult) -> tuple[str, ...]:
    reasons: list[str] = []
    if window.data_status == "empty_data":
        reasons.append("empty_data")
    if window.data_status == "partial_data":
        reasons.append("partial_data")
    if len(window.bars) < MINIMUM_SCORE_BARS:
        reasons.append("insufficient_bars")
    return tuple(reasons)


def _excursions(
    decision: Decision | None,
    window: MinuteWindowResult,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if len(window.bars) < MINIMUM_SCORE_BARS:
        return None, None, None
    entry = window.bars[0].close
    highs = tuple(bar.high for bar in window.bars[1:])
    lows = tuple(bar.low for bar in window.bars[1:])
    final_close = window.bars[-1].close
    match decision:
        case Decision.SHORT:
            mfe = _pct(entry, min(lows))
            mae = _pct(entry, max(highs))
            close_return = _pct(entry, final_close) * NEGATIVE_ONE
            return mfe * NEGATIVE_ONE, mae * NEGATIVE_ONE, close_return
        case Decision.LONG:
            return (
                _pct(entry, max(highs)),
                _pct(entry, min(lows)),
                _pct(entry, final_close),
            )
        case Decision.SKIP | Decision.WATCH | None:
            return None, None, None


def _pct(entry: Decimal, value: Decimal) -> Decimal:
    return ((value - entry) / entry * PERCENT_MULTIPLIER).quantize(Decimal("0.0001"))
