from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fractal_journal.bar_series import FileBarSeriesStore
from fractal_journal.chart_query import (
    ChartQueryError,
    FileChartQueryStore,
    answer_contains_blocked_action,
    build_query_context,
    new_query_record,
)
from fractal_journal.config import Settings
from fractal_journal.hermes_query import ChartQueryAnswer
from fractal_journal.main import ChartQueryListResponse, ChartQueryResponse, create_app
from fractal_journal.provider import FixtureOhlcvProvider, OhlcvBar


def _bars(closes: list[float]) -> tuple[OhlcvBar, ...]:
    start = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    for index, close in enumerate(closes):
        time_utc = start + timedelta(hours=4 * index)
        value = Decimal(str(round(close, 2)))
        bars.append(
            OhlcvBar(
                time_utc=time_utc,
                time_exchange=time_utc.isoformat(),
                open=value,
                high=value + 1,
                low=value - 1,
                close=value,
                volume=1_000,
            ),
        )
    return tuple(bars)


def _crossing_closes() -> list[float]:
    # Flat long history keeps SMA200 anchored, then a sustained ramp lifts
    # SMA50 through it — one unambiguous golden cross with a forward window.
    return [100.0] * 260 + [100.0 + 2.0 * step for step in range(1, 121)]


class FakeQueryService:
    def __init__(self, *, fail_with: str | None = None) -> None:
        self.fail_with = fail_with
        self.questions: list[str] = []

    def ask(
        self,
        *,
        symbol: str,
        timeframe: str,
        question: str,
        bars: tuple[OhlcvBar, ...],
    ) -> ChartQueryAnswer:
        self.questions.append(question)
        if self.fail_with is not None:
            raise ChartQueryError(self.fail_with)
        return ChartQueryAnswer(
            answer=f"{symbol} {timeframe} {len(bars)}봉 기준 분석 서술",
            model="fake-model",
        )


def test_context_pack_finds_golden_cross_with_forward_returns() -> None:
    context = build_query_context(_bars(_crossing_closes()))
    pair = context["ma_cross_history"]["sma50_x_sma200"]
    golden = [event for event in pair["events"] if event["kind"] == "golden"]
    assert len(golden) == 1
    assert golden[0]["forward_returns_pct"]["+40"] is not None
    assert golden[0]["forward_returns_pct"]["+40"] > 0
    aggregates = pair["aggregates"]["golden"]
    assert aggregates["count"] == 1
    assert aggregates["positive_after_40_bars"] == 1
    assert context["series"]["bar_count"] == 380
    assert len(context["recent_bars"]) == 30


def test_context_pack_flat_series_has_no_events() -> None:
    context = build_query_context(_bars([100.0] * 260))
    pair = context["ma_cross_history"]["sma50_x_sma200"]
    assert pair["events"] == []
    assert pair["aggregates"]["golden"]["count"] == 0


def test_query_store_round_trip_with_filters(tmp_path: Path) -> None:
    store = FileChartQueryStore(tmp_path)
    for symbol in ("214450", "005930"):
        store.append(
            new_query_record(
                symbol=symbol,
                timeframe="240",
                question=f"{symbol} 질문",
                status="answered",
                answer="답변",
            ),
        )
    everything = store.list_queries()
    assert [record.symbol for record in everything] == ["005930", "214450"]
    only = store.list_queries(symbol="214450", timeframe="240")
    assert len(only) == 1
    assert only[0].question == "214450 질문"


def test_blocked_action_scan_catches_instructions() -> None:
    assert answer_contains_blocked_action("이 자리는 지금 사세요")
    factual = "골든크로스 이후 +40봉 중앙값은 +3.2%였다"
    assert not answer_contains_blocked_action(factual)


def _app_with_series(tmp_path: Path, service: FakeQueryService) -> tuple[FastAPI, str]:
    token = tmp_path.name
    settings = Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        api_token=token,
    )
    FileBarSeriesStore(tmp_path).register("214450", "240", _bars([100.0] * 300))
    app = create_app(
        settings,
        provider=FixtureOhlcvProvider(),
        query_service=service,  # type: ignore[arg-type]
    )
    return app, token


def test_query_endpoint_answers_and_persists(tmp_path: Path) -> None:
    service = FakeQueryService()
    app, token = _app_with_series(tmp_path, service)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/api/queries",
            json={
                "symbol": "214450",
                "timeframe": "240",
                "question": "전체 이력에서 골든크로스 이후 성적은?",
            },
            headers=headers,
        )
        assert response.status_code == 201
        body = ChartQueryResponse.model_validate_json(response.text)
        assert body.query.status == "answered"
        assert body.query.bar_count == 300
        assert body.query.model == "fake-model"

        listing = client.get(
            "/api/queries",
            params={"symbol": "214450", "timeframe": "240"},
            headers=headers,
        )
        assert listing.status_code == 200
        items = ChartQueryListResponse.model_validate_json(listing.text).items
        assert len(items) == 1
        assert items[0].query_id == body.query.query_id


def test_query_endpoint_blocks_replay_and_unregistered(tmp_path: Path) -> None:
    service = FakeQueryService()
    app, token = _app_with_series(tmp_path, service)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        replay = client.post(
            "/api/queries",
            json={
                "symbol": "214450",
                "timeframe": "240",
                "question": "질문",
                "replay_active": True,
            },
            headers=headers,
        )
        assert replay.status_code == 409
        assert replay.json()["detail"] == "replay_active"

        missing = client.post(
            "/api/queries",
            json={"symbol": "005930", "timeframe": "240", "question": "질문"},
            headers=headers,
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "series_unregistered"
        assert service.questions == []


def test_query_endpoint_persists_failures(tmp_path: Path) -> None:
    service = FakeQueryService(fail_with="hermes_timeout")
    app, token = _app_with_series(tmp_path, service)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/api/queries",
            json={"symbol": "214450", "timeframe": "240", "question": "질문"},
            headers=headers,
        )
        assert response.status_code == 201
        body = ChartQueryResponse.model_validate_json(response.text)
        assert body.query.status == "failed"
        assert body.query.error_code == "hermes_timeout"
