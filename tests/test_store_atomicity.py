from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fractal_journal.schemas import CaptureCreate, CaptureRecord
from fractal_journal.store import FileCaptureStore

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
INJECTED_FAILURE = "injected journal replacement failure"


def test_journal_commit_failure_rolls_back_new_screenshot_and_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    screenshots = tmp_path / "screenshots"
    store = FileCaptureStore(tmp_path, screenshots)
    existing = store.create_capture(_capture_payload("existing"))
    journal_path = tmp_path / "captures.jsonl"
    journal_before = journal_path.read_bytes()
    screenshots_before = tuple(screenshots.iterdir())
    original_replace = Path.replace

    def fail_journal_replace(source: Path, target: Path | str) -> Path:
        if Path(target) == journal_path:
            raise OSError(INJECTED_FAILURE)
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_journal_replace)

    # When
    with pytest.raises(OSError, match=INJECTED_FAILURE):
        _ = store.create_capture(_capture_payload("failed"))

    # Then
    assert journal_path.read_bytes() == journal_before
    assert store.list_captures(10) == (existing,)
    assert tuple(screenshots.iterdir()) == screenshots_before
    assert not tuple(tmp_path.rglob("*.tmp"))


def test_concurrent_capture_writes_preserve_every_jsonl_record(tmp_path: Path) -> None:
    # Given
    screenshots = tmp_path / "screenshots"
    store = FileCaptureStore(tmp_path, screenshots)
    capture_count = 32

    # When
    with ThreadPoolExecutor(max_workers=8) as executor:
        records = tuple(
            executor.map(
                store.create_capture,
                (_capture_payload(str(index)) for index in range(capture_count)),
            ),
        )

    # Then
    journal_lines = (tmp_path / "captures.jsonl").read_text(
        encoding="utf-8",
    ).splitlines()
    parsed = tuple(CaptureRecord.model_validate_json(line) for line in journal_lines)
    assert len(records) == capture_count
    assert len({record.id for record in records}) == capture_count
    assert {record.id for record in parsed} == {record.id for record in records}
    assert len(tuple(screenshots.glob("*.png"))) == capture_count
    assert not tuple(tmp_path.rglob("*.tmp"))


def _capture_payload(note: str) -> CaptureCreate:
    screenshot = b64encode(PNG_1X1).decode("ascii")
    decision_time = "2026-07-09T10:00:00+09:00"
    return CaptureCreate.model_validate(
        {
            "screenshot_data_url": f"data:image/png;base64,{screenshot}",
            "extracted": {
                "source_url": "https://www.tradingview.com/chart/example/",
                "page_title": "005930 5 Samsung Electronics",
                "symbol_candidate": "005930",
                "timeframe_candidate": "5",
                "decision_time_candidate": decision_time,
                "replay_active": True,
                "captured_at": datetime(2026, 7, 9, 1, tzinfo=UTC).isoformat(),
            },
            "confirmed": {
                "symbol": "005930",
                "provider_symbol": "005930",
                "market_div_code": "J",
                "timeframe": "5",
                "decision_time_exchange": decision_time,
                "exchange_tz": "Asia/Seoul",
                "provider_status": "ready",
            },
            "setup": "ma_crossover",
            "hypothesis": "golden_cross_expected",
            "decision_note": note,
            "warnings": ["price_basis_unverified"],
        },
    )
