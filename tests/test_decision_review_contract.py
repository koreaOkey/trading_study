import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fractal_journal.ai_review import (
    RISK_NOTE,
    DecisionReview,
    DecisionReviewFailure,
    DecisionReviewFailureCode,
    DecisionReviewResult,
    DecisionReviewStatus,
)
from fractal_journal.schemas import (
    EvidenceDataStatus,
    GapTrend,
    IndicatorMeasurement,
    MaCrossoverEvidence,
)


@pytest.mark.parametrize(
    ("field", "expected", "invalid"),
    [
        ("schema_version", "decision_review.v1", "decision_review.v2"),
        ("review_profile", "trading", "general"),
    ],
)
def test_decision_review_rejects_wrong_contract_constants(
    field: str,
    expected: str,
    invalid: str,
) -> None:
    # Given
    raw = _contract_json().replace(
        f'"{field}": "{expected}"'.encode(),
        f'"{field}": "{invalid}"'.encode(),
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = DecisionReview.model_validate_json(raw)

    # Then
    assert raised.value.error_count() == 1


def test_decision_review_rejects_naive_created_at() -> None:
    # Given
    raw = _contract_json().replace(b"2026-07-10T01:00:00Z", b"2026-07-10T01:00:00")

    # When
    with pytest.raises(ValidationError) as raised:
        _ = DecisionReview.model_validate_json(raw)

    # Then
    assert raised.value.errors()[0]["type"] == "timezone_aware"


def test_decision_review_normalizes_offset_created_at_to_utc_json() -> None:
    # Given
    raw = _contract_json().replace(
        b"2026-07-10T01:00:00Z",
        b"2026-07-10T10:00:00+09:00",
    )

    # When
    review = DecisionReview.model_validate_json(raw)
    serialized = review.model_dump_json()

    # Then
    assert review.review_created_at_utc == datetime(2026, 7, 10, 1, tzinfo=UTC)
    assert '"review_created_at_utc":"2026-07-10T01:00:00Z"' in serialized


def test_decision_review_rejects_non_server_risk_note() -> None:
    # Given
    raw = _contract_json().replace(
        RISK_NOTE.encode(),
        b"This is safe enough.",
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = DecisionReview.model_validate_json(raw)

    # Then
    assert raised.value.error_count() == 1


def test_decision_review_result_accepts_ready_payload() -> None:
    # When
    result = DecisionReviewResult(
        capture_id="capture-1",
        status=DecisionReviewStatus.READY,
        review=_review(),
    )

    # Then
    assert result.review is not None
    assert result.failure is None


def test_decision_review_result_accepts_failed_payload() -> None:
    # When
    result = DecisionReviewResult(
        capture_id="capture-1",
        status=DecisionReviewStatus.FAILED,
        failure=_failure(),
    )

    # Then
    assert result.review is None
    assert result.failure is not None


def test_decision_review_result_rejects_failed_without_failure() -> None:
    # When
    with pytest.raises(ValidationError) as raised:
        _ = DecisionReviewResult(
            capture_id="capture-1",
            status=DecisionReviewStatus.FAILED,
        )

    # Then
    assert raised.value.error_count() == 1


def test_decision_review_result_rejects_failed_with_both_payloads() -> None:
    # When
    with pytest.raises(ValidationError) as raised:
        _ = DecisionReviewResult(
            capture_id="capture-1",
            status=DecisionReviewStatus.FAILED,
            review=_review(),
            failure=_failure(),
        )

    # Then
    assert raised.value.error_count() == 1


def test_decision_review_result_rejects_wrong_schema_version() -> None:
    # Given
    result = DecisionReviewResult(
        capture_id="capture-1",
        status=DecisionReviewStatus.READY,
        evidence=_evidence(),
        review=_review(),
    )
    raw = result.model_dump_json().replace(
        '"decision_review_result.v1"',
        '"decision_review_result.v2"',
        1,
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = DecisionReviewResult.model_validate_json(raw)

    # Then
    assert raised.value.errors()[0]["loc"] == ("schema_version",)


def test_ma_crossover_evidence_rejects_wrong_schema_version() -> None:
    # Given
    raw = _evidence().model_dump_json().replace(
        '"ma_crossover_evidence.v1"',
        '"ma_crossover_evidence.v2"',
        1,
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = MaCrossoverEvidence.model_validate_json(raw)

    # Then
    assert raised.value.errors()[0]["loc"] == ("schema_version",)


def test_decision_review_result_serializes_extension_contract_versions() -> None:
    # Given
    result = DecisionReviewResult(
        capture_id="capture-1",
        status=DecisionReviewStatus.READY,
        evidence=_evidence(),
        review=_review(),
    )

    # When
    serialized = result.model_dump_json()

    # Then
    assert '"schema_version":"decision_review_result.v1"' in serialized
    assert '"schema_version":"ma_crossover_evidence.v1"' in serialized


def _review() -> DecisionReview:
    return DecisionReview.model_validate_json(_contract_json())


def _failure() -> DecisionReviewFailure:
    return DecisionReviewFailure(
        code=DecisionReviewFailureCode.HERMES_TIMEOUT,
        message="Hermes reviewer timed out",
        retryable=True,
        review_model="gpt-5.5",
        review_profile="trading",
    )


def _evidence() -> MaCrossoverEvidence:
    measurement = IndicatorMeasurement(
        value=Decimal(100),
        previous_value=Decimal(99),
        bars_used=200,
    )
    return MaCrossoverEvidence(
        provider="kis",
        provider_symbol="005930",
        timeframe="5",
        decision_time_exchange=datetime.fromisoformat("2026-07-10T10:00:00+09:00"),
        data_status=EvidenceDataStatus.READY,
        bar_count=200,
        last_bar_time_exchange=datetime.fromisoformat("2026-07-10T10:00:00+09:00"),
        sma_50=measurement,
        sma_200=measurement,
        vwma_100=measurement,
        gap_trend=GapTrend.NARROWING,
    )


def _contract_json() -> bytes:
    return json.dumps(
        {
            "schema_version": "decision_review.v1",
            "review_created_at_utc": "2026-07-10T01:00:00Z",
            "review_model": "gpt-5.5",
            "review_profile": "trading",
            "overall_assessment": "balanced",
            "summary": "balanced evidence",
            "risk_note": RISK_NOTE,
        },
        ensure_ascii=False,
    ).encode()
