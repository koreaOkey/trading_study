from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING

from fractal_journal.hermes_facts import MIN_REQUIRED_BARS, supported_factual_codes
from fractal_journal.hermes_selection import (
    HermesAuthoredSelection,
    HermesWorkerEnvelope,
    map_finding_codes,
    selection_to_review,
)
from fractal_journal.schemas import (
    GapTrend,
    Hypothesis,
    IndicatorMeasurement,
    MaCrossoverEvidence,
)

if TYPE_CHECKING:
    from fractal_journal.ai_review import DecisionReview

_REQUIRES_BARS = re.compile(r"requires_(\d+)_bars")
_TREND_TEXT: dict[GapTrend | None, str] = {
    GapTrend.NARROWING: "축소",
    GapTrend.WIDENING: "확대",
    GapTrend.FLAT: "정체",
    None: "확인 불가",
}

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
    gap_trend = _TREND_TEXT[evidence.gap_trend]
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


def describe_finding_codes(
    codes: tuple[str, ...],
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
) -> tuple[str, ...]:
    """Append a trusted-measurement explanation to each finding sentence.

    Details are computed here from the code-verified evidence, never authored
    by Hermes, so the deterministic-text safety boundary is unchanged.
    """
    described = []
    for code in codes:
        base = map_finding_codes((code,))[0]
        detail = _finding_detail(code, evidence, hypothesis)
        described.append(base if detail is None else f"{base} {detail}.")
    return tuple(described)


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
        missing_evidence=describe_finding_codes(
            envelope.selection.missing_codes,
            evidence,
            hypothesis,
        ),
        contradictions=describe_finding_codes(
            envelope.selection.contradiction_codes,
            evidence,
            hypothesis,
        ),
    )


def _finding_detail(  # noqa: C901, PLR0911, PLR0912 — one branch per finding code
    code: str,
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
) -> str | None:
    golden = hypothesis is Hypothesis.GOLDEN_CROSS_EXPECTED
    dead = hypothesis is Hypothesis.DEAD_CROSS_EXPECTED
    gap = evidence.sma_50_to_sma_200_gap_pct
    trend = _TREND_TEXT[evidence.gap_trend]
    measurements = {
        "sma50": ("SMA50", evidence.sma_50),
        "sma200": ("SMA200", evidence.sma_200),
        "vwma100": ("VWMA100", evidence.vwma_100),
    }

    prefix = code.split("_", 1)[0]
    if prefix in measurements and code.endswith(
        ("_value_missing", "_slope_missing", "_distance_missing"),
    ):
        return _null_reason_detail(measurements[prefix][1], evidence.bar_count)

    if code == "vwma_hypothesis_conflict":
        slope = evidence.vwma_100.slope_pct
        if slope is None:
            return None
        expected = "상승 전환" if golden else "하락 전환"
        return (
            f"가설은 VWMA100 {expected}을 전제하지만 "
            f"측정 기울기는 봉당 {_signed(slope, '0.001')}%다"
        )
    if code == "slope_hypothesis_conflict":
        slope_50 = evidence.sma_50.slope_pct
        slope_200 = evidence.sma_200.slope_pct
        if slope_50 is None or slope_200 is None:
            return None
        relation = (
            "이하라 접근이 안 되고 있다" if golden else "이상이라 이탈이 안 되고 있다"
        )
        return (
            f"SMA50 기울기(봉당 {_signed(slope_50, '0.001')}%)가 "
            f"SMA200 기울기(봉당 {_signed(slope_200, '0.001')}%) {relation}"
        )
    if code in {"golden_gap_direction_conflict", "dead_gap_direction_conflict"}:
        if gap is None:
            return "SMA50-SMA200 간격을 계산할 수 없다"
        already = (gap >= 0) if code.startswith("golden") else (gap <= 0)
        side = "위" if code.startswith("golden") else "아래"
        if already:
            return (
                f"SMA50이 이미 SMA200 {side}에 있다"
                f"(간격 {_signed(gap, '0.01')}%)"
            )
        return (
            f"간격 {_signed(gap, '0.01')}%가 축소가 아니라 {trend} 중이다"
        )
    if code == "price_distance_hypothesis_conflict":
        distance = evidence.sma_50.distance_from_close_pct
        if distance is None:
            return None
        side = "아래" if golden else "위"
        distance_text = abs(distance).quantize(Decimal("0.01"))
        return f"종가가 SMA50보다 {distance_text}% {side}에 있다"
    if code in {"provider_data_conflict", "provider_partial"}:
        reasons = ", ".join(evidence.null_reasons[:3])
        suffix = f" (사유: {reasons})" if reasons else ""
        return f"데이터 상태가 {evidence.data_status.value}다{suffix}"
    if code == "bars_insufficient":
        return f"현재 봉 {evidence.bar_count}개로 최소 {MIN_REQUIRED_BARS}개에 미달한다"
    if code == "signed_gap_missing":
        if evidence.sma_50.value is None or evidence.sma_200.value is None:
            missing = "SMA50" if evidence.sma_50.value is None else "SMA200"
            return f"{missing} 값이 없어 간격을 계산할 수 없다"
        return "SMA200이 0이라 간격이 정의되지 않는다"
    if code == "gap_trend_missing":
        return "직전 봉 기준 이동평균 값이 없어 추세를 비교할 수 없다"
    if code == "data_stale":
        last = evidence.last_bar_time_exchange
        last_text = "없음" if last is None else last.strftime("%Y-%m-%d %H:%M")
        decision_text = evidence.decision_time_exchange.strftime("%Y-%m-%d %H:%M")
        return f"마지막 봉 {last_text} vs 판단 시각 {decision_text}"
    if code == "hypothesis_unsupported":
        if not (golden or dead):
            return "가설이 미확정이라 측정 방향과 대조할 수 없다"
        need = "음(-)의 간격 축소" if golden else "양(+)의 간격 축소"
        gap_text = "확인 불가" if gap is None else f"{_signed(gap, '0.01')}%"
        return f"가설 지지는 {need}가 필요한데 현재 간격 {gap_text}, 추세 {trend}다"
    return None


def _null_reason_detail(
    measurement: IndicatorMeasurement,
    bar_count: int,
) -> str | None:
    reason = measurement.null_reason
    if reason is None:
        return None
    requires = _REQUIRES_BARS.search(reason)
    if requires is not None:
        return f"현재 봉 {bar_count}개로 필요 봉 {requires.group(1)}개에 미달한다"
    if "zero_volume" in reason:
        return "구간 거래량 합이 0이라 계산할 수 없다"
    if "zero" in reason:
        return "기준값이 0이라 계산할 수 없다"
    return f"사유: {reason}"


def _signed(value: Decimal, step: str) -> str:
    return f"{value.quantize(Decimal(step)):+f}"


def _number(value: Decimal | None) -> str:
    return "확인 불가" if value is None else str(value)


def _percent(value: Decimal | None) -> str:
    return "확인 불가" if value is None else f"{value}%"
