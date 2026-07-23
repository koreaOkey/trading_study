import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import ClassVar, Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from fractal_journal.provider import OhlcvBar
from fractal_journal.schemas import (
    BreakoutProbabilityEstimate,
    CrossProbabilityEstimate,
    EvidenceDataStatus,
    GapTrend,
    IndicatorMeasurement,
    MaCrossoverEvidence,
    MaCrossoverThresholds,
    ThresholdProjectionPoint,
)

SMA_50_PERIOD: Final = 50
SMA_200_PERIOD: Final = 200
VWMA_100_PERIOD: Final = 100
PERCENT: Final = Decimal(100)
THRESHOLD_PROJECTION_BARS: Final = 5
TWO_DP: Final = Decimal("0.01")
PROBABILITY_HORIZON_BARS: Final = 30  # rule expiry_bars와 정합
PROBABILITY_PATHS: Final = 2_000
PROBABILITY_MIN_RETURN_SAMPLE: Final = 60
PROBABILITY_MAX_RETURN_SAMPLE: Final = 250
BREAKOUT_CONFIRM_BARS: Final = 3
READY_PROVIDER_STATUSES: Final = frozenset({"ok", "ready"})


class MaCrossoverEvidenceContext(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    provider: str = Field(min_length=1, max_length=24)
    provider_symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=16)
    decision_time_exchange: AwareDatetime
    provider_data_status: str = Field(default="ok", min_length=1, max_length=64)


def calculate_ma_crossover_evidence(
    bars: Sequence[OhlcvBar],
    context: MaCrossoverEvidenceContext,
) -> MaCrossoverEvidence:
    ordered_bars, normalization_reasons = _normalize_bars(
        bars,
        context.decision_time_exchange,
    )
    closes = tuple(bar.close for bar in ordered_bars)
    volumes = tuple(Decimal(bar.volume) for bar in ordered_bars)
    close = closes[-1] if closes else None

    sma_50 = _sma_measurement(closes, close, SMA_50_PERIOD)
    sma_200 = _sma_measurement(closes, close, SMA_200_PERIOD)
    vwma_100 = _vwma_measurement(closes, volumes, close)
    gap_pct = _signed_gap_pct(sma_50.value, sma_200.value)
    gap_trend = _gap_trend(sma_50, sma_200)

    reasons = list(normalization_reasons)
    if not ordered_bars:
        reasons.append("no_eligible_bars")
    if context.provider_data_status not in READY_PROVIDER_STATUSES:
        reasons.append(f"provider_data_status:{context.provider_data_status}")
    reasons.extend(
        measurement.null_reason
        for measurement in (sma_50, sma_200, vwma_100)
        if measurement.null_reason is not None
    )
    if gap_pct is None and sma_200.value == Decimal(0):
        reasons.append("sma_200_zero_gap_undefined")

    unique_reasons = tuple(dict.fromkeys(reasons))
    data_status = _data_status(ordered_bars, unique_reasons)
    last_bar = ordered_bars[-1] if ordered_bars else None
    return MaCrossoverEvidence(
        provider=context.provider,
        provider_symbol=context.provider_symbol,
        timeframe=context.timeframe,
        decision_time_exchange=context.decision_time_exchange,
        data_status=data_status,
        bar_count=len(ordered_bars),
        last_bar_time_exchange=(
            datetime.fromisoformat(last_bar.time_exchange) if last_bar else None
        ),
        close=close,
        volume=Decimal(last_bar.volume) if last_bar else None,
        sma_50=sma_50,
        sma_200=sma_200,
        vwma_100=vwma_100,
        sma_50_to_sma_200_gap_pct=gap_pct,
        gap_trend=gap_trend,
        thresholds=_calculate_thresholds(closes, volumes, sma_50.value, sma_200.value),
        null_reasons=unique_reasons,
    )


def _structure_threshold(closes: Sequence[Decimal], basis: str) -> Decimal:
    """Minimum next-bar close that keeps the structure condition true.

    Both SMAs are linear in the next close P, so the condition solves exactly:
    convergence_hold keeps the 50/200 gap narrowing, cross_hold keeps (or
    reaches) SMA50 >= SMA200.
    """
    leaving_50 = closes[-SMA_50_PERIOD]
    leaving_200 = closes[-SMA_200_PERIOD]
    if basis == "convergence_hold":
        return (4 * leaving_50 - leaving_200) / 3
    sma_50 = sum(closes[-SMA_50_PERIOD:], Decimal(0)) / SMA_50_PERIOD
    sma_200 = sum(closes[-SMA_200_PERIOD:], Decimal(0)) / SMA_200_PERIOD
    gap = sma_200 - sma_50
    window_shift = leaving_50 / SMA_50_PERIOD - leaving_200 / SMA_200_PERIOD
    return (gap + window_shift) * SMA_200_PERIOD / 3


def _project_structure_line(
    closes: Sequence[Decimal],
    basis: str,
) -> tuple[ThresholdProjectionPoint, ...]:
    simulated = list(closes)
    points: list[ThresholdProjectionPoint] = []
    for bar_offset in range(1, THRESHOLD_PROJECTION_BARS + 1):
        threshold = _structure_threshold(simulated, basis)
        points.append(
            ThresholdProjectionPoint(
                bar_offset=bar_offset,
                min_close=threshold.quantize(TWO_DP),
            )
        )
        # Boundary path: assume the close lands exactly on the threshold. A
        # non-positive threshold means the condition cannot break next bar;
        # carry the last close forward so the simulation stays realistic.
        simulated.append(threshold if threshold > 0 else simulated[-1])
    return tuple(points)


def _probability_pct(successes: int) -> Decimal:
    return (Decimal(successes) / Decimal(PROBABILITY_PATHS) * PERCENT).quantize(
        Decimal("0.1")
    )


@dataclass(frozen=True, slots=True)
class _SimulationBase:
    pairs: list[tuple[float, float]]
    closes: list[float]
    volumes: list[float]
    sums: tuple[float, float, float, float]
    crossed: bool
    vwma_available: bool


def _run_paths(
    rng: random.Random,
    base: _SimulationBase,
) -> tuple[int, int, int, int, int]:
    pairs = base.pairs
    crossed = base.crossed
    vwma_available = base.vwma_available
    cross_successes = 0
    hit_50 = hit_200 = hit_vwma = hit_all = 0
    for _ in range(PROBABILITY_PATHS):
        path_closes = list(base.closes)
        path_volumes = list(base.volumes)
        sum_50, sum_200, sum_pv, sum_v = base.sums
        survived = True
        reached = False
        run_50 = run_200 = run_vwma = run_all = 0
        path_50 = path_200 = path_vwma = path_all = False
        for _ in range(PROBABILITY_HORIZON_BARS):
            bar_return, bar_volume = pairs[rng.randrange(len(pairs))]
            next_close = path_closes[-1] * (1.0 + bar_return)
            sum_50 += next_close - path_closes[-SMA_50_PERIOD]
            sum_200 += next_close - path_closes[-SMA_200_PERIOD]
            sum_pv += (
                next_close * bar_volume
                - path_closes[-VWMA_100_PERIOD] * path_volumes[-VWMA_100_PERIOD]
            )
            sum_v += bar_volume - path_volumes[-VWMA_100_PERIOD]
            path_closes.append(next_close)
            path_volumes.append(bar_volume)

            sma_50_now = sum_50 / SMA_50_PERIOD
            sma_200_now = sum_200 / SMA_200_PERIOD
            if sma_50_now >= sma_200_now:
                reached = True
            else:
                survived = False

            above_50 = next_close > sma_50_now
            above_200 = next_close > sma_200_now
            above_vwma = vwma_available and sum_v > 0 and next_close > sum_pv / sum_v
            run_50 = run_50 + 1 if above_50 else 0
            run_200 = run_200 + 1 if above_200 else 0
            run_vwma = run_vwma + 1 if above_vwma else 0
            run_all = run_all + 1 if (above_50 and above_200 and above_vwma) else 0
            path_50 = path_50 or run_50 >= BREAKOUT_CONFIRM_BARS
            path_200 = path_200 or run_200 >= BREAKOUT_CONFIRM_BARS
            path_vwma = path_vwma or run_vwma >= BREAKOUT_CONFIRM_BARS
            path_all = path_all or run_all >= BREAKOUT_CONFIRM_BARS
        if (crossed and survived) or (not crossed and reached):
            cross_successes += 1
        hit_50 += path_50
        hit_200 += path_200
        hit_vwma += path_vwma
        hit_all += path_all
    return cross_successes, hit_50, hit_200, hit_vwma, hit_all


def _estimate_probabilities(
    closes: Sequence[Decimal],
    volumes: Sequence[Decimal],
    crossed: bool,
) -> tuple[CrossProbabilityEstimate | None, BreakoutProbabilityEstimate | None]:
    """Bootstrap Monte Carlo on the symbol's own recent (return, volume) pairs.

    One shared path set answers both questions: whether the 50/200 cross is
    reached (pre-cross) or survives (post-cross), and whether the close
    finishes above each co-simulated MA for BREAKOUT_CONFIRM_BARS in a row.
    Seeded from the input closes so identical evidence always yields the
    identical estimates (reproducible reviews, cache-friendly).
    """
    if len(closes) < SMA_200_PERIOD + 1:
        return None, None
    history = [float(value) for value in closes]
    history_volumes = [float(value) for value in volumes]
    sample_closes = history[-(PROBABILITY_MAX_RETURN_SAMPLE + 1) :]
    sample_volumes = history_volumes[-(PROBABILITY_MAX_RETURN_SAMPLE + 1) :]
    pairs = [
        (sample_closes[index] / sample_closes[index - 1] - 1.0, sample_volumes[index])
        for index in range(1, len(sample_closes))
        if sample_closes[index - 1] > 0
    ]
    if len(pairs) < PROBABILITY_MIN_RETURN_SAMPLE:
        return None, None

    seed_material = ",".join(f"{value:.6f}" for value in history[-200:])
    seed = int(sha256(seed_material.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)  # noqa: S311 — simulation sampling, not cryptography

    base_closes = history[-SMA_200_PERIOD:]
    base_volumes = history_volumes[-SMA_200_PERIOD:]
    base_sum_50 = sum(base_closes[-SMA_50_PERIOD:])
    base_sum_200 = sum(base_closes)
    base_sum_pv = sum(
        close * volume
        for close, volume in zip(
            base_closes[-VWMA_100_PERIOD:],
            base_volumes[-VWMA_100_PERIOD:],
            strict=True,
        )
    )
    base_sum_v = sum(base_volumes[-VWMA_100_PERIOD:])
    vwma_available = base_sum_v > 0

    counts = _run_paths(
        rng,
        _SimulationBase(
            pairs=pairs,
            closes=base_closes,
            volumes=base_volumes,
            sums=(base_sum_50, base_sum_200, base_sum_pv, base_sum_v),
            crossed=crossed,
            vwma_available=vwma_available,
        ),
    )
    cross_successes, hit_50, hit_200, hit_vwma, hit_all = counts

    cross = CrossProbabilityEstimate(
        target="hold_cross" if crossed else "reach_cross",
        horizon_bars=PROBABILITY_HORIZON_BARS,
        paths=PROBABILITY_PATHS,
        probability_pct=_probability_pct(cross_successes),
        return_sample_bars=len(pairs),
    )
    breakout = BreakoutProbabilityEstimate(
        horizon_bars=PROBABILITY_HORIZON_BARS,
        confirm_bars=BREAKOUT_CONFIRM_BARS,
        paths=PROBABILITY_PATHS,
        sma50_pct=_probability_pct(hit_50),
        sma200_pct=_probability_pct(hit_200),
        vwma100_pct=_probability_pct(hit_vwma) if vwma_available else None,
        all_above_pct=_probability_pct(hit_all) if vwma_available else None,
        return_sample_bars=len(pairs),
    )
    return cross, breakout


def _calculate_thresholds(
    closes: Sequence[Decimal],
    volumes: Sequence[Decimal],
    sma_50_value: Decimal | None,
    sma_200_value: Decimal | None,
) -> MaCrossoverThresholds | None:
    if len(closes) < SMA_50_PERIOD or sma_50_value is None:
        return None
    leaving_50 = closes[-SMA_50_PERIOD]
    sma50_hold = (
        (SMA_50_PERIOD * sma_50_value - leaving_50) / (SMA_50_PERIOD - 1)
    ).quantize(TWO_DP)

    convergence_min = cross_min = None
    projection: tuple[ThresholdProjectionPoint, ...] = ()
    cross_probability = None
    breakout_probability = None
    basis = "convergence_hold"
    if len(closes) >= SMA_200_PERIOD and sma_200_value is not None:
        crossed = sma_50_value >= sma_200_value
        basis = "cross_hold" if crossed else "convergence_hold"
        convergence_min = _structure_threshold(
            closes, "convergence_hold"
        ).quantize(TWO_DP)
        cross_min = _structure_threshold(closes, "cross_hold").quantize(TWO_DP)
        projection = _project_structure_line(closes, basis)
        cross_probability, breakout_probability = _estimate_probabilities(
            closes, volumes, crossed
        )

    vwma_hold = None
    if len(closes) >= VWMA_100_PERIOD:
        kept_closes = closes[-(VWMA_100_PERIOD - 1) :]
        kept_volumes = volumes[-(VWMA_100_PERIOD - 1) :]
        volume_sum = sum(kept_volumes, Decimal(0))
        if volume_sum > 0:
            pairs = zip(kept_closes, kept_volumes, strict=True)
            weighted = sum((close * volume for close, volume in pairs), Decimal(0))
            # The next bar's own volume cancels out of "close >= next VWMA100",
            # so this needs no future-volume assumption.
            vwma_hold = (weighted / volume_sum).quantize(TWO_DP)

    return MaCrossoverThresholds(
        basis=basis,
        convergence_min_close=convergence_min,
        cross_min_close=cross_min,
        sma50_hold_min_close=sma50_hold,
        vwma100_hold_min_close=vwma_hold,
        structure_projection=projection,
        cross_probability=cross_probability,
        breakout_probability=breakout_probability,
    )


def _normalize_bars(
    bars: Sequence[OhlcvBar],
    decision_time: datetime,
) -> tuple[tuple[OhlcvBar, ...], tuple[str, ...]]:
    candidates = tuple(
        bar for bar in bars if _is_available_at_decision(bar, decision_time)
    )
    by_time: dict[datetime, OhlcvBar] = {}
    conflicting_times: set[datetime] = set()
    for bar in candidates:
        existing = by_time.get(bar.time_utc)
        if existing is not None and existing != bar:
            conflicting_times.add(bar.time_utc)
        else:
            by_time[bar.time_utc] = bar
    ordered = tuple(
        bar for time, bar in sorted(by_time.items()) if time not in conflicting_times
    )
    reasons = (
        (f"conflicting_duplicate_bars:{len(conflicting_times)}",)
        if conflicting_times
        else ()
    )
    return ordered, reasons


def _is_available_at_decision(bar: OhlcvBar, decision_time: datetime) -> bool:
    if bar.time_utc.tzinfo is None or bar.time_utc.utcoffset() is None:
        return False
    if not bar.close.is_finite() or bar.close <= 0 or bar.volume < 0:
        return False
    try:
        exchange_time = datetime.fromisoformat(bar.time_exchange)
    except ValueError:
        return False
    if exchange_time.tzinfo is None or exchange_time.utcoffset() is None:
        return False
    return bar.time_utc <= decision_time and exchange_time <= decision_time


def _sma_measurement(
    closes: tuple[Decimal, ...],
    close: Decimal | None,
    period: int,
) -> IndicatorMeasurement:
    name = f"sma_{period}"
    bars_used = min(len(closes), period)
    if len(closes) < period:
        return IndicatorMeasurement(
            bars_used=bars_used,
            null_reason=f"{name}_requires_{period}_bars",
        )
    value = sum(closes[-period:], start=Decimal(0)) / Decimal(period)
    if len(closes) < period + 1:
        return IndicatorMeasurement(
            value=value,
            distance_from_close_pct=_distance_from_close_pct(close, value),
            bars_used=period,
            null_reason=f"{name}_requires_{period + 1}_bars",
        )
    previous = sum(closes[-period - 1 : -1], start=Decimal(0)) / Decimal(period)
    reason = f"{name}_previous_zero" if previous == 0 else None
    if value == 0:
        reason = f"{name}_current_zero"
    return IndicatorMeasurement(
        value=value,
        previous_value=previous,
        slope_pct=_change_pct(value, previous),
        distance_from_close_pct=_distance_from_close_pct(close, value),
        bars_used=period,
        null_reason=reason,
    )


def _vwma_measurement(
    closes: tuple[Decimal, ...],
    volumes: tuple[Decimal, ...],
    close: Decimal | None,
) -> IndicatorMeasurement:
    period = VWMA_100_PERIOD
    bars_used = min(len(closes), period)
    if len(closes) < period:
        return IndicatorMeasurement(
            bars_used=bars_used,
            null_reason="vwma_100_requires_100_bars",
        )
    value = _vwma(closes[-period:], volumes[-period:])
    if value is None:
        return IndicatorMeasurement(
            bars_used=period,
            null_reason="vwma_100_zero_volume",
        )
    if len(closes) < period + 1:
        return IndicatorMeasurement(
            value=value,
            distance_from_close_pct=_distance_from_close_pct(close, value),
            bars_used=period,
            null_reason="vwma_100_requires_101_bars",
        )
    previous = _vwma(closes[-period - 1 : -1], volumes[-period - 1 : -1])
    if previous is None:
        return IndicatorMeasurement(
            value=value,
            distance_from_close_pct=_distance_from_close_pct(close, value),
            bars_used=period,
            null_reason="vwma_100_previous_zero_volume",
        )
    reason = "vwma_100_previous_zero" if previous == 0 else None
    if value == 0:
        reason = "vwma_100_current_zero"
    return IndicatorMeasurement(
        value=value,
        previous_value=previous,
        slope_pct=_change_pct(value, previous),
        distance_from_close_pct=_distance_from_close_pct(close, value),
        bars_used=period,
        null_reason=reason,
    )


def _vwma(
    closes: tuple[Decimal, ...],
    volumes: tuple[Decimal, ...],
) -> Decimal | None:
    total_volume = sum(volumes, start=Decimal(0))
    if total_volume == 0:
        return None
    weighted_total = sum(
        (close * volume for close, volume in zip(closes, volumes, strict=True)),
        start=Decimal(0),
    )
    return weighted_total / total_volume


def _change_pct(value: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return ((value - previous) / previous) * PERCENT


def _distance_from_close_pct(
    close: Decimal | None,
    indicator: Decimal,
) -> Decimal | None:
    if close is None or indicator == 0:
        return None
    return ((close - indicator) / indicator) * PERCENT


def _signed_gap_pct(
    sma_50: Decimal | None,
    sma_200: Decimal | None,
) -> Decimal | None:
    if sma_50 is None or sma_200 is None or sma_200 == 0:
        return None
    return ((sma_50 - sma_200) / sma_200) * PERCENT


def _gap_trend(
    sma_50: IndicatorMeasurement,
    sma_200: IndicatorMeasurement,
) -> GapTrend | None:
    current_50 = sma_50.value
    previous_50 = sma_50.previous_value
    current_200 = sma_200.value
    previous_200 = sma_200.previous_value
    if (
        current_50 is None
        or previous_50 is None
        or current_200 is None
        or previous_200 is None
    ):
        return None
    current_gap = abs(current_50 - current_200)
    previous_gap = abs(previous_50 - previous_200)
    if current_gap < previous_gap:
        return GapTrend.NARROWING
    if current_gap > previous_gap:
        return GapTrend.WIDENING
    return GapTrend.FLAT


def _data_status(
    bars: tuple[OhlcvBar, ...],
    reasons: tuple[str, ...],
) -> EvidenceDataStatus:
    if not bars:
        return EvidenceDataStatus.UNAVAILABLE
    if reasons:
        return EvidenceDataStatus.PARTIAL
    return EvidenceDataStatus.READY
