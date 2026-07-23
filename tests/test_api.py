from base64 import b64encode
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fractal_journal.ai_review import DecisionReviewFailureCode, DecisionReviewResult
from fractal_journal.config import Settings
from fractal_journal.main import create_app
from fractal_journal.provider import FixtureOhlcvProvider
from fractal_journal.schemas import (
    CaptureCreate,
    CaptureListResponse,
    CaptureRecord,
    CaptureResponse,
)
from fractal_journal.scoring import ScoreResult

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class CaptureBaseJson(TypedDict):
    screenshot_data_url: str
    extracted: "ExtractedJson"
    confirmed: "ConfirmedJson"
    warnings: list[str]


class JsonMap(CaptureBaseJson):
    setup: str
    hypothesis: str
    decision_note: str


class LegacyCaptureJson(CaptureBaseJson):
    decision: str
    notes: str


class ExtractedJson(TypedDict):
    source_url: str
    page_title: str
    symbol_candidate: str
    timeframe_candidate: str
    decision_time_candidate: str
    replay_active: bool
    captured_at: str


class ConfirmedJson(TypedDict):
    symbol: str
    provider: NotRequired[str]
    provider_symbol: str
    market_div_code: str
    timeframe: str
    decision_time_exchange: str
    exchange_tz: str
    price_basis: NotRequired[str]
    session_state: NotRequired[str]
    provider_status: str
    scenario: NotRequired[str]
    confidence: NotRequired[int]
    invalidation: NotRequired[str]


def test_create_and_list_capture(tmp_path: Path) -> None:
    token = tmp_path.name
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token=token,
        ),
        provider=FixtureOhlcvProvider(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/captures",
            json=_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        body = CaptureResponse.model_validate_json(response.text)
        assert body.capture.confirmed.symbol == "005930"
        assert body.capture.setup == "ma_crossover"
        assert body.capture.hypothesis == "golden_cross_expected"
        assert body.capture.decision_note == _payload()["decision_note"]
        assert body.capture.warnings == ("price_basis_unverified",)

        capture_id = str(body.capture.id)
        score_response = client.post(
            f"/api/captures/{capture_id}/score",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert score_response.status_code == 200
        score = ScoreResult.model_validate_json(score_response.text)
        assert score.score_version == "score.v0"

        review_response = client.post(
            f"/api/captures/{capture_id}/ai-review",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert review_response.status_code == 200
        review = DecisionReviewResult.model_validate_json(review_response.text)
        assert review.status == "failed"
        assert review.failure is not None
        assert review.failure.code is DecisionReviewFailureCode.EVIDENCE_UNAVAILABLE

        list_response = client.get(
            "/api/captures",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_response.status_code == 200
        captures = CaptureListResponse.model_validate_json(list_response.text)
        assert len(captures.captures) == 1


def test_token_is_enforced(tmp_path: Path) -> None:
    token = tmp_path.name
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token=token,
        ),
    )
    with TestClient(app) as client:
        rejected = client.get("/api/captures")
        assert rejected.status_code == 401
        accepted = client.get(
            "/api/captures",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert accepted.status_code == 200


def test_write_without_configured_token_rejects_allowed_extension_origin(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token="",
            allowed_extension_origins=["chrome-extension://abc"],
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/captures",
            json=_payload(),
            headers={"Origin": "chrome-extension://abc"},
        )
        assert response.status_code == 401


def test_write_with_configured_token_rejects_missing_auth(tmp_path: Path) -> None:
    token = tmp_path.name
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token=token,
            allowed_extension_origins=["chrome-extension://abc"],
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/captures",
            json=_payload(),
            headers={"Origin": "chrome-extension://abc"},
        )
        assert response.status_code == 401


def test_write_with_valid_token_succeeds(tmp_path: Path) -> None:
    token = tmp_path.name
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token=token,
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/captures",
            json=_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201


def test_invalid_screenshot_rejected(tmp_path: Path) -> None:
    token = tmp_path.name
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token=token,
        ),
    )
    payload = _payload()
    payload["screenshot_data_url"] = "data:image/png;base64,ZmFrZQ=="
    with TestClient(app) as client:
        response = client.post(
            "/api/captures",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422


def test_capture_rejects_decision_time_without_timezone(tmp_path: Path) -> None:
    token = tmp_path.name
    payload = _payload()
    payload["confirmed"]["decision_time_exchange"] = "2026-07-09T10:00:00"
    app = create_app(
        Settings(
            data_dir=tmp_path,
            screenshot_dir=tmp_path / "screenshots",
            api_token=token,
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/captures",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422


def test_capture_create_accepts_ma_crossover_payload_without_legacy_ui_fields() -> None:
    # Given
    payload = _payload()

    # When
    capture = CaptureCreate.model_validate(payload)

    # Then
    assert capture.setup == "ma_crossover"
    assert capture.hypothesis == "golden_cross_expected"
    assert capture.decision_note == "SMA50이 SMA200에 수렴하고 VWMA100이 지지한다."


def test_capture_create_rejects_unknown_hypothesis() -> None:
    # Given
    payload = _payload()
    payload["hypothesis"] = "bullish_cross"

    # When
    with pytest.raises(ValidationError) as exc_info:
        _ = CaptureCreate.model_validate(payload)

    # Then
    assert any(error["loc"] == ("hypothesis",) for error in exc_info.value.errors())


def test_capture_create_rejects_payload_without_new_or_legacy_contract() -> None:
    # Given
    new_payload = _payload()
    payload = _capture_base(new_payload)

    # When
    with pytest.raises(ValidationError) as exc_info:
        _ = CaptureCreate.model_validate(payload)

    # Then
    assert any(
        error["type"] == "capture_payload_variant"
        for error in exc_info.value.errors()
    )


def test_capture_create_accepts_complete_legacy_contract() -> None:
    # Given
    new_payload = _payload()
    payload = LegacyCaptureJson(
        **_capture_base(new_payload),
        decision="watch",
        notes="레거시 판단 메모",
    )

    # When
    capture = CaptureCreate.model_validate(payload)

    # Then
    assert capture.decision == "watch"
    assert capture.notes == "레거시 판단 메모"
    assert capture.effective_decision_note == "레거시 판단 메모"


def test_capture_create_accepts_legacy_decision_without_notes_key() -> None:
    # Given
    new_payload = _payload()
    payload = {**_capture_base(new_payload), "decision": "watch"}

    # When
    capture = CaptureCreate.model_validate(payload)

    # Then
    assert capture.decision == "watch"
    assert capture.notes == ""
    assert capture.effective_decision_note == ""


def test_capture_create_rejects_new_contract_with_partial_legacy_fields() -> None:
    # Given
    payload = {**_payload(), "decision": "watch"}

    # When
    with pytest.raises(ValidationError) as exc_info:
        _ = CaptureCreate.model_validate(payload)

    # Then
    assert any(
        error["type"] == "capture_payload_variant"
        for error in exc_info.value.errors()
    )


def test_capture_create_rejects_legacy_contract_with_partial_new_fields() -> None:
    # Given
    new_payload = _payload()
    payload = LegacyCaptureJson(
        **_capture_base(new_payload),
        decision="watch",
        notes="레거시 판단 메모",
    )
    payload_with_setup = {**payload, "setup": "ma_crossover"}

    # When
    with pytest.raises(ValidationError) as exc_info:
        _ = CaptureCreate.model_validate(payload_with_setup)

    # Then
    assert any(
        error["type"] == "capture_payload_variant"
        for error in exc_info.value.errors()
    )


def test_capture_record_reads_legacy_decision_notes_and_invalidation() -> None:
    # Given
    payload = _payload()
    legacy_record = {
        "id": "0123456789abcdef01234567",
        "created_at": "2026-07-09T01:00:00Z",
        "screenshot_sha256": "a" * 64,
        "screenshot_path": "screenshots/legacy.png",
        "extracted": payload["extracted"],
        "confirmed": {
            **payload["confirmed"],
            "invalidation": "SMA50이 다시 하락 전환하면 무효",
        },
        "decision": "watch",
        "notes": "레거시 판단 메모",
        "warnings": ["price_basis_unverified"],
    }

    # When
    capture = CaptureRecord.model_validate(legacy_record)

    # Then
    assert capture.decision == "watch"
    assert capture.notes == "레거시 판단 메모"
    assert capture.confirmed.invalidation == "SMA50이 다시 하락 전환하면 무효"


def _payload() -> JsonMap:
    screenshot = b64encode(PNG_1X1).decode("ascii")
    captured_at = datetime(2026, 7, 9, 10, 0, tzinfo=UTC).isoformat()
    return {
        "screenshot_data_url": f"data:image/png;base64,{screenshot}",
        "extracted": {
            "source_url": "https://www.tradingview.com/chart/example/",
            "page_title": "005930 1 Samsung Electronics",
            "symbol_candidate": "005930",
            "timeframe_candidate": "1D",
            "decision_time_candidate": "2026-07-09T10:00:00+09:00",
            "replay_active": True,
            "captured_at": captured_at,
        },
        "confirmed": {
            "symbol": "005930",
            "provider_symbol": "005930",
            "market_div_code": "J",
            "timeframe": "1D",
            "decision_time_exchange": "2026-07-09T10:00:00+09:00",
            "exchange_tz": "Asia/Seoul",
            "provider_status": "candidate",
        },
        "setup": "ma_crossover",
        "hypothesis": "golden_cross_expected",
        "decision_note": "SMA50이 SMA200에 수렴하고 VWMA100이 지지한다.",
        "warnings": ["price_basis_unverified"],
    }


def _capture_base(payload: JsonMap) -> CaptureBaseJson:
    return {
        "screenshot_data_url": payload["screenshot_data_url"],
        "extracted": payload["extracted"],
        "confirmed": payload["confirmed"],
        "warnings": payload["warnings"],
    }
