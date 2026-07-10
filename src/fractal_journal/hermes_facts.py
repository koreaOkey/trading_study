from __future__ import annotations

from typing import TYPE_CHECKING, Final

from fractal_journal.schemas import (
    EvidenceDataStatus,
    GapTrend,
    Hypothesis,
    MaCrossoverEvidence,
)

MIN_REQUIRED_BARS: Final = 200

if TYPE_CHECKING:
    from decimal import Decimal


def supported_factual_codes(
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
) -> frozenset[str]:
    gap = evidence.sma_50_to_sma_200_gap_pct
    narrowing = evidence.gap_trend is GapTrend.NARROWING
    golden = hypothesis is Hypothesis.GOLDEN_CROSS_EXPECTED
    dead = hypothesis is Hypothesis.DEAD_CROSS_EXPECTED
    aligned = (golden and gap is not None and gap < 0 and narrowing) or (
        dead and gap is not None and gap > 0 and narrowing
    )
    slope_50 = evidence.sma_50.slope_pct
    slope_200 = evidence.sma_200.slope_pct
    vwma_slope = evidence.vwma_100.slope_pct
    price_distance = evidence.sma_50.distance_from_close_pct
    facts = {
        "sma50_value_available": evidence.sma_50.value is not None,
        "sma200_value_available": evidence.sma_200.value is not None,
        "vwma100_value_available": evidence.vwma_100.value is not None,
        "sma50_slope_available": slope_50 is not None,
        "sma200_slope_available": slope_200 is not None,
        "vwma100_slope_available": vwma_slope is not None,
        "sma50_distance_available": evidence.sma_50.distance_from_close_pct is not None,
        "sma200_distance_available": (
            evidence.sma_200.distance_from_close_pct is not None
        ),
        "vwma100_distance_available": (
            evidence.vwma_100.distance_from_close_pct is not None
        ),
        "signed_gap_available": gap is not None,
        "gap_narrowing": narrowing,
        "gap_widening": evidence.gap_trend is GapTrend.WIDENING,
        "gap_flat": evidence.gap_trend is GapTrend.FLAT,
        "bars_sufficient": evidence.bar_count >= MIN_REQUIRED_BARS,
        "data_fresh": (
            evidence.last_bar_time_exchange == evidence.decision_time_exchange
        ),
        "provider_complete": (
            evidence.provider == "kis"
            and evidence.data_status is EvidenceDataStatus.READY
        ),
        "hypothesis_aligned": aligned,
        "gap_trend_missing": evidence.gap_trend is None,
        "bars_insufficient": evidence.bar_count < MIN_REQUIRED_BARS,
        "data_stale": (
            evidence.last_bar_time_exchange != evidence.decision_time_exchange
        ),
        "provider_partial": evidence.data_status is not EvidenceDataStatus.READY,
        "hypothesis_unsupported": not aligned,
        "golden_gap_direction_conflict": golden and not aligned,
        "dead_gap_direction_conflict": dead and not aligned,
        "slope_hypothesis_conflict": _slope_conflict(
            golden,
            dead,
            slope_50,
            slope_200,
        ),
        "vwma_hypothesis_conflict": (
            (golden and vwma_slope is not None and vwma_slope < 0)
            or (dead and vwma_slope is not None and vwma_slope > 0)
        ),
        "price_distance_hypothesis_conflict": (
            (golden and price_distance is not None and price_distance < 0)
            or (dead and price_distance is not None and price_distance > 0)
        ),
        "provider_data_conflict": evidence.data_status is not EvidenceDataStatus.READY,
    }
    for name, measurement in (
        ("sma50", evidence.sma_50),
        ("sma200", evidence.sma_200),
        ("vwma100", evidence.vwma_100),
    ):
        facts[f"{name}_value_missing"] = measurement.value is None
        facts[f"{name}_slope_missing"] = measurement.slope_pct is None
        facts[f"{name}_distance_missing"] = measurement.distance_from_close_pct is None
    facts["signed_gap_missing"] = gap is None
    return frozenset(code for code, supported in facts.items() if supported)


def _slope_conflict(
    golden: bool,
    dead: bool,
    slope_50: Decimal | None,
    slope_200: Decimal | None,
) -> bool:
    if slope_50 is None or slope_200 is None:
        return False
    return (golden and slope_50 <= slope_200) or (dead and slope_50 >= slope_200)
