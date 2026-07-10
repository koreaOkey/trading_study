from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fractal_journal.indicators import (
    MaCrossoverEvidenceContext,
    calculate_ma_crossover_evidence,
)
from fractal_journal.provider import OhlcvBar
from fractal_journal.schemas import EvidenceDataStatus, GapTrend

DECISION_TIME = datetime(2026, 7, 9, 4, 20, tzinfo=UTC)


def test_calculates_current_previous_and_signed_gap_from_known_bars() -> None:
    # Given
    bars = _bars([Decimal(100)] * 200 + [Decimal(200)])

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    assert evidence.data_status is EvidenceDataStatus.READY
    assert evidence.bar_count == 201
    assert evidence.close == Decimal(200)
    assert evidence.volume == Decimal(1)
    assert evidence.sma_50.value == Decimal(102)
    assert evidence.sma_50.previous_value == Decimal(100)
    assert evidence.sma_50.slope_pct == Decimal(2)
    assert evidence.sma_200.value == Decimal("100.5")
    assert evidence.sma_200.previous_value == Decimal(100)
    assert evidence.sma_200.slope_pct == Decimal("0.5")
    assert evidence.vwma_100.value == Decimal(101)
    assert evidence.vwma_100.previous_value == Decimal(100)
    assert evidence.vwma_100.slope_pct == Decimal(1)
    assert evidence.sma_50.distance_from_close_pct == Decimal(9800) / Decimal(102)
    assert evidence.sma_50_to_sma_200_gap_pct == Decimal(150) / Decimal("100.5")
    assert evidence.gap_trend is GapTrend.WIDENING
    assert evidence.null_reasons == ()


def test_signed_gap_expresses_sma50_below_sma200() -> None:
    # Given
    bars = _bars([Decimal(200)] * 200 + [Decimal(100)])

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    gap_pct = evidence.sma_50_to_sma_200_gap_pct
    assert gap_pct is not None
    assert gap_pct == Decimal(-150) / Decimal("199.5")
    assert gap_pct < 0
    assert evidence.gap_trend is GapTrend.WIDENING


def test_equal_smas_have_zero_gap_and_flat_trend() -> None:
    # Given
    bars = _bars([Decimal(100)] * 201)

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    assert evidence.sma_50_to_sma_200_gap_pct == Decimal(0)
    assert evidence.gap_trend is GapTrend.FLAT


def test_gap_trend_reports_narrowing_from_absolute_ma_distance() -> None:
    # Given
    bars = _bars([Decimal(100)] * 150 + [Decimal(200)] * 50 + [Decimal(100)])

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    assert evidence.sma_50.value == Decimal(198)
    assert evidence.sma_50.previous_value == Decimal(200)
    assert evidence.gap_trend is GapTrend.NARROWING


def test_vwma_uses_volume_weights() -> None:
    # Given
    bars = _bars([Decimal(100)] * 200)
    high_volume_close = _bar(200, Decimal(200), volume=100)

    # When
    evidence = calculate_ma_crossover_evidence((*bars, high_volume_close), _context())

    # Then
    assert evidence.vwma_100.value == Decimal(29900) / Decimal(199)
    assert evidence.vwma_100.previous_value == Decimal(100)


def test_normalizes_order_and_ignores_contaminated_bars() -> None:
    # Given
    valid = _bars([Decimal(100)] * 200 + [Decimal(200)])
    future = _bar(202, Decimal(999999))
    malformed = _bar(203, Decimal(888888), time_exchange="not-a-timestamp")
    contaminated = (*reversed(valid), valid[-1], future, malformed)

    # When
    evidence = calculate_ma_crossover_evidence(contaminated, _context())

    # Then
    assert evidence.bar_count == 201
    assert evidence.close == Decimal(200)
    assert evidence.sma_50.value == Decimal(102)
    assert evidence.last_bar_time_exchange == valid[-1].time_utc


def test_requires_both_timestamps_to_be_at_or_before_decision_time() -> None:
    # Given
    valid = _bars([Decimal(100)] * 201)
    future_exchange = _bar(
        10,
        Decimal(999999),
        time_exchange=(DECISION_TIME + timedelta(minutes=1)).isoformat(),
    )
    past_exchange = (DECISION_TIME - timedelta(minutes=1)).isoformat()
    future_utc = _bar(202, Decimal(888888), time_exchange=past_exchange)

    # When
    evidence = calculate_ma_crossover_evidence(
        (*valid, future_exchange, future_utc),
        _context(),
    )

    # Then
    assert evidence.bar_count == 201
    assert evidence.sma_50.value == Decimal(100)


def test_zero_volume_window_returns_null_vwma_reason() -> None:
    # Given
    bars = _bars([Decimal(100)] * 201, volume=0)

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    assert evidence.data_status is EvidenceDataStatus.PARTIAL
    assert evidence.vwma_100.value is None
    assert evidence.vwma_100.previous_value is None
    assert evidence.vwma_100.null_reason == "vwma_100_zero_volume"
    assert evidence.null_reasons == ("vwma_100_zero_volume",)


def test_two_hundred_bars_leave_previous_sma200_unavailable() -> None:
    # Given
    bars = _bars([Decimal(100)] * 200)

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    assert evidence.data_status is EvidenceDataStatus.PARTIAL
    assert evidence.sma_200.value == Decimal(100)
    assert evidence.sma_200.previous_value is None
    assert evidence.sma_200.bars_used == 200
    assert evidence.sma_200.null_reason == "sma_200_requires_201_bars"
    assert evidence.gap_trend is None


def test_no_eligible_bars_returns_unavailable_evidence() -> None:
    # Given
    future = (_bar(202, Decimal(100)),)

    # When
    evidence = calculate_ma_crossover_evidence(future, _context())

    # Then
    assert evidence.data_status is EvidenceDataStatus.UNAVAILABLE
    assert evidence.bar_count == 0
    assert evidence.last_bar_time_exchange is None
    assert evidence.close is None
    assert evidence.volume is None
    assert evidence.null_reasons[0] == "no_eligible_bars"


def test_provider_partial_status_prevents_ready_evidence() -> None:
    # Given
    bars = _bars([Decimal(100)] * 201)

    # When
    evidence = calculate_ma_crossover_evidence(
        bars,
        _context(provider_data_status="partial_data"),
    )

    # Then
    assert evidence.data_status is EvidenceDataStatus.PARTIAL
    assert evidence.null_reasons == ("provider_data_status:partial_data",)


def _context(provider_data_status: str = "ok") -> MaCrossoverEvidenceContext:
    return MaCrossoverEvidenceContext(
        provider="kis",
        provider_symbol="214450",
        timeframe="1m",
        decision_time_exchange=DECISION_TIME,
        provider_data_status=provider_data_status,
    )


def _bars(closes: list[Decimal], volume: int = 1) -> tuple[OhlcvBar, ...]:
    return tuple(
        _bar(index, close, volume=volume) for index, close in enumerate(closes)
    )


def _bar(
    index: int,
    close: Decimal,
    *,
    volume: int = 1,
    time_exchange: str | None = None,
) -> OhlcvBar:
    time_utc = DECISION_TIME - timedelta(minutes=200 - index)
    return OhlcvBar(
        time_utc=time_utc,
        time_exchange=time_exchange or time_utc.isoformat(),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
    )
