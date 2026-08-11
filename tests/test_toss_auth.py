import time
from pathlib import Path

import httpx2
import pytest

from fractal_journal.kis_auth import AccessToken, TokenCache
from fractal_journal.toss_auth import (
    ClientId,
    ClientSecret,
    TossCredentials,
    TossTokenIssueError,
    get_access_token,
    load_credentials,
)

CREDENTIALS = TossCredentials(
    client_id=ClientId("test-id"),
    client_secret=ClientSecret("test-secret"),
)


def test_token_issue_posts_form_encoded_credentials_and_caches(
    tmp_path: Path,
) -> None:
    # Given
    cache_path = tmp_path / "toss-token.json"
    captured: dict[str, str] = {}

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured["path"] = request.url.path
        captured["content_type"] = request.headers["content-type"]
        captured["body"] = request.content.decode()
        return httpx2.Response(
            200,
            json={
                "access_token": "issued-value",
                "token_type": "Bearer",
                "expires_in": 86399,
            },
        )

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        # When
        result = get_access_token(client, CREDENTIALS, cache_path)

    # Then
    assert result == "issued-value"
    assert captured["path"] == "/oauth2/token"
    assert captured["content_type"].startswith("application/x-www-form-urlencoded")
    assert "grant_type=client_credentials" in captured["body"]
    assert "client_id=test-id" in captured["body"]
    assert "client_secret=test-secret" in captured["body"]
    persisted = TokenCache.model_validate_json(cache_path.read_text(encoding="utf-8"))
    assert persisted.access_token == result
    assert cache_path.stat().st_mode & 0o777 == 0o600


def test_fresh_cached_token_is_reused_without_network_call(tmp_path: Path) -> None:
    # Given
    cache_path = tmp_path / "toss-token.json"
    cache = TokenCache(
        access_token=AccessToken("cached-value"),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    issue_calls = 0

    def handle(_request: httpx2.Request) -> httpx2.Response:
        nonlocal issue_calls
        issue_calls += 1
        return httpx2.Response(
            200,
            json={"access_token": "fresh-value", "expires_in": 86399},
        )

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        # When
        result = get_access_token(client, CREDENTIALS, cache_path)

    # Then
    assert result == "cached-value"
    assert issue_calls == 0


def test_force_refresh_bypasses_valid_cached_token(tmp_path: Path) -> None:
    # Given
    cache_path = tmp_path / "toss-token.json"
    cache = TokenCache(
        access_token=AccessToken("cached-value"),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")

    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"access_token": "fresh-value", "expires_in": 86399},
        )

    with httpx2.Client(
        base_url="https://toss.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        # When
        result = get_access_token(client, CREDENTIALS, cache_path, force_refresh=True)

    # Then
    persisted = TokenCache.model_validate_json(cache_path.read_text(encoding="utf-8"))
    assert result == "fresh-value"
    assert persisted.access_token == result


def test_error_envelope_raises_token_issue_error(tmp_path: Path) -> None:
    # Given
    cache_path = tmp_path / "toss-token.json"

    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"error": {"code": "invalid-client", "message": "bad credentials"}},
        )

    # When / Then
    with (
        httpx2.Client(
            base_url="https://toss.test",
            transport=httpx2.MockTransport(handle),
        ) as client,
        pytest.raises(TossTokenIssueError),
    ):
        _ = get_access_token(client, CREDENTIALS, cache_path)
    assert not cache_path.exists()


def test_load_credentials_reads_lowercase_env_file_keys(tmp_path: Path) -> None:
    # Given
    env_path = tmp_path / ".env"
    _ = env_path.write_text(
        "KIS_APP_KEY=other\ntoss_client_id=file-id\ntoss_client_secret='file-secret'\n",
        encoding="utf-8",
    )

    # When
    credentials = load_credentials(env_path, "", "")

    # Then
    assert credentials is not None
    assert (credentials.client_id, credentials.client_secret) == (
        "file-id",
        "file-secret",
    )


def test_load_credentials_returns_none_without_toss_keys(tmp_path: Path) -> None:
    # Given
    env_path = tmp_path / ".env"
    _ = env_path.write_text("KIS_APP_KEY=other\n", encoding="utf-8")

    # When / Then
    assert load_credentials(env_path, "", "") is None
    assert load_credentials(tmp_path / "missing.env", "", "") is None


def test_load_credentials_prefers_explicit_values(tmp_path: Path) -> None:
    # Given
    env_path = tmp_path / ".env"
    _ = env_path.write_text(
        "toss_client_id=a\ntoss_client_secret=b\n",
        encoding="utf-8",
    )

    # When
    credentials = load_credentials(env_path, "explicit-id", "explicit-secret")

    # Then
    assert credentials is not None
    assert (credentials.client_id, credentials.client_secret) == (
        "explicit-id",
        "explicit-secret",
    )
