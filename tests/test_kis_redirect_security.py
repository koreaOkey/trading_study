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
    KisTokenIssueError,
    TokenCache,
    create_kis_client,
    get_access_token,
)
from fractal_journal.kis_provider import KisOhlcvProvider
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalDataStatus,
    MinuteWindowRequest,
)

DECISION_TIME = datetime.fromisoformat("2026-07-09T15:30:00+09:00")
REDIRECT_CODE = "KIS_REDIRECT_REJECTED"


def test_kis_client_disables_redirect_following() -> None:
    # Given
    client = create_kis_client("https://kis.test")

    # When
    follows_redirects = client.follow_redirects
    client.close()

    # Then
    assert follows_redirects is False


@pytest.mark.parametrize("status_code", [302, 307, 308])
def test_token_redirect_never_reaches_second_origin(
    status_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.host == "redirect.test":
            return httpx2.Response(
                200,
                json={"access_token": "attacker-value", "expires_in": 3600},
            )
        return httpx2.Response(
            status_code,
            headers={"Location": "https://redirect.test/collect"},
        )

    _install_transport(monkeypatch, handle)
    credentials = _credentials()

    # When
    with (
        create_kis_client("https://kis.test") as client,
        pytest.raises(KisTokenIssueError) as error,
    ):
        _ = get_access_token(client, credentials, tmp_path / "token.json")

    # Then
    assert [request.url.host for request in requests] == ["kis.test"]
    assert "redirect.test" not in str(error.value)
    assert str(credentials.app_secret) not in str(error.value)


@pytest.mark.parametrize("status_code", [307, 308])
def test_history_redirect_never_forwards_credential_headers(
    status_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _redirect_or_attacker_response(request, status_code)

    _install_transport(monkeypatch, handle)
    provider = _provider(tmp_path)
    request = HistoricalBarsRequest(
        provider_symbol="214450",
        decision_time_exchange=DECISION_TIME,
        timeframe="1",
        max_pages=1,
    )

    # When
    result = provider.fetch_historical_bars(request)

    # Then
    assert [item.url.host for item in requests] == ["kis.test"]
    assert result.status is HistoricalDataStatus.API_ERROR
    assert result.provenance.api_message_codes == (REDIRECT_CODE,)
    assert "redirect.test" not in result.model_dump_json()
    assert str(provider.credentials.app_secret) not in result.model_dump_json()


def test_minute_redirect_never_forwards_credential_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _redirect_or_attacker_response(request, 302)

    _install_transport(monkeypatch, handle)
    provider = _provider(tmp_path)
    request = MinuteWindowRequest(
        provider_symbol="214450",
        decision_time_exchange=DECISION_TIME.isoformat(),
    )

    # When
    result = provider.fetch_minute_window(request)

    # Then
    assert [item.url.host for item in requests] == ["kis.test"]
    assert result.data_status == "api_error"
    assert "redirect.test" not in result.model_dump_json()
    assert str(provider.credentials.app_secret) not in result.model_dump_json()


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handle: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    transport = httpx2.MockTransport(handle)
    monkeypatch.setattr(
        "fractal_journal.kis_auth.httpx2.HTTPTransport",
        lambda **_kwargs: transport,
    )


def _provider(tmp_path: Path) -> KisOhlcvProvider:
    cache_path = tmp_path / "token.json"
    cache = TokenCache(
        access_token=AccessToken("cached-value"),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    return KisOhlcvProvider(_credentials(), cache_path, base_url="https://kis.test")


def _credentials() -> KisCredentials:
    return KisCredentials(
        app_key=AppKey("sensitive-key"),
        app_secret=AppSecret("sensitive-secret"),
    )


def _redirect_or_attacker_response(
    request: httpx2.Request,
    status_code: int,
) -> httpx2.Response:
    if request.url.host == "redirect.test":
        return httpx2.Response(
            200,
            json={"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok"},
        )
    return httpx2.Response(
        status_code,
        headers={"Location": "https://redirect.test/collect"},
    )
