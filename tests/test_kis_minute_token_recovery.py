import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx2
import pytest

from fractal_journal.kis_auth import (
    AccessToken,
    AppKey,
    AppSecret,
    KisCredentials,
    TokenCache,
)
from fractal_journal.kis_models import KisBar, KisQuoteResponse
from fractal_journal.kis_provider import KisOhlcvProvider
from fractal_journal.provider import MinuteWindowRequest

DECISION_TIME = datetime.fromisoformat("2026-07-09T09:09:00+09:00")
AUTH_REJECTION_CODE = "EGW00123"
HISTORY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"


def test_minute_window_refreshes_cached_token_once_after_kis_rejects_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path)
    authorizations: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/oauth2/tokenP":
            return _issued_token_response()
        authorization = request.headers["authorization"]
        authorizations.append(authorization)
        response = (
            _response(rt_cd="1", msg_cd=AUTH_REJECTION_CODE)
            if authorization == "Bearer stale-value"
            else _response(_bar())
        )
        return httpx2.Response(200, json=response.model_dump(mode="json"))

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_minute_window(_request())

    # Then
    assert authorizations == ["Bearer stale-value", "Bearer fresh-value"]
    assert result.data_status == "partial_data"


def test_minute_window_does_not_retry_invalid_token_more_than_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path)
    paths: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return (
            _issued_token_response()
            if request.url.path == "/oauth2/tokenP"
            else httpx2.Response(
                200,
                json=_response(
                    rt_cd="1",
                    msg_cd=AUTH_REJECTION_CODE,
                ).model_dump(mode="json"),
            )
        )

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_minute_window(_request())

    # Then
    assert paths == [HISTORY_PATH, "/oauth2/tokenP", HISTORY_PATH]
    assert result.data_status == "api_error"


def test_minute_window_does_not_refresh_token_for_non_auth_api_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path)
    paths: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return httpx2.Response(
            200,
            json=_response(rt_cd="1", msg_cd="API001").model_dump(mode="json"),
        )

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    result = provider.fetch_minute_window(_request())

    # Then
    assert paths == [HISTORY_PATH]
    assert result.data_status == "api_error"


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    cache_path: Path,
    handle: Callable[[httpx2.Request], httpx2.Response],
) -> KisOhlcvProvider:
    transport = httpx2.MockTransport(handle)

    def create_client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=transport)

    monkeypatch.setattr("fractal_journal.kis_provider.create_kis_client", create_client)
    credentials = KisCredentials(app_key=AppKey("key"), app_secret=AppSecret("secret"))
    return KisOhlcvProvider(credentials, cache_path)


def _cached_token(tmp_path: Path) -> Path:
    cache_path = tmp_path / "token.json"
    cache = TokenCache(
        access_token=AccessToken("stale-value"),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    return cache_path


def _request() -> MinuteWindowRequest:
    return MinuteWindowRequest(
        provider_symbol="214450",
        decision_time_exchange=DECISION_TIME.isoformat(),
    )


def _issued_token_response() -> httpx2.Response:
    return httpx2.Response(
        200,
        json={"access_token": "fresh-value", "expires_in": 3600},
    )


def _response(
    *bars: KisBar,
    rt_cd: str = "0",
    msg_cd: str = "MCA00000",
) -> KisQuoteResponse:
    return KisQuoteResponse(
        rt_cd=rt_cd,
        msg_cd=msg_cd,
        msg1="ok" if rt_cd == "0" else "error",
        output2=bars,
    )


def _bar() -> KisBar:
    return KisBar(
        stck_bsop_date=DECISION_TIME.strftime("%Y%m%d"),
        stck_cntg_hour=DECISION_TIME.strftime("%H%M%S"),
        stck_prpr="100",
        cntg_vol="102",
    )
