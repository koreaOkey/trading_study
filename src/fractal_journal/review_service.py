import json
from dataclasses import dataclass
from datetime import datetime
from decimal import InvalidOperation

import httpx2
from pydantic import ValidationError

from fractal_journal.ai_review import (
    DecisionReviewFailure,
    DecisionReviewFailureCode,
    DecisionReviewResult,
    DecisionReviewStatus,
)
from fractal_journal.hermes_review import DecisionReviewer, HermesReviewError
from fractal_journal.indicators import (
    MaCrossoverEvidenceContext,
    calculate_ma_crossover_evidence,
)
from fractal_journal.kis_auth import KisTokenIssueError
from fractal_journal.provider import HistoricalBarsRequest, OhlcvProvider
from fractal_journal.schemas import CaptureRecord, EvidenceDataStatus

EVIDENCE_UNAVAILABLE_MESSAGE = "KIS decision evidence is unavailable"
HERMES_FAILURE_MESSAGE = "Hermes decision review failed"
REVIEW_PROFILE = "trading"


@dataclass(frozen=True, slots=True)
class DecisionReviewService:
    provider: OhlcvProvider
    reviewer: DecisionReviewer

    def review_capture(self, capture: CaptureRecord) -> DecisionReviewResult:
        if capture.confirmed.provider == "fixture":
            return _evidence_failure(capture)
        try:
            request = HistoricalBarsRequest(
                provider_symbol=capture.confirmed.provider_symbol,
                market_div_code=capture.confirmed.market_div_code,
                decision_time_exchange=datetime.fromisoformat(
                    capture.confirmed.decision_time_exchange,
                ),
                timeframe=capture.confirmed.timeframe,
                target_bars=201,
                price_basis_policy=capture.confirmed.price_basis,
            )
            history = self.provider.fetch_historical_bars(request)
        except (
            httpx2.HTTPError,
            InvalidOperation,
            json.JSONDecodeError,
            KisTokenIssueError,
            ValidationError,
            ValueError,
        ):
            return _evidence_failure(capture)

        if history.provider == "fixture" or not history.bars:
            return _evidence_failure(capture)

        evidence = calculate_ma_crossover_evidence(
            history.bars,
            MaCrossoverEvidenceContext(
                provider=history.provider,
                provider_symbol=capture.confirmed.provider_symbol,
                timeframe=capture.confirmed.timeframe,
                decision_time_exchange=request.decision_time_exchange,
                provider_data_status=history.status.value,
            ),
        )
        if evidence.data_status is EvidenceDataStatus.UNAVAILABLE:
            return _evidence_failure(capture)

        try:
            output = self.reviewer.review(capture, evidence)
        except HermesReviewError as exc:
            return DecisionReviewResult(
                capture_id=str(capture.id),
                status=DecisionReviewStatus.FAILED,
                evidence=evidence,
                failure=DecisionReviewFailure(
                    code=exc.code,
                    message=HERMES_FAILURE_MESSAGE,
                    retryable=exc.retryable,
                    review_model="unknown",
                    review_profile=REVIEW_PROFILE,
                ),
            )
        return DecisionReviewResult(
            capture_id=str(capture.id),
            status=DecisionReviewStatus.READY,
            evidence=evidence,
            review=output.review,
        )


def _evidence_failure(capture: CaptureRecord) -> DecisionReviewResult:
    return DecisionReviewResult(
        capture_id=str(capture.id),
        status=DecisionReviewStatus.FAILED,
        failure=DecisionReviewFailure(
            code=DecisionReviewFailureCode.EVIDENCE_UNAVAILABLE,
            message=EVIDENCE_UNAVAILABLE_MESSAGE,
            retryable=True,
            review_model="not-invoked",
            review_profile=REVIEW_PROFILE,
        ),
    )
