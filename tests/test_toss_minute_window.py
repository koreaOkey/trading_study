import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest

from fractal_journal.kis_auth import AccessToken, TokenCache
from fractal_journal.provider import MinuteWindowRequest
from fractal_journal.toss_auth import ClientId, ClientSecret, TossCredentials
from fractal_journal.toss_history import CANDLES_ENDPOINT
from fractal_journal.toss_provider import TossOhlcvProvider

DECISION_TIME = datetime.fromisoformat("2026-07-09T09:09:00+09:00")


def test_minute_window_requests_forward_shifted_before_and_clips_lookback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path, "cached-value")
    captured_params: dict[str, str] = {}
    request_time = DECISION_TIME + timedelta(minutes=30)

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured_params.update(request.url.params)
        return httpx2.Response(
            200,
            json=_envelope_json(request_time, count=200),
        )

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    window = provider.fetch_minute_window(_request())

    # Then
    assert captured_params["before"] == "2026-07-09T09:39:00+09:00"
    assert captured_params["interval"] == "1m"
    assert window.provider == "toss"
    assert window.endpoint == CANDLES_ENDPOINT
    assert window.data_status == "ok"
    # lookback 60 + forward 30 + 1 bars remain after clipping the page
    # to the requested window.
    assert len(window.bars) == 91
    window_start = DECISION_TIME - timedelta(minutes=60)
    assert window.bars[0].time_utc == window_start
    assert window.bars[-1].time_utc == request_time
    assert list(window.bars) == sorted(window.bars, key=lambda bar: bar.time_utc)


def test_minute_window_refreshes_token_once_after_invalid_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path, "stale-value")
    paths: list[str] = []
    authorizations: list[str] = []
    request_time = DECISION_TIME + timedelta(minutes=30)

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if request.url.path == "/oauth2/token":
            return httpx2.Response(
                200,
                json={"access_token": "fresh-value", "expires_in": 86399},
            )
        authorization = request.headers["authorization"]
        authorizations.append(authorization)
        if authorization == "Bearer stale-value":
            return httpx2.Response(
                401,
                json={"error": {"code": "expired-token", "message": "expired"}},
            )
        return httpx2.Response(200, json=_envelope_json(request_time, count=120))

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    window = provider.fetch_minute_window(_request())

    # Then
    assert paths == [CANDLES_ENDPOINT, "/oauth2/token", CANDLES_ENDPOINT]
    assert authorizations == ["Bearer stale-value", "Bearer fresh-value"]
    assert window.data_status == "ok"


def test_minute_window_reports_empty_data_without_bars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    cache_path = _cached_token(tmp_path, "cached-value")

    def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={"result": {"candles": [], "nextBefore": None}},
        )

    provider = _provider(monkeypatch, cache_path, handle)

    # When
    window = provider.fetch_minute_window(_request())

    # Then
    assert window.data_status == "empty_data"
    assert window.bars == ()


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    cache_path: Path,
    handle: Callable[[httpx2.Request], httpx2.Response],
) -> TossOhlcvProvider:
    transport = httpx2.MockTransport(handle)

    def create_client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=transport)

    monkeypatch.setattr(
        "fractal_journal.toss_provider.create_toss_client",
        create_client,
    )
    credentials = TossCredentials(
        client_id=ClientId("id"),
        client_secret=ClientSecret("secret"),
    )
    return TossOhlcvProvider(credentials, cache_path, history_throttle=lambda: None)


def _cached_token(tmp_path: Path, value: str) -> Path:
    cache_path = tmp_path / "toss-token.json"
    cache = TokenCache(
        access_token=AccessToken(value),
        expires_at_epoch=time.time() + 3600,
    )
    _ = cache_path.write_text(cache.model_dump_json(), encoding="utf-8")
    return cache_path


def _request() -> MinuteWindowRequest:
    return MinuteWindowRequest(
        provider_symbol="005930",
        decision_time_exchange=DECISION_TIME.isoformat(),
        lookback_minutes=60,
        forward_minutes=30,
    )


def _envelope_json(end: datetime, *, count: int) -> dict[str, Any]:
    return {
        "result": {
            "candles": [
                _candle_json(end - timedelta(minutes=offset), 100.0 + count - offset)
                for offset in range(count)
            ],
            "nextBefore": (end - timedelta(minutes=count)).isoformat(),
        },
    }


def _candle_json(exchange_time: datetime, close: float) -> dict[str, Any]:
    return {
        "timestamp": exchange_time.isoformat(timespec="milliseconds"),
        "openPrice": close - 1,
        "highPrice": close + 1,
        "lowPrice": close - 2,
        "closePrice": close,
        "volume": 102.0,
        "currency": "KRW",
    }
