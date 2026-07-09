from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fractal_journal.schemas import CaptureRecord
from fractal_journal.scoring import ScoreResult

BLOCKED_ACTION_TERMS = ("매수하세요", "매도하세요", "손절하세요", "진입하세요")
RISK_NOTE = (
    "기술적 분석은 확률적 시나리오 정리이며 수익 보장이나 "
    "개인화된 투자 지시가 아니다."
)


class ScoreBoundaryValidationError(ValueError):
    def __init__(self) -> None:
        super().__init__("score boundary invalid")


class RiskNoteValidationError(ValueError):
    def __init__(self) -> None:
        super().__init__("risk note required")


class AIReviewResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: str = "ai_review_output.v0"
    review_request_id: str
    capture_id: str
    review_created_at_utc: datetime
    review_model: str = "local-safety-template"
    one_line_review: str
    risk_note: str
    scenario_rating: str
    failure_tags: tuple[str, ...]
    process_tags: tuple[str, ...]
    learning_loop_candidate: bool
    learning_loop_reason: str
    ai_review_can_override_score: bool = False
    safety_passed: bool
    blocked_terms_found: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_score_boundary(self) -> "AIReviewResult":
        if self.ai_review_can_override_score:
            raise ScoreBoundaryValidationError
        if not self.risk_note:
            raise RiskNoteValidationError
        return self


def create_local_ai_review(
    capture: CaptureRecord,
    score: ScoreResult,
) -> AIReviewResult:
    text = _review_text(capture, score)
    blocked = tuple(term for term in BLOCKED_ACTION_TERMS if term in text)
    process_tags = ["confirmed-metadata-used"]
    if score.provider_window.data_status == "partial_data":
        process_tags.append("partial-data")
    if score.provider_window.warnings:
        process_tags.append("alignment-warning")
    failure_tags: list[str] = []
    if not capture.notes:
        failure_tags.append("invalidation-missing")
    rating = "insufficient_data" if score.metric_null_reasons else "adequate"
    loop_reason = "provider/scoring warning review needed" if score.warnings else "none"
    return AIReviewResult(
        review_request_id=str(uuid4()),
        capture_id=str(capture.id),
        review_created_at_utc=datetime.now(UTC),
        one_line_review=text,
        risk_note=RISK_NOTE,
        scenario_rating=rating,
        failure_tags=tuple(failure_tags),
        process_tags=tuple(process_tags),
        learning_loop_candidate=bool(score.warnings),
        learning_loop_reason=loop_reason,
        safety_passed=not blocked,
        blocked_terms_found=blocked,
    )


def _review_text(capture: CaptureRecord, score: ScoreResult) -> str:
    warning_count = len(score.warnings)
    return (
        f"{capture.confirmed.symbol} {capture.confirmed.timeframe} 복기: "
        f"confirmed metadata 기준으로 {score.score_version} 점수가 생성됐고 "
        f"경고 {warning_count}개를 함께 확인해야 한다."
    )
