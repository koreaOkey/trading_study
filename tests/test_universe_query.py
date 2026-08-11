import json
from pathlib import Path

from fastapi.testclient import TestClient

from fractal_journal.chart_query import ChartQueryError
from fractal_journal.config import Settings
from fractal_journal.hermes_query import ChartQueryAnswer
from fractal_journal.hermes_query_worker import (
    CHART_QUERY_SYSTEM_PROMPT,
    UNIVERSE_QUERY_SYSTEM_PROMPT,
    select_system_prompt,
)
from fractal_journal.main import UniverseQueryListResponse, UniverseQueryResponse, create_app
from fractal_journal.provider import FixtureOhlcvProvider
from fractal_journal.universe_query import (
    FileUniverseQueryStore,
    UniverseDataFile,
    UniverseQueryError,
    build_universe_context,
    build_universe_query_prompt,
    collect_universe_files,
    new_universe_query_record,
)


def _write_scan(scan_dir: Path, asset_class: str, *, candidates: int = 1) -> None:
    scan_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "symbol": f"00000{index}",
            "name": f"종목{index}",
            "market": "KOSPI",
            "timeframe": "1d",
            "last_date": "20260804",
            "close": 1000.0 + index,
            "is_candidate": index < candidates,
        }
        for index in range(3)
    ]
    (scan_dir / f"latest_{asset_class}.json").write_text(
        json.dumps(
            {"run_at": "2026-08-04 16:04", "asset_class": asset_class, "rows": rows},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class FakeUniverseService:
    def __init__(self, *, fail_with: str | None = None) -> None:
        self.fail_with = fail_with
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def ask(
        self,
        *,
        scope: str,
        question: str,
        files: tuple[UniverseDataFile, ...],
    ) -> ChartQueryAnswer:
        self.calls.append((scope, question, tuple(f.filename for f in files)))
        if self.fail_with is not None:
            raise ChartQueryError(self.fail_with)
        return ChartQueryAnswer(answer=f"{scope} 유니버스 서술", model="fake-model")


def test_collect_universe_files_scopes_and_missing(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans"
    base_rate = tmp_path / "cross_base_rate.json"
    _write_scan(scan_dir, "kr")
    _write_scan(scan_dir, "crypto")
    base_rate.write_text("{}", encoding="utf-8")

    kr_only = collect_universe_files(scan_dir, base_rate, "kr")
    assert [file.filename for file in kr_only] == [
        "latest_kr.json",
        "cross_base_rate.json",
    ]
    # all은 존재하는 클래스만 모으고, us가 없어도 동작한다.
    everything = collect_universe_files(scan_dir, base_rate, "all")
    assert [file.filename for file in everything] == [
        "latest_kr.json",
        "latest_crypto.json",
        "cross_base_rate.json",
    ]
    try:
        _ = collect_universe_files(scan_dir, base_rate, "us")
    except UniverseQueryError as exc:
        assert exc.reason == "universe_data_unavailable"
    else:
        raise AssertionError("us scope must fail without latest_us.json")


def test_universe_context_and_prompt_manifest(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans"
    _write_scan(scan_dir, "kr", candidates=2)
    files = collect_universe_files(scan_dir, tmp_path / "absent.json", "kr")
    context = build_universe_context(files)
    kr = context["classes"]["kr"]
    assert kr["row_count"] == 3
    assert kr["candidate_count"] == 2
    assert kr["candidates"][0]["name"] == "종목0"

    prompt = build_universe_query_prompt(
        scope="kr",
        question="후보 몇 개?",
        context=context,
        files=files,
        workdir=str(tmp_path),
    )
    payload = json.loads(prompt.stdin.decode().rsplit("\n", 1)[-1])
    assert payload["query_input"]["universe_scope"] == "kr"
    assert payload["query_input"]["data_files"][0]["filename"] == "latest_kr.json"
    assert payload["workdir"] == str(tmp_path)
    # 워커는 data_files 매니페스트를 보고 유니버스 시스템 프롬프트를 고른다.
    assert select_system_prompt(prompt.stdin.decode()) == UNIVERSE_QUERY_SYSTEM_PROMPT


def test_select_system_prompt_keeps_chart_default() -> None:
    chart_stdin = 'INPUT_SHA256=x\nintro\n{"query_input":{"bars_csv":{}}}'
    assert select_system_prompt(chart_stdin) == CHART_QUERY_SYSTEM_PROMPT
    assert select_system_prompt("not json") == CHART_QUERY_SYSTEM_PROMPT


def test_universe_store_round_trip_with_scope_filter(tmp_path: Path) -> None:
    store = FileUniverseQueryStore(tmp_path)
    for scope in ("kr", "crypto"):
        store.append(
            new_universe_query_record(
                scope=scope,
                question=f"{scope} 질문",
                status="answered",
                answer="답변",
            ),
        )
    assert [record.scope for record in store.list_queries()] == ["crypto", "kr"]
    only = store.list_queries(scope="kr")
    assert len(only) == 1
    assert only[0].question == "kr 질문"


def _universe_app(
    tmp_path: Path,
    service: FakeUniverseService,
    *,
    with_scan: bool = True,
) -> tuple[object, str]:
    token = tmp_path.name
    scan_dir = tmp_path / "scans"
    if with_scan:
        _write_scan(scan_dir, "kr")
    settings = Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        api_token=token,
        universe_scan_dir=scan_dir,
        universe_base_rate_path=tmp_path / "cross_base_rate.json",
    )
    app = create_app(
        settings,
        provider=FixtureOhlcvProvider(),
        universe_query_service=service,  # type: ignore[arg-type]
    )
    return app, token


def test_universe_endpoint_answers_and_persists(tmp_path: Path) -> None:
    service = FakeUniverseService()
    app, token = _universe_app(tmp_path, service)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        no_auth = client.post(
            "/api/universe-queries",
            json={"scope": "kr", "question": "후보?"},
        )
        assert no_auth.status_code == 401

        response = client.post(
            "/api/universe-queries",
            json={"scope": "kr", "question": "지금 국장 후보는?"},
            headers=headers,
        )
        assert response.status_code == 201
        body = UniverseQueryResponse.model_validate_json(response.text)
        assert body.query.status == "answered"
        assert body.query.scope == "kr"
        assert body.query.data_files == ("latest_kr.json",)
        assert service.calls[0][0] == "kr"

        listing = client.get(
            "/api/universe-queries",
            params={"scope": "kr"},
            headers=headers,
        )
        assert listing.status_code == 200
        items = UniverseQueryListResponse.model_validate_json(listing.text).items
        assert len(items) == 1
        assert items[0].query_id == body.query.query_id


def test_universe_endpoint_maps_errors(tmp_path: Path) -> None:
    service = FakeUniverseService(fail_with="hermes_timeout")
    app, token = _universe_app(tmp_path, service)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        failed = client.post(
            "/api/universe-queries",
            json={"scope": "kr", "question": "후보?"},
            headers=headers,
        )
        assert failed.status_code == 201
        body = UniverseQueryResponse.model_validate_json(failed.text)
        assert body.query.status == "failed"
        assert body.query.error_code == "hermes_timeout"

        bad_scope = client.post(
            "/api/universe-queries",
            json={"scope": "nasdaq", "question": "후보?"},
            headers=headers,
        )
        assert bad_scope.status_code == 422


def test_universe_endpoint_404_without_scan_data(tmp_path: Path) -> None:
    service = FakeUniverseService()
    app, token = _universe_app(tmp_path, service, with_scan=False)
    with TestClient(app) as client:
        missing = client.post(
            "/api/universe-queries",
            json={"scope": "kr", "question": "후보?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "universe_data_unavailable"
        assert service.calls == []
