from base64 import b64encode
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict

from fastapi.testclient import TestClient

from fractal_journal.config import Settings
from fractal_journal.main import create_app

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class JsonMap(TypedDict, total=False):
    screenshot_data_url: str
    extracted: "ExtractedJson"
    confirmed: "ConfirmedJson"
    decision: str
    notes: str
    warnings: list[str]


class ExtractedJson(TypedDict):
    source_url: str
    page_title: str
    symbol_candidate: str
    timeframe_candidate: str
    captured_at: str


class ConfirmedJson(TypedDict):
    symbol: str
    provider: str
    provider_symbol: str
    market_div_code: str
    timeframe: str
    trade_date: str
    decision_time_exchange: str
    exchange_tz: str
    price_basis: str
    session_state: str
    provider_status: str
    scenario: str
    confidence: int
    invalidation: NotRequired[str]


def test_create_and_list_capture(tmp_path: Path) -> None:
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
        body = response.json()
        assert body["capture"]["confirmed"]["symbol"] == "005930"
        assert body["capture"]["warnings"] == ["price_basis_unverified"]

        capture_id = body["capture"]["id"]
        score_response = client.post(
            f"/api/captures/{capture_id}/score",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert score_response.status_code == 200
        assert score_response.json()["score_version"] == "score.v0"

        review_response = client.post(
            f"/api/captures/{capture_id}/ai-review",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert review_response.status_code == 200
        assert review_response.json()["ai_review_can_override_score"] is False

        list_response = client.get(
            "/api/captures",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_response.status_code == 200
        assert len(list_response.json()["captures"]) == 1


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
            "captured_at": captured_at,
        },
        "confirmed": {
            "symbol": "005930",
            "provider": "kis",
            "provider_symbol": "005930",
            "market_div_code": "J",
            "timeframe": "1D",
            "trade_date": "2026-07-09",
            "decision_time_exchange": "2026-07-09T10:00:00+09:00",
            "exchange_tz": "Asia/Seoul",
            "price_basis": "unknown_unadjusted_assumed",
            "session_state": "regular",
            "provider_status": "candidate",
            "scenario": "wait",
            "confidence": 3,
            "invalidation": "",
        },
        "decision": "watch",
        "notes": "test capture",
        "warnings": ["price_basis_unverified"],
    }
