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


def _context(
    provider_data_status: str = "ok",
    supply_zone_price: Decimal | None = None,
) -> MaCrossoverEvidenceContext:
    return MaCrossoverEvidenceContext(
        provider="kis",
        provider_symbol="214450",
        timeframe="1m",
        decision_time_exchange=DECISION_TIME,
        provider_data_status=provider_data_status,
        supply_zone_price=supply_zone_price,
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


def test_thresholds_solve_next_bar_structure_conditions_exactly() -> None:
    # Given: 200 flat bars at 100 then one at 200 (SMA50 102 > SMA200 100.5).
    bars = _bars([Decimal(100)] * 200 + [Decimal(200)])

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    thresholds = evidence.thresholds
    assert thresholds is not None
    assert thresholds.basis == "cross_hold"
    # Verify by simulation: a close exactly at the threshold keeps
    # SMA50 >= SMA200 on the next bar, one tick below breaks it.
    closes = [Decimal(100)] * 200 + [Decimal(200)]
    assert thresholds.cross_min_close is not None

    def relation(next_close: Decimal) -> Decimal:
        extended = [*closes, next_close]
        sma_50 = sum(extended[-50:]) / 50
        sma_200 = sum(extended[-200:]) / 200
        return sma_50 - sma_200

    assert relation(thresholds.cross_min_close) >= 0
    assert relation(thresholds.cross_min_close - Decimal(1)) < 0

    # sma50_hold: close at threshold stays at/above the new SMA50.
    assert thresholds.sma50_hold_min_close is not None
    hold = thresholds.sma50_hold_min_close
    new_sma_50 = (sum(closes[-49:]) + hold) / 50
    assert hold >= new_sma_50 - Decimal("0.01")

    # vwma100_hold equals the VWMA of the 99 bars that stay in the window.
    assert thresholds.vwma100_hold_min_close is not None
    kept = closes[-99:]
    assert thresholds.vwma100_hold_min_close == (
        sum(kept) / Decimal(99)
    ).quantize(Decimal("0.01"))

    # Projection provides five forward points of the active basis line.
    assert len(thresholds.structure_projection) == 5
    assert thresholds.structure_projection[0].min_close == thresholds.cross_min_close


def test_thresholds_use_convergence_basis_below_cross() -> None:
    # Given: SMA50 below SMA200 (pre-cross).
    bars = _bars([Decimal(200)] * 200 + [Decimal(100)])

    # When
    evidence = calculate_ma_crossover_evidence(bars, _context())

    # Then
    thresholds = evidence.thresholds
    assert thresholds is not None
    assert thresholds.basis == "convergence_hold"
    assert thresholds.convergence_min_close is not None
    # Convergence threshold: next close above it narrows the 50/200 gap.
    closes = [Decimal(200)] * 200 + [Decimal(100)]
    gap_now = sum(closes[-200:]) / 200 - sum(closes[-50:]) / 50

    def gap_after(next_close: Decimal) -> Decimal:
        extended = [*closes, next_close]
        return sum(extended[-200:]) / 200 - sum(extended[-50:]) / 50

    at = thresholds.convergence_min_close
    assert gap_after(at + Decimal(1)) < gap_now
    assert gap_after(at - Decimal(1)) > gap_now


def test_thresholds_absent_below_minimum_bars() -> None:
    bars = _bars([Decimal(100)] * 30)

    evidence = calculate_ma_crossover_evidence(bars, _context())

    assert evidence.thresholds is None


def test_cross_probability_is_deterministic_and_directionally_sane() -> None:
    # Given: a steady uptrend (already crossed, hold should be near-certain)
    # vs a steady decline (reaching a cross should be near-impossible).
    rising = _bars([Decimal(100) * (Decimal("1.003") ** i) for i in range(260)])
    falling = _bars([Decimal(300) - Decimal(i) for i in range(260)])

    # When
    up = calculate_ma_crossover_evidence(rising, _context()).thresholds
    down = calculate_ma_crossover_evidence(falling, _context()).thresholds
    up_again = calculate_ma_crossover_evidence(rising, _context()).thresholds

    # Then: estimates exist, are reproducible, and order sanely.
    assert up is not None
    assert up.cross_probability is not None
    assert down is not None
    assert down.cross_probability is not None
    assert up_again is not None
    assert up_again.cross_probability is not None
    assert (
        up.cross_probability.probability_pct
        == up_again.cross_probability.probability_pct
    )
    assert up.cross_probability.target == "hold_cross"
    assert down.cross_probability.target == "reach_cross"
    assert up.cross_probability.probability_pct > down.cross_probability.probability_pct
    assert up.cross_probability.paths == 2000


def test_level_breakout_probability_tracks_manual_supply_zone_level() -> None:
    closes = [Decimal(100) * (Decimal("1.003") ** i) for i in range(260)]
    bars = _bars(closes)
    last_close = closes[-1]

    # A level far below the last close is broken in nearly every path; a level
    # far above it in nearly none. Absent a level, the estimate is absent.
    below = calculate_ma_crossover_evidence(
        bars, _context(supply_zone_price=last_close / 2)
    ).thresholds
    above = calculate_ma_crossover_evidence(
        bars, _context(supply_zone_price=last_close * 10)
    ).thresholds
    without = calculate_ma_crossover_evidence(bars, _context()).thresholds

    assert below is not None
    assert below.level_breakout_probability is not None
    assert above is not None
    assert above.level_breakout_probability is not None
    assert without is not None
    assert without.level_breakout_probability is None
    assert below.level_breakout_probability.probability_pct > Decimal(95)
    assert above.level_breakout_probability.probability_pct < Decimal(5)
    assert below.level_breakout_probability.level_price == last_close / 2
    assert below.level_breakout_probability.confirm_bars == 3

    # The level only adds a comparison — the shared path set stays identical,
    # so the other estimates are unchanged by supplying a level.
    assert without.cross_probability is not None
    assert below.cross_probability is not None
    assert (
        below.cross_probability.probability_pct
        == without.cross_probability.probability_pct
    )
    assert below.breakout_probability == without.breakout_probability
