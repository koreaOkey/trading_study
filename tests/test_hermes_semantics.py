import json
from datetime import datetime
from decimal import Decimal

import pytest

from fractal_journal.hermes_selection import HermesAuthoredSelection
from fractal_journal.hermes_semantics import (
    SelectionEvidenceMismatchError,
    build_revised_decision_note,
    describe_finding_codes,
    validate_selection_against_evidence,
)
from fractal_journal.schemas import (
    EvidenceDataStatus,
    GapTrend,
    Hypothesis,
    IndicatorMeasurement,
    MaCrossoverEvidence,
)


@pytest.mark.parametrize(
    ("assessment", "sufficient", "missing", "contradiction"),
    [
        ("balanced", ["gap_widening"], [], []),
        ("insufficient", [], ["sma50_value_missing"], []),
        ("insufficient", [], ["bars_insufficient"], []),
        ("insufficient", [], ["data_stale"], []),
        ("insufficient", [], ["provider_partial"], []),
        ("insufficient", [], ["hypothesis_unsupported"], []),
        ("conflicted", [], [], ["golden_gap_direction_conflict"]),
    ],
)
def test_selection_rejects_codes_contrary_to_trusted_evidence(
    assessment: str,
    sufficient: list[str],
    missing: list[str],
    contradiction: list[str],
) -> None:
    # Given
    selection = _selection(assessment, sufficient, missing, contradiction)

    # When
    with pytest.raises(SelectionEvidenceMismatchError):
        validate_selection_against_evidence(
            selection,
            _evidence(),
            Hypothesis.GOLDEN_CROSS_EXPECTED,
            decision_note_present=True,
        )


def test_selection_rejects_available_code_when_measurement_is_missing() -> None:
    # Given
    selection = _selection("balanced", ["sma50_value_available"], [], [])
    evidence = _evidence().model_copy(
        update={"sma_50": IndicatorMeasurement(null_reason="missing")},
    )

    # When
    with pytest.raises(SelectionEvidenceMismatchError):
        validate_selection_against_evidence(
            selection,
            evidence,
            Hypothesis.GOLDEN_CROSS_EXPECTED,
            decision_note_present=True,
        )


@pytest.mark.parametrize(
    ("quality", "note_present", "origin"),
    [
        ("specific", True, "기존 메모를 측정값 중심으로 재작성했다."),
        ("vague", True, "모호한 메모를 측정값 중심으로 재작성했다."),
        ("missing", False, "원문 메모 없이 측정값으로 재작성했다."),
    ],
)
def test_revised_note_uses_only_trusted_hypothesis_and_numeric_evidence(
    quality: str,
    note_present: bool,
    origin: str,
) -> None:
    # Given
    selection = _selection("balanced", ["gap_narrowing"], [], [], quality)
    evidence = _evidence()
    sentinel = "buy now 매수하세요"

    # When
    validate_selection_against_evidence(
        selection,
        evidence,
        Hypothesis.GOLDEN_CROSS_EXPECTED,
        decision_note_present=note_present,
    )
    revised = build_revised_decision_note(
        selection,
        evidence,
        Hypothesis.GOLDEN_CROSS_EXPECTED,
    )

    # Then
    assert "가설: 골든크로스 예상" in revised
    assert "SMA50=100" in revised
    assert "SMA200=100" in revised
    assert "VWMA100=100" in revised
    assert "SMA50-SMA200 간격=-0.2%" in revised
    assert "봉 수=200" in revised
    assert origin in revised
    assert sentinel not in revised


def test_finding_descriptions_cite_the_measurements_behind_each_verdict() -> None:
    # Given: a golden-cross hypothesis with a barely negative VWMA100 slope.
    evidence = _evidence().model_copy(
        update={
            "vwma_100": IndicatorMeasurement(
                value=Decimal(81451),
                previous_value=Decimal(81469),
                slope_pct=Decimal("-0.0219"),
                distance_from_close_pct=Decimal("8.29"),
                bars_used=100,
            ),
        },
    )

    # When
    (described,) = describe_finding_codes(
        ("vwma_hypothesis_conflict",),
        evidence,
        Hypothesis.GOLDEN_CROSS_EXPECTED,
    )

    # Then: the fixed sentence stays, the measured why is appended.
    assert described.startswith("VWMA100 방향과 선택한 가설이 충돌한다.")
    assert "상승 전환을 전제" in described
    assert "-0.022%" in described


def test_missing_findings_explain_bar_shortfalls_from_null_reasons() -> None:
    evidence = _evidence().model_copy(
        update={
            "bar_count": 150,
            "sma_200": IndicatorMeasurement(
                bars_used=150,
                null_reason="sma_200_requires_200_bars",
            ),
        },
    )

    described = describe_finding_codes(
        ("sma200_value_missing", "bars_insufficient"),
        evidence,
        Hypothesis.GOLDEN_CROSS_EXPECTED,
    )

    assert "현재 봉 150개로 필요 봉 200개에 미달한다" in described[0]
    assert "최소 200개에 미달한다" in described[1]


def test_findings_without_extra_context_keep_the_fixed_sentence() -> None:
    described = describe_finding_codes(
        ("golden_gap_direction_conflict",),
        _evidence().model_copy(update={"sma_50_to_sma_200_gap_pct": Decimal("1.5")}),
        Hypothesis.GOLDEN_CROSS_EXPECTED,
    )

    assert described == (
        "골든크로스 가설과 간격 방향이 충돌한다. "
        "SMA50이 이미 SMA200 위에 있다(간격 +1.50%).",
    )


def _selection(
    assessment: str,
    sufficient: list[str],
    missing: list[str],
    contradiction: list[str],
    quality: str = "specific",
) -> HermesAuthoredSelection:
    return HermesAuthoredSelection.model_validate_json(
        json.dumps(
            {
                "overall_assessment": assessment,
                "sufficient_codes": sufficient,
                "missing_codes": missing,
                "excessive_codes": [],
                "contradiction_codes": contradiction,
                "note_quality_code": quality,
            },
        ),
    )


def _evidence() -> MaCrossoverEvidence:
    measurement = IndicatorMeasurement(
        value=Decimal(100),
        previous_value=Decimal(99),
        slope_pct=Decimal("1.01"),
        distance_from_close_pct=Decimal("0.5"),
        bars_used=200,
    )
    decision_time = datetime.fromisoformat("2026-07-10T10:00:00+09:00")
    return MaCrossoverEvidence(
        provider="kis",
        provider_symbol="005930",
        timeframe="5",
        decision_time_exchange=decision_time,
        data_status=EvidenceDataStatus.READY,
        bar_count=200,
        last_bar_time_exchange=decision_time,
        close=Decimal(101),
        volume=Decimal(100000),
        sma_50=measurement,
        sma_200=measurement,
        vwma_100=measurement,
        sma_50_to_sma_200_gap_pct=Decimal("-0.2"),
        gap_trend=GapTrend.NARROWING,
    )
