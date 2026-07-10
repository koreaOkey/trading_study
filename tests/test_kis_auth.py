import logging
import time
from pathlib import Path

import httpx2
import pytest

from fractal_journal.kis_auth import (
    AccessToken,
    AppKey,
    AppSecret,
    KisCredentials,
    TokenCache,
    get_access_token,
    invalidate_token_cache,
)


def test_force_refresh_bypasses_valid_cached_token(tmp_path: Path) -> None:
    # Given
    cache_path = tmp_path / "token.json"
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
            json={"access_token": "fresh-value", "expires_in": 3600},
        )

    credentials = KisCredentials(app_key=AppKey("key"), app_secret=AppSecret("secret"))
    with httpx2.Client(
        base_url="https://kis.test",
        transport=httpx2.MockTransport(handle),
    ) as client:
        # When
        result = get_access_token(
            client,
            credentials,
            cache_path,
            force_refresh=True,
        )

    # Then
    persisted = TokenCache.model_validate_json(cache_path.read_text(encoding="utf-8"))
    assert result == "fresh-value"
    assert persisted.access_token == result
    assert issue_calls == 1


def test_invalidating_token_cache_does_not_log_cached_token(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given
    cache_path = tmp_path / "token.json"
    opaque_value = "sensitive-cached-value"
    cache = TokenCache(
        access_token=AccessToken(opaque_value),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")

    # When
    with caplog.at_level(logging.DEBUG):
        invalidate_token_cache(cache_path)

    # Then
    assert opaque_value not in caplog.text
