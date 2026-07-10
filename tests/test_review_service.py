from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from fractal_journal.ai_review import (
    RISK_NOTE,
    DecisionReview,
    DecisionReviewFailureCode,
    DecisionReviewResult,
    ReviewOverallAssessment,
)
from fractal_journal.config import Settings
from fractal_journal.hermes_review import (
    HermesReviewError,
    HermesReviewOutput,
)
from fractal_journal.main import create_app
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    HistoricalProvenance,
    HistoricalStopReason,
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvBar,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
DECISION_TIME = datetime.fromisoformat("2026-07-09T10:00:00+09:00")


class RecordingProvider:
    def __init__(self, result: HistoricalBarsResult) -> None:
        self.result = result
        self.history_requests: list[HistoricalBarsRequest] = []
        self.minute_window_calls = 0

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        self.minute_window_calls += 1
        raise AssertionError(request)

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        self.history_requests.append(request)
        return self.result


class BlockingProvider(RecordingProvider):
    def __init__(self, result: HistoricalBarsResult) -> None:
        super().__init__(result)
        self.entered = Event()
        self.release = Event()

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        self.entered.set()
        assert self.release.wait(timeout=10)
        return super().fetch_historical_bars(request)


class RecordingReviewer:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def review(self, capture, evidence) -> HermesReviewOutput:  # noqa: ANN001
        self.calls += 1
        if self.fail:
            raise HermesReviewError(
                code=DecisionReviewFailureCode.HERMES_TIMEOUT,
                message="Hermes reviewer timed out",
                retryable=True,
            )
        return HermesReviewOutput(
            review=DecisionReview(
                review_created_at_utc=datetime(2026, 7, 10, 1, tzinfo=UTC),
                review_model="test-model",
                review_profile="trading",
                overall_assessment=ReviewOverallAssessment.BALANCED,
                summary="근거가 대체로 균형적이다.",
                sufficient_evidence=("SMA 간격 축소",),
                missing_evidence=("거래량 확장",),
                risk_note=RISK_NOTE,
            ),
            raw_output_sha256=sha256(b"review").hexdigest(),
        )


def test_post_review_uses_history_only_persists_and_retry_does_not_duplicate_capture(
    tmp_path: Path,
) -> None:
    # Given
    token = tmp_path.name
    provider = RecordingProvider(_history_result(201))
    reviewer = RecordingReviewer()
    app = create_app(_settings(tmp_path, token), provider=provider, reviewer=reviewer)

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)
        before = _capture_count(client, token)

        # When
        first = client.post(_review_path(capture_id), headers=_auth(token))
        second = client.post(_review_path(capture_id), headers=_auth(token))
        retrieved = client.get(_review_path(capture_id), headers=_auth(token))
        after = _capture_count(client, token)

    # Then
    first_result = DecisionReviewResult.model_validate_json(first.text)
    second_result = DecisionReviewResult.model_validate_json(second.text)
    stored_result = DecisionReviewResult.model_validate_json(retrieved.text)
    assert first_result.status == "ready"
    assert second_result == first_result
    assert stored_result == second_result
    assert before == after == 1
    assert reviewer.calls == 2
    assert provider.minute_window_calls == 0
    assert len(provider.history_requests) == 2
    assert provider.history_requests[0].decision_time_exchange == DECISION_TIME
    assert provider.history_requests[0].target_bars == 201


def test_post_review_fails_closed_without_kis_and_does_not_call_hermes(
    tmp_path: Path,
) -> None:
    # Given
    token = tmp_path.name
    provider = RecordingProvider(_history_result(0, provider="fixture"))
    reviewer = RecordingReviewer()
    app = create_app(_settings(tmp_path, token), provider=provider, reviewer=reviewer)

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)

        # When
        response = client.post(_review_path(capture_id), headers=_auth(token))

    # Then
    result = DecisionReviewResult.model_validate_json(response.text)
    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.code is DecisionReviewFailureCode.EVIDENCE_UNAVAILABLE
    assert result.evidence is None
    assert reviewer.calls == 0


def test_post_review_sends_partial_usable_evidence_to_hermes(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    provider = RecordingProvider(
        _history_result(100, status=HistoricalDataStatus.PARTIAL_DATA),
    )
    reviewer = RecordingReviewer()
    app = create_app(_settings(tmp_path, token), provider=provider, reviewer=reviewer)

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)

        # When
        response = client.post(_review_path(capture_id), headers=_auth(token))

    # Then
    result = DecisionReviewResult.model_validate_json(response.text)
    assert result.status == "ready"
    assert result.evidence is not None
    assert result.evidence.data_status == "partial"
    assert result.evidence.sma_200.value is None
    assert reviewer.calls == 1


def test_failed_retry_overwrites_stale_ready_review(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    reviewer = RecordingReviewer()
    app = create_app(
        _settings(tmp_path, token),
        provider=RecordingProvider(_history_result(201)),
        reviewer=reviewer,
    )

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)
        ready = client.post(_review_path(capture_id), headers=_auth(token))
        reviewer.fail = True

        # When
        failed = client.post(_review_path(capture_id), headers=_auth(token))
        retrieved = client.get(_review_path(capture_id), headers=_auth(token))

    # Then
    assert DecisionReviewResult.model_validate_json(ready.text).status == "ready"
    failed_result = DecisionReviewResult.model_validate_json(failed.text)
    assert failed_result.status == "failed"
    assert failed_result.failure is not None
    assert failed_result.failure.code is DecisionReviewFailureCode.HERMES_TIMEOUT
    assert DecisionReviewResult.model_validate_json(retrieved.text) == failed_result
    assert not tuple((tmp_path / "decision_reviews").glob("*.tmp"))


def test_review_get_reports_pending_and_invalid_id_is_not_found(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    app = create_app(
        _settings(tmp_path, token),
        provider=RecordingProvider(_history_result(201)),
        reviewer=RecordingReviewer(),
    )

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)

        # When
        pending = client.get(_review_path(capture_id), headers=_auth(token))
        invalid = client.post("/api/captures/not-an-id/ai-review", headers=_auth(token))

    # Then
    assert pending.status_code == 200
    assert pending.json() == {"detail": "ai_review_pending"}
    assert invalid.status_code == 404


def test_capture_detail_reports_pending_when_review_is_absent(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    app = create_app(
        _settings(tmp_path, token),
        provider=RecordingProvider(_history_result(201)),
        reviewer=RecordingReviewer(),
    )

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)

        # When
        detail = client.get(f"/api/captures/{capture_id}", headers=_auth(token))

    # Then
    assert detail.json()["ai_review_status"] == "pending"


def test_capture_detail_reports_ready_for_successful_review(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    app = create_app(
        _settings(tmp_path, token),
        provider=RecordingProvider(_history_result(201)),
        reviewer=RecordingReviewer(),
    )

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)
        _ = client.post(_review_path(capture_id), headers=_auth(token))

        # When
        detail = client.get(f"/api/captures/{capture_id}", headers=_auth(token))

    # Then
    assert detail.json()["ai_review_status"] == "ready"


def test_capture_detail_reports_failed_for_failed_review(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    app = create_app(
        _settings(tmp_path, token),
        provider=RecordingProvider(_history_result(0, provider="fixture")),
        reviewer=RecordingReviewer(),
    )

    with TestClient(app) as client:
        capture_id = _create_capture(client, token)
        _ = client.post(_review_path(capture_id), headers=_auth(token))

        # When
        detail = client.get(f"/api/captures/{capture_id}", headers=_auth(token))

    # Then
    assert detail.json()["ai_review_status"] == "failed"


def test_blocked_review_does_not_block_async_health_route(tmp_path: Path) -> None:
    # Given
    token = tmp_path.name
    provider = BlockingProvider(_history_result(201))
    app = create_app(
        _settings(tmp_path, token),
        provider=provider,
        reviewer=RecordingReviewer(),
    )

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        capture_id = _create_capture(client, token)
        review_future = executor.submit(
            client.post,
            _review_path(capture_id),
            headers=_auth(token),
        )
        assert provider.entered.wait(timeout=2)
        health_future = executor.submit(client.get, "/health")

        # When
        try:
            health_response = health_future.result(timeout=2)
        finally:
            provider.release.set()
        review_response = review_future.result(timeout=2)

    # Then
    assert health_response.status_code == 200
    assert review_response.status_code == 200


def _settings(tmp_path: Path, token: str) -> Settings:
    return Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        api_token=token,
        kis_env_path=tmp_path / "missing.env",
    )


def _create_capture(client: TestClient, token: str) -> str:
    response = client.post("/api/captures", json=_payload(), headers=_auth(token))
    assert response.status_code == 201
    return str(response.json()["capture"]["id"])


def _capture_count(client: TestClient, token: str) -> int:
    response = client.get("/api/captures", headers=_auth(token))
    assert response.status_code == 200
    return len(response.json()["captures"])


def _review_path(capture_id: str) -> str:
    return f"/api/captures/{capture_id}/ai-review"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload() -> dict[str, str | list[str] | dict[str, str | bool]]:
    screenshot = b64encode(PNG_1X1).decode("ascii")
    return {
        "screenshot_data_url": f"data:image/png;base64,{screenshot}",
        "extracted": {
            "source_url": "https://www.tradingview.com/chart/example/",
            "page_title": "005930 5 Samsung Electronics",
            "symbol_candidate": "005930",
            "timeframe_candidate": "5",
            "decision_time_candidate": DECISION_TIME.isoformat(),
            "replay_active": True,
            "captured_at": DECISION_TIME.astimezone(UTC).isoformat(),
        },
        "confirmed": {
            "symbol": "005930",
            "provider_symbol": "005930",
            "market_div_code": "J",
            "timeframe": "5",
            "decision_time_exchange": DECISION_TIME.isoformat(),
            "exchange_tz": "Asia/Seoul",
            "provider_status": "ready",
        },
        "setup": "ma_crossover",
        "hypothesis": "golden_cross_expected",
        "decision_note": "SMA50이 SMA200에 수렴하고 VWMA100이 지지한다.",
        "warnings": ["price_basis_unverified"],
    }


def _history_result(
    count: int,
    *,
    provider: str = "kis",
    status: HistoricalDataStatus = HistoricalDataStatus.OK,
) -> HistoricalBarsResult:
    bars = tuple(_bar(index, count) for index in range(count))
    unavailable = provider == "fixture"
    stop_reason = (
        HistoricalStopReason.PROVIDER_UNAVAILABLE
        if unavailable
        else HistoricalStopReason.TARGET_REACHED
    )
    return HistoricalBarsResult(
        provider=provider,
        status=(HistoricalDataStatus.PROVIDER_UNAVAILABLE if unavailable else status),
        bars=bars,
        provenance=HistoricalProvenance(
            endpoint=f"{provider}://history",
            tr_id="FHKST03010230",
            request_end_exchange=DECISION_TIME,
            aggregated_timeframe_minutes=5 if not unavailable else None,
            target_bars=201,
            page_count=1 if bars else 0,
            raw_bar_count=len(bars),
            unique_minute_bar_count=len(bars),
            future_bars_filtered=0,
            price_basis="unknown_unadjusted_assumed",
            api_message_codes=(),
            last_cursor_exchange=bars[0].time_utc if bars else None,
            raw_response_sha256=sha256(b"bars").hexdigest(),
            stop_reason=stop_reason,
        ),
    )


def _bar(index: int, count: int) -> OhlcvBar:
    time_exchange = DECISION_TIME - timedelta(minutes=5 * (count - index - 1))
    close = Decimal(100000 + index)
    return OhlcvBar(
        time_utc=time_exchange.astimezone(UTC),
        time_exchange=time_exchange.isoformat(),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000 + index,
    )
