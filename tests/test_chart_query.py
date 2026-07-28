import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fractal_journal.bar_series import FileBarSeriesStore
from fractal_journal.chart_query import (
    ChartQueryError,
    ChartQueryRecord,
    FileChartQueryStore,
    QueryComputation,
    answer_contains_blocked_action,
    build_query_context,
    build_query_prompt,
    new_query_record,
)
from fractal_journal.config import Settings
from fractal_journal.hermes_query import ChartQueryAnswer, HermesChartQueryService
from fractal_journal.hermes_review import HermesProcessRequest, HermesProcessResult
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


class FakeHermesRunner:
    """Plays the worker: validates the workdir bars.csv and answers in v2."""

    def __init__(self, *, schema_version: str = "hermes_query_envelope.v2") -> None:
        self.schema_version = schema_version
        self.saw_bars_csv = False
        self.workdir_payload: dict[str, object] = {}

    def run(self, request: HermesProcessRequest) -> HermesProcessResult:
        prompt = request.stdin.decode("utf-8")
        input_hash = prompt.partition("\n")[0].removeprefix("INPUT_SHA256=")
        payload = json.loads(prompt.rsplit("\n", 1)[-1])
        workdir = payload["workdir"]
        self.saw_bars_csv = (Path(workdir) / "bars.csv").is_file()
        self.workdir_payload = payload
        envelope = {
            "schema_version": self.schema_version,
            "answered_at_utc": "2026-07-28T00:00:00Z",
            "model": "fake-model",
            "input_sha256": input_hash,
            "answer": "골든크로스 이후 200SMA 이탈까지 중앙값 12봉이었다",
            "computations": [
                {
                    "code": "print(12)",
                    "stdout": "12\n",
                    "stderr": "",
                    "exit_code": 0,
                    "timed_out": False,
                },
            ],
        }
        return HermesProcessResult(
            exit_code=0,
            stdout=json.dumps(envelope, ensure_ascii=False).encode(),
        )


def _service(runner: FakeHermesRunner, tmp_path: Path) -> HermesChartQueryService:
    settings = Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        api_token=tmp_path.name,
    )
    return HermesChartQueryService(settings=settings, runner=runner)


def test_service_ships_bars_csv_and_returns_computations(tmp_path: Path) -> None:
    runner = FakeHermesRunner()
    service = _service(runner, tmp_path)
    answered = service.ask(
        symbol="214450",
        timeframe="240",
        question="골크 후 200SMA 이탈까지 며칠?",
        bars=_bars([100.0] * 300),
    )
    assert runner.saw_bars_csv
    bars_csv = runner.workdir_payload["query_input"]["bars_csv"]
    assert bars_csv["row_count"] == 300
    assert bars_csv["columns"][0] == "date"
    assert answered.model == "fake-model"
    assert len(answered.computations) == 1
    assert answered.computations[0].stdout == "12\n"


def test_service_rejects_v1_envelope(tmp_path: Path) -> None:
    runner = FakeHermesRunner(schema_version="hermes_query_envelope.v1")
    service = _service(runner, tmp_path)
    with pytest.raises(ChartQueryError) as excinfo:
        _ = service.ask(
            symbol="214450",
            timeframe="240",
            question="질문",
            bars=_bars([100.0] * 300),
        )
    assert excinfo.value.reason == "invalid_response"


def test_query_prompt_omits_bars_csv_without_workdir() -> None:
    context = build_query_context(_bars([100.0] * 260))
    prompt = build_query_prompt(
        symbol="214450",
        timeframe="240",
        question="질문",
        context=context,
    )
    payload = json.loads(prompt.stdin.decode("utf-8").rsplit("\n", 1)[-1])
    assert "workdir" not in payload
    assert "bars_csv" not in payload["query_input"]


def test_record_persists_computations_and_reads_legacy_lines(
    tmp_path: Path,
) -> None:
    store = FileChartQueryStore(tmp_path)
    store.append(
        new_query_record(
            symbol="214450",
            timeframe="240",
            question="질문",
            status="answered",
            answer="답변",
            computations=(
                QueryComputation(code="print(1)", stdout="1\n", exit_code=0),
            ),
        ),
    )
    legacy = new_query_record(
        symbol="214450",
        timeframe="240",
        question="구버전",
        status="answered",
        answer="답변",
    )
    legacy_line = legacy.model_dump_json(exclude={"computations"})
    assert "computations" not in legacy_line
    with (tmp_path / "queries.jsonl").open("a", encoding="utf-8") as handle:
        _ = handle.write(legacy_line + "\n")

    records = store.list_queries()
    assert len(records) == 2
    assert records[0].computations == ()
    assert records[1].computations[0].code == "print(1)"
    assert isinstance(records[1], ChartQueryRecord)


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
