"""Toss Securities open API token issue/cache, mirroring kis_auth.

The token cache reuses kis_auth's TokenCache model (same JSON format and
0600 permissions) but lives in a separate file so the two providers never
clobber each other's tokens.
"""

import json
import socket
import time
from pathlib import Path
from typing import ClassVar, NewType

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from fractal_journal.kis_auth import AccessToken, TokenCache

ClientId = NewType("ClientId", str)
ClientSecret = NewType("ClientSecret", str)
TOKEN_SAFETY_SECONDS = 300
HTTP_REDIRECT_MIN = 300
HTTP_REDIRECT_MAX = 400


class TossCredentials(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    client_id: ClientId
    client_secret: ClientSecret


class TossTokenIssueResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: AccessToken | None = None
    expires_in: int | None = None


class TossTokenIssueError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("toss_token_issue_failed")


def load_credentials(
    env_path: Path,
    client_id: str,
    client_secret: str,
) -> TossCredentials | None:
    if client_id and client_secret:
        return TossCredentials(
            client_id=ClientId(client_id),
            client_secret=ClientSecret(client_secret),
        )
    try:
        values = _read_env(env_path)
    except FileNotFoundError:
        return None
    loaded_id = values.get("TOSS_CLIENT_ID") or values.get("toss_client_id")
    loaded_secret = values.get("TOSS_CLIENT_SECRET") or values.get("toss_client_secret")
    if loaded_id is None or loaded_secret is None:
        return None
    return TossCredentials(
        client_id=ClientId(loaded_id),
        client_secret=ClientSecret(loaded_secret),
    )


def create_toss_client(base_url: str) -> httpx2.Client:
    limits = httpx2.Limits(
        max_connections=50,
        max_keepalive_connections=20,
        keepalive_expiry=30.0,
    )
    timeout = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=limits,
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    return httpx2.Client(
        base_url=base_url,
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
    )


def get_access_token(
    client: httpx2.Client,
    credentials: TossCredentials,
    cache_path: Path,
    *,
    force_refresh: bool = False,
) -> AccessToken:
    if not force_refresh:
        cache = _load_token_cache(cache_path)
        if cache is not None:
            cache_is_fresh = cache.expires_at_epoch - time.time() > TOKEN_SAFETY_SECONDS
            if cache_is_fresh:
                return cache.access_token
    response = client.post(
        "/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        },
    )
    if HTTP_REDIRECT_MIN <= response.status_code < HTTP_REDIRECT_MAX:
        raise TossTokenIssueError
    parsed = TossTokenIssueResponse.model_validate(response.json())
    if parsed.access_token is None or parsed.expires_in is None:
        raise TossTokenIssueError
    cache = TokenCache(
        access_token=parsed.access_token,
        expires_at_epoch=time.time() + parsed.expires_in,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    cache_path.chmod(0o600)
    return cache.access_token


def invalidate_token_cache(cache_path: Path) -> None:
    cache_path.unlink(missing_ok=True)


def _read_env(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _load_token_cache(cache_path: Path) -> TokenCache | None:
    try:
        return TokenCache.model_validate_json(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, ValidationError):
        return None
