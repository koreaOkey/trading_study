from base64 import b64encode
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from fractal_journal.bar_series import (
    BarSeriesError,
    FileBarSeriesStore,
    RegisteredBarsProvider,
    parse_tradingview_csv,
)
from fractal_journal.config import Settings
from fractal_journal.main import create_app
from fractal_journal.provider import (
    FixtureOhlcvProvider,
    HistoricalBarsRequest,
    HistoricalDataStatus,
)
from test_review_service import PNG_1X1, RecordingReviewer

SEOUL = ZoneInfo("Asia/Seoul")
DECISION_TIME = "2026-07-09T10:00:00+09:00"


def _csv(rows: list[str], header: str = "time,open,high,low,close,Volume") -> str:
    return "\n".join([header, *rows]) + "\n"


def _session_rows(count: int) -> list[str]:
    # Two 240m bars per trading day (09:00 and 13:00 KST), ending 2026-06-02.
    rows: list[str] = []
    days_needed = (count + 1) // 2
    start = datetime(2026, 6, 2, tzinfo=SEOUL) - timedelta(days=days_needed - 1)
    price = 1000
    while len(rows) < count:
        day = start + timedelta(days=len(rows) // 2)
        hour = 9 if len(rows) % 2 == 0 else 13
        stamp = day.replace(hour=hour).isoformat()
        rows.append(f"{stamp},{price},{price + 10},{price - 10},{price + 5},1500")
        price += 1
    return rows


class TestParseTradingViewCsv:
    def test_parses_iso_times_ascending_and_deduplicated(self) -> None:
        text = _csv(
            [
                "2026-06-02T13:00:00+09:00,110,111,109,110.5,200",
                "2026-06-02T09:00:00+09:00,100,101,99,100.5,100",
                "2026-06-02T09:00:00+09:00,100,101,99,100.7,120",
            ]
        )

        bars = parse_tradingview_csv(text)

        assert [bar.time_exchange for bar in bars] == [
            "2026-06-02T09:00:00+09:00",
            "2026-06-02T13:00:00+09:00",
        ]
        assert bars[0].close == Decimal("100.7")  # later duplicate wins
        assert bars[0].volume == 120

    def test_parses_unix_seconds_and_naive_times_as_kst(self) -> None:
        unix = int(datetime(2026, 6, 2, 9, 0, tzinfo=SEOUL).timestamp())
        text = _csv(
            [
                f"{unix},100,101,99,100.5,100",
                "2026-06-02T13:00:00,110,111,109,110.5,200",
            ]
        )

        bars = parse_tradingview_csv(text)

        assert [bar.time_exchange for bar in bars] == [
            "2026-06-02T09:00:00+09:00",
            "2026-06-02T13:00:00+09:00",
        ]

    def test_skips_incomplete_ohlc_and_ignores_indicator_columns(self) -> None:
        text = _csv(
            [
                "2026-06-02T09:00:00+09:00,100,101,99,100.5,100,",
                "2026-06-02T13:00:00+09:00,,,,,200,99.1",
            ],
            header="time,open,high,low,close,Volume,SMA #1",
        )

        bars = parse_tradingview_csv(text)

        assert len(bars) == 1

    def test_missing_volume_defaults_to_zero(self) -> None:
        text = _csv(
            ["2026-06-02T09:00:00+09:00,100,101,99,100.5"],
            header="time,open,high,low,close",
        )

        assert parse_tradingview_csv(text)[0].volume == 0

    def test_missing_required_columns_raises(self) -> None:
        with pytest.raises(BarSeriesError) as excinfo:
            _ = parse_tradingview_csv(_csv(["1,2"], header="time,open"))
        assert excinfo.value.reason == "missing_required_columns"

    def test_no_bars_raises(self) -> None:
        with pytest.raises(BarSeriesError) as excinfo:
            _ = parse_tradingview_csv(_csv([]))
        assert excinfo.value.reason == "no_bars_parsed"


class TestFileBarSeriesStore:
    def test_register_merges_and_reports_coverage(self, tmp_path: Path) -> None:
        store = FileBarSeriesStore(tmp_path)
        first = parse_tradingview_csv(_csv(_session_rows(2)))
        second = parse_tradingview_csv(_csv(_session_rows(4)))

        _ = store.register("214450", "240", first)
        coverage = store.register("214450", "240", second)

        assert coverage.bar_count == 4
        assert coverage.first_time_exchange == "2026-06-01T09:00:00+09:00"
        assert coverage.last_time_exchange == "2026-06-02T13:00:00+09:00"

    def test_series_file_is_scoring_compatible_csv(self, tmp_path: Path) -> None:
        store = FileBarSeriesStore(tmp_path)
        bars = parse_tradingview_csv(_csv(_session_rows(2)))
        _ = store.register("214450", "240", bars)

        path = store.series_path("214450", "240")
        lines = path.read_text(encoding="utf-8").splitlines()

        assert lines[0] == "date,open,high,low,close,volume"
        assert lines[1].startswith("2026-06-02T09:00:00,")  # KST wall time, sortable

    def test_invalid_symbol_is_rejected(self, tmp_path: Path) -> None:
        store = FileBarSeriesStore(tmp_path)
        with pytest.raises(BarSeriesError):
            _ = store.series_path("../evil", "240")


class TestRegisteredBarsProvider:
    def _request(self, target_bars: int = 201) -> HistoricalBarsRequest:
        return HistoricalBarsRequest(
            provider_symbol="214450",
            decision_time_exchange=datetime.fromisoformat(DECISION_TIME),
            timeframe="240",
            target_bars=target_bars,
        )

    def test_serves_only_bars_at_or_before_decision_time(self, tmp_path: Path) -> None:
        store = FileBarSeriesStore(tmp_path)
        rows = [
            *_session_rows(10),
            "2026-07-09T09:00:00+09:00,2000,2010,1990,2005,1500",
            "2026-07-09T13:00:00+09:00,2100,2110,2090,2105,1500",  # after decision
        ]
        _ = store.register("214450", "240", parse_tradingview_csv(_csv(rows)))
        provider = RegisteredBarsProvider(store, FixtureOhlcvProvider())

        result = provider.fetch_historical_bars(self._request(target_bars=201))

        assert result.provider == "tradingview_csv"
        assert result.status is HistoricalDataStatus.PARTIAL_DATA
        assert result.bars[-1].time_exchange == "2026-07-09T09:00:00+09:00"
        assert all(
            bar.time_utc <= datetime.fromisoformat(DECISION_TIME)
            for bar in result.bars
        )
        assert result.provenance.future_bars_filtered == 1

    def test_full_lookback_reports_ok_status(self, tmp_path: Path) -> None:
        store = FileBarSeriesStore(tmp_path)
        bars = parse_tradingview_csv(_csv(_session_rows(210)))
        _ = store.register("214450", "240", bars)
        provider = RegisteredBarsProvider(store, FixtureOhlcvProvider())

        result = provider.fetch_historical_bars(self._request(target_bars=201))

        assert result.status is HistoricalDataStatus.OK
        assert len(result.bars) == 201

    def test_falls_back_when_series_missing(self, tmp_path: Path) -> None:
        store = FileBarSeriesStore(tmp_path)
        provider = RegisteredBarsProvider(store, FixtureOhlcvProvider())

        result = provider.fetch_historical_bars(self._request())

        assert result.provider == "fixture"


def _settings(tmp_path: Path, token: str) -> Settings:
    return Settings(
        data_dir=tmp_path,
        screenshot_dir=tmp_path / "screenshots",
        api_token=token,
        kis_env_path=tmp_path / "missing.env",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _capture_payload() -> dict[str, object]:
    screenshot = b64encode(PNG_1X1).decode("ascii")
    return {
        "screenshot_data_url": f"data:image/png;base64,{screenshot}",
        "extracted": {
            "source_url": "https://www.tradingview.com/chart/example/",
            "page_title": "Example 214450 240",
            "symbol_candidate": "214450",
            "timeframe_candidate": "240",
            "decision_time_candidate": DECISION_TIME,
            "replay_active": True,
            "captured_at": "2026-07-09T01:00:00Z",
        },
        "confirmed": {
            "symbol": "214450",
            "provider": "kis",
            "provider_symbol": "214450",
            "market_div_code": "J",
            "timeframe": "240",
            "decision_time_exchange": DECISION_TIME,
            "exchange_tz": "Asia/Seoul",
            "provider_status": "candidate",
        },
        "setup": "ma_crossover",
        "hypothesis": "golden_cross_expected",
        "decision_note": "골든크로스 수렴 관찰",
        "warnings": ["price_basis_unverified"],
    }


def test_register_endpoint_reviews_pending_captures_with_registered_evidence(
    tmp_path: Path,
) -> None:
    # Given: a saved capture with no review yet (deferred-review flow).
    token = tmp_path.name
    reviewer = RecordingReviewer()
    app = create_app(
        _settings(tmp_path, token),
        provider=FixtureOhlcvProvider(),
        reviewer=reviewer,
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/captures", json=_capture_payload(), headers=_auth(token)
        )
        assert created.status_code == 201
        capture_id = str(created.json()["capture"]["id"])

        # When: the session CSV (covering before and after the decision) is registered.
        rows = [
            *_session_rows(210),
            "2026-07-09T09:00:00+09:00,2000,2010,1990,2005,1500",
            "2026-07-09T13:00:00+09:00,2100,2110,2090,2105,1500",
        ]
        response = client.post(
            "/api/bar-series",
            json={"symbol": "214450", "timeframe": "240", "csv_text": _csv(rows)},
            headers=_auth(token),
        )

        # Then: the capture is reviewed once using the registered evidence.
        assert response.status_code == 200
        body = response.json()
        assert body["coverage"]["bar_count"] == 212
        assert reviewer.calls == 1
        assert len(body["reviews"]) == 1
        review = body["reviews"][0]
        assert review["capture_id"] == capture_id
        assert review["status"] == "ready"
        assert review["evidence"]["provider"] == "tradingview_csv"
        assert review["evidence"]["data_status"] == "ready"

        # And: re-registering does not re-review an already complete review.
        again = client.post(
            "/api/bar-series",
            json={"symbol": "214450", "timeframe": "240", "csv_text": _csv(rows)},
            headers=_auth(token),
        )
        assert again.status_code == 200
        assert reviewer.calls == 1
        assert again.json()["reviews"] == []


def test_coverage_endpoint_reports_registration_state(tmp_path: Path) -> None:
    token = tmp_path.name
    app = create_app(_settings(tmp_path, token), provider=FixtureOhlcvProvider())
    with TestClient(app) as client:
        empty = client.get(
            "/api/bar-series/coverage",
            params={"symbol": "214450", "timeframe": "240"},
            headers=_auth(token),
        )
        assert empty.status_code == 200
        assert empty.json() == {"registered": False, "coverage": None}

        _ = client.post(
            "/api/bar-series",
            json={
                "symbol": "214450",
                "timeframe": "240",
                "csv_text": _csv(_session_rows(4)),
            },
            headers=_auth(token),
        )
        covered = client.get(
            "/api/bar-series/coverage",
            params={"symbol": "214450", "timeframe": "240"},
            headers=_auth(token),
        )
        assert covered.status_code == 200
        body = covered.json()
        assert body["registered"] is True
        assert body["coverage"]["last_time_exchange"] == "2026-06-02T13:00:00+09:00"


def test_bar_series_requires_auth(tmp_path: Path) -> None:
    settings = _settings(tmp_path, tmp_path.name)
    app = create_app(settings, provider=FixtureOhlcvProvider())
    with TestClient(app) as client:
        rejected = client.post(
            "/api/bar-series",
            json={"symbol": "214450", "timeframe": "240", "csv_text": "time,open\n"},
        )
        assert rejected.status_code == 401
