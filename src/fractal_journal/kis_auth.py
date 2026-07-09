import json
import socket
import time
from pathlib import Path
from typing import ClassVar, NewType

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

AppKey = NewType("AppKey", str)
AppSecret = NewType("AppSecret", str)
AccessToken = NewType("AccessToken", str)
TOKEN_SAFETY_SECONDS = 300


class KisCredentials(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    app_key: AppKey
    app_secret: AppSecret


class TokenCache(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: AccessToken
    expires_at_epoch: float


class KisTokenIssueResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: AccessToken | None = None
    expires_in: int | None = None
    error_code: str | None = None
    error_description: str | None = None


class KisTokenIssueError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("kis_token_issue_failed")


def load_credentials(
    env_path: Path,
    app_key: str,
    app_secret: str,
) -> KisCredentials | None:
    if app_key and app_secret:
        return KisCredentials(app_key=AppKey(app_key), app_secret=AppSecret(app_secret))
    try:
        values = _read_env(env_path)
    except FileNotFoundError:
        return None
    loaded_key = values.get("KIS_APP_KEY") or values.get("appkey")
    loaded_secret = values.get("KIS_APP_SECRET") or values.get("appsecret")
    if loaded_key is None or loaded_secret is None:
        return None
    return KisCredentials(
        app_key=AppKey(loaded_key),
        app_secret=AppSecret(loaded_secret),
    )


def create_kis_client(base_url: str) -> httpx2.Client:
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
        follow_redirects=True,
    )


def get_access_token(
    client: httpx2.Client,
    credentials: KisCredentials,
    cache_path: Path,
) -> AccessToken:
    cache = _load_token_cache(cache_path)
    if cache is not None:
        cache_is_fresh = cache.expires_at_epoch - time.time() > TOKEN_SAFETY_SECONDS
        if cache_is_fresh:
            return cache.access_token
    response = client.post(
        "/oauth2/tokenP",
        json={
            "grant_type": "client_credentials",
            "appkey": credentials.app_key,
            "appsecret": credentials.app_secret,
        },
    )
    parsed = KisTokenIssueResponse.model_validate(response.json())
    if parsed.access_token is None or parsed.expires_in is None:
        raise KisTokenIssueError
    cache = TokenCache(
        access_token=parsed.access_token,
        expires_at_epoch=time.time() + parsed.expires_in,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    cache_path.chmod(0o600)
    return cache.access_token


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
