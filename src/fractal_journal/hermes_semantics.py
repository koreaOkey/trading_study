from __future__ import annotations

from typing import TYPE_CHECKING

from fractal_journal.hermes_facts import supported_factual_codes
from fractal_journal.hermes_selection import (
    HermesAuthoredSelection,
    HermesWorkerEnvelope,
    map_finding_codes,
    selection_to_review,
)
from fractal_journal.schemas import (
    GapTrend,
    Hypothesis,
    MaCrossoverEvidence,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from fractal_journal.ai_review import DecisionReview

class SelectionEvidenceMismatchError(ValueError):
    def __init__(self) -> None:
        super().__init__("Hermes selection contradicts trusted evidence")


def validate_selection_against_evidence(
    selection: HermesAuthoredSelection,
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
    *,
    decision_note_present: bool,
) -> None:
    selected = (
        *selection.sufficient_codes,
        *selection.missing_codes,
        *selection.contradiction_codes,
    )
    supported = supported_factual_codes(evidence, hypothesis)
    if any(code not in supported for code in selected):
        raise SelectionEvidenceMismatchError
    note_matches = (selection.note_quality_code == "missing") != decision_note_present
    if not note_matches:
        raise SelectionEvidenceMismatchError


def build_revised_decision_note(
    selection: HermesAuthoredSelection,
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
) -> str:
    hypothesis_text = {
        Hypothesis.GOLDEN_CROSS_EXPECTED: "골든크로스 예상",
        Hypothesis.DEAD_CROSS_EXPECTED: "데드크로스 예상",
        Hypothesis.UNCERTAIN: "방향 미확정",
    }[hypothesis]
    gap_trend = {
        GapTrend.NARROWING: "축소",
        GapTrend.WIDENING: "확대",
        GapTrend.FLAT: "정체",
        None: "확인 불가",
    }[evidence.gap_trend]
    findings = map_finding_codes(
        (*selection.missing_codes, *selection.contradiction_codes),
    )
    finding_text = " ".join(findings) if findings else "핵심 누락이나 충돌 없음."
    note_origin = {
        "specific": "기존 메모를 측정값 중심으로 재작성했다.",
        "vague": "모호한 메모를 측정값 중심으로 재작성했다.",
        "missing": "원문 메모 없이 측정값으로 재작성했다.",
    }[selection.note_quality_code]
    return (
        f"가설: {hypothesis_text}. "
        f"SMA50={_number(evidence.sma_50.value)}, "
        f"SMA200={_number(evidence.sma_200.value)}, "
        f"VWMA100={_number(evidence.vwma_100.value)}. "
        f"기울기: SMA50={_percent(evidence.sma_50.slope_pct)}, "
        f"SMA200={_percent(evidence.sma_200.slope_pct)}, "
        f"VWMA100={_percent(evidence.vwma_100.slope_pct)}. "
        f"SMA50-SMA200 간격={_percent(evidence.sma_50_to_sma_200_gap_pct)}, "
        f"간격 추세={gap_trend}. 봉 수={evidence.bar_count}, "
        f"provider 상태={evidence.data_status.value}. {finding_text} {note_origin}"
    )


def review_from_trusted_context(
    envelope: HermesWorkerEnvelope,
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
    *,
    decision_note_present: bool,
) -> DecisionReview:
    validate_selection_against_evidence(
        envelope.selection,
        evidence,
        hypothesis,
        decision_note_present=decision_note_present,
    )
    revised_note = build_revised_decision_note(
        envelope.selection,
        evidence,
        hypothesis,
    )
    return selection_to_review(
        envelope,
        revised_decision_note=revised_note,
    )


def _number(value: Decimal | None) -> str:
    return "확인 불가" if value is None else str(value)


def _percent(value: Decimal | None) -> str:
    return "확인 불가" if value is None else f"{value}%"
