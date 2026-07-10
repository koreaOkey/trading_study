from __future__ import annotations

from datetime import UTC
from typing import ClassVar, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from fractal_journal.ai_review import (
    RISK_NOTE,
    DecisionReview,
    ReviewOverallAssessment,
)

type SufficientCode = Literal[
    "sma50_value_available",
    "sma200_value_available",
    "vwma100_value_available",
    "sma50_slope_available",
    "sma200_slope_available",
    "vwma100_slope_available",
    "sma50_distance_available",
    "sma200_distance_available",
    "vwma100_distance_available",
    "signed_gap_available",
    "gap_narrowing",
    "gap_widening",
    "gap_flat",
    "bars_sufficient",
    "data_fresh",
    "provider_complete",
    "hypothesis_aligned",
]
type MissingCode = Literal[
    "sma50_value_missing",
    "sma200_value_missing",
    "vwma100_value_missing",
    "sma50_slope_missing",
    "sma200_slope_missing",
    "vwma100_slope_missing",
    "sma50_distance_missing",
    "sma200_distance_missing",
    "vwma100_distance_missing",
    "signed_gap_missing",
    "gap_trend_missing",
    "bars_insufficient",
    "data_stale",
    "provider_partial",
    "hypothesis_unsupported",
]
type ExcessiveCode = Literal[
    "redundant_ma_confirmation",
    "redundant_distance_confirmation",
    "redundant_volume_confirmation",
    "single_signal_overweighted",
]
type ContradictionCode = Literal[
    "golden_gap_direction_conflict",
    "dead_gap_direction_conflict",
    "slope_hypothesis_conflict",
    "vwma_hypothesis_conflict",
    "price_distance_hypothesis_conflict",
    "provider_data_conflict",
]
type NoteQualityCode = Literal["specific", "vague", "missing"]

_CODE_TEXT: Final[dict[str, str]] = {
    "sma50_value_available": "SMA50 값이 판단 시점 데이터에 포함되어 있다.",
    "sma200_value_available": "SMA200 값이 판단 시점 데이터에 포함되어 있다.",
    "vwma100_value_available": "VWMA100 값이 판단 시점 데이터에 포함되어 있다.",
    "sma50_slope_available": "SMA50 기울기가 근거로 확인되었다.",
    "sma200_slope_available": "SMA200 기울기가 근거로 확인되었다.",
    "vwma100_slope_available": "VWMA100 기울기가 근거로 확인되었다.",
    "sma50_distance_available": "종가와 SMA50의 이격도가 확인되었다.",
    "sma200_distance_available": "종가와 SMA200의 이격도가 확인되었다.",
    "vwma100_distance_available": "종가와 VWMA100의 이격도가 확인되었다.",
    "signed_gap_available": "SMA50과 SMA200의 부호 있는 간격이 확인되었다.",
    "gap_narrowing": "SMA50과 SMA200의 간격이 축소되고 있다.",
    "gap_widening": "SMA50과 SMA200의 간격이 확대되고 있다.",
    "gap_flat": "SMA50과 SMA200의 간격 변화가 제한적이다.",
    "bars_sufficient": "이동평균 계산에 필요한 봉 수가 충분하다.",
    "data_fresh": "마지막 봉이 판단 시점과 정렬되어 있다.",
    "provider_complete": "KIS 제공 데이터가 완전한 상태다.",
    "hypothesis_aligned": "선택한 가설과 측정된 방향이 일치한다.",
    "sma50_value_missing": "SMA50 값을 확인할 수 없다.",
    "sma200_value_missing": "SMA200 값을 확인할 수 없다.",
    "vwma100_value_missing": "VWMA100 값을 확인할 수 없다.",
    "sma50_slope_missing": "SMA50 기울기 근거가 부족하다.",
    "sma200_slope_missing": "SMA200 기울기 근거가 부족하다.",
    "vwma100_slope_missing": "VWMA100 기울기 근거가 부족하다.",
    "sma50_distance_missing": "종가와 SMA50의 이격도 근거가 부족하다.",
    "sma200_distance_missing": "종가와 SMA200의 이격도 근거가 부족하다.",
    "vwma100_distance_missing": "종가와 VWMA100의 이격도 근거가 부족하다.",
    "signed_gap_missing": "SMA50과 SMA200의 부호 있는 간격이 누락되었다.",
    "gap_trend_missing": "이동평균 간격 추세를 확인할 수 없다.",
    "bars_insufficient": "이동평균 계산에 필요한 봉 수가 부족하다.",
    "data_stale": "마지막 봉이 판단 시점과 정렬되지 않았다.",
    "provider_partial": "KIS 제공 데이터가 부분 상태다.",
    "hypothesis_unsupported": "선택한 가설을 지지할 근거가 부족하다.",
    "redundant_ma_confirmation": "이동평균 근거를 중복 확인했다.",
    "redundant_distance_confirmation": "이격도 근거를 중복 확인했다.",
    "redundant_volume_confirmation": "거래량 근거를 중복 확인했다.",
    "single_signal_overweighted": "하나의 신호에 확인이 과도하게 집중되었다.",
    "golden_gap_direction_conflict": "골든크로스 가설과 간격 방향이 충돌한다.",
    "dead_gap_direction_conflict": "데드크로스 가설과 간격 방향이 충돌한다.",
    "slope_hypothesis_conflict": "이동평균 기울기와 선택한 가설이 충돌한다.",
    "vwma_hypothesis_conflict": "VWMA100 방향과 선택한 가설이 충돌한다.",
    "price_distance_hypothesis_conflict": "가격 이격도와 선택한 가설이 충돌한다.",
    "provider_data_conflict": "provider 상태와 사용된 근거가 충돌한다.",
}
_SUMMARY_TEXT: Final[dict[ReviewOverallAssessment, str]] = {
    ReviewOverallAssessment.INSUFFICIENT: "판단을 뒷받침할 근거가 부족한 상태다.",
    ReviewOverallAssessment.BALANCED: "판단 근거의 균형이 적절한 상태다.",
    ReviewOverallAssessment.OVERCONFIRMED: "중복된 확인이 판단보다 앞선 상태다.",
    ReviewOverallAssessment.CONFLICTED: "가설과 측정 근거가 서로 충돌하는 상태다.",
}
class SelectionConsistencyError(ValueError):
    def __init__(self) -> None:
        super().__init__("Hermes selection codes are inconsistent")


class HermesAuthoredSelection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    overall_assessment: ReviewOverallAssessment
    sufficient_codes: tuple[SufficientCode, ...] = Field(max_length=17)
    missing_codes: tuple[MissingCode, ...] = Field(max_length=15)
    excessive_codes: tuple[ExcessiveCode, ...] = Field(max_length=4)
    contradiction_codes: tuple[ContradictionCode, ...] = Field(max_length=6)
    note_quality_code: NoteQualityCode

    @model_validator(mode="after")
    def validate_consistency(self) -> HermesAuthoredSelection:
        groups = (
            self.sufficient_codes,
            self.missing_codes,
            self.excessive_codes,
            self.contradiction_codes,
        )
        selected = tuple(code for group in groups for code in group)
        if len(selected) != len(set(selected)):
            raise SelectionConsistencyError
        selected_set = set(selected)
        exclusive_groups = (
            {"gap_narrowing", "gap_widening", "gap_flat"},
            {"bars_sufficient", "bars_insufficient"},
            {"data_fresh", "data_stale"},
            {"provider_complete", "provider_partial"},
            {"hypothesis_aligned", "hypothesis_unsupported"},
        )
        counterpart_stems = (
            "sma50_value", "sma200_value", "vwma100_value",
            "sma50_slope", "sma200_slope", "vwma100_slope",
            "sma50_distance", "sma200_distance", "vwma100_distance",
            "signed_gap",
        )
        exclusive = any(len(selected_set & group) > 1 for group in exclusive_groups)
        counterparts = any(
            {f"{stem}_available", f"{stem}_missing"} <= selected_set
            for stem in counterpart_stems
        )
        if exclusive or counterparts or not self._assessment_matches():
            raise SelectionConsistencyError
        return self

    def _assessment_matches(self) -> bool:
        checks = {
            ReviewOverallAssessment.INSUFFICIENT: bool(self.missing_codes)
            and not (self.excessive_codes or self.contradiction_codes),
            ReviewOverallAssessment.BALANCED: bool(self.sufficient_codes)
            and not (
                self.missing_codes
                or self.excessive_codes
                or self.contradiction_codes
            ),
            ReviewOverallAssessment.OVERCONFIRMED: bool(self.excessive_codes)
            and not self.contradiction_codes,
            ReviewOverallAssessment.CONFLICTED: bool(self.contradiction_codes),
        }
        return checks[self.overall_assessment]


class HermesWorkerEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["hermes_worker_envelope.v1"]
    review_created_at_utc: AwareDatetime
    review_model: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:/-]+$",
    )
    review_profile: Literal["trading"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: HermesAuthoredSelection

    @field_validator("review_created_at_utc")
    @classmethod
    def normalize_created_at(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)


def selection_to_review(
    envelope: HermesWorkerEnvelope,
    *,
    revised_decision_note: str,
) -> DecisionReview:
    selection = envelope.selection
    return DecisionReview(
        review_created_at_utc=envelope.review_created_at_utc,
        review_model=envelope.review_model,
        review_profile=envelope.review_profile,
        overall_assessment=selection.overall_assessment,
        summary=_SUMMARY_TEXT[selection.overall_assessment],
        sufficient_evidence=map_finding_codes(selection.sufficient_codes),
        missing_evidence=map_finding_codes(selection.missing_codes),
        excessive_evidence=map_finding_codes(selection.excessive_codes),
        contradictions=map_finding_codes(selection.contradiction_codes),
        revised_decision_note=revised_decision_note,
        risk_note=RISK_NOTE,
    )


def map_finding_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_CODE_TEXT[code] for code in codes)
