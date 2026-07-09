import re
from base64 import b64decode
from binascii import Error as Base64Error
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from secrets import token_hex

from fractal_journal.ai_review import AIReviewResult
from fractal_journal.schemas import CaptureCreate, CaptureId, CaptureRecord
from fractal_journal.scoring import ScoreResult

CAPTURE_ID_PATTERN = re.compile(r"^[0-9a-f]{24}$")
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024


class InvalidScreenshotError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason


class CaptureNotFoundError(Exception):
    def __init__(self, capture_id: str) -> None:
        super().__init__(capture_id)
        self.capture_id: str = capture_id


class FileCaptureStore:
    def __init__(self, data_dir: Path, screenshot_dir: Path | None = None) -> None:
        self._data_dir: Path = data_dir
        self._screenshots_dir: Path = screenshot_dir or data_dir / "screenshots"
        self._journal_path: Path = data_dir / "captures.jsonl"
        self._scores_dir: Path = data_dir / "scores"
        self._reviews_dir: Path = data_dir / "ai_reviews"

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def ensure_ready(self) -> None:
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._scores_dir.mkdir(parents=True, exist_ok=True)
        self._reviews_dir.mkdir(parents=True, exist_ok=True)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._journal_path.touch(exist_ok=True)

    def create_capture(self, payload: CaptureCreate) -> CaptureRecord:
        self.ensure_ready()
        screenshot_bytes = _decode_png_data_url(payload.screenshot_data_url)
        digest = sha256(screenshot_bytes).hexdigest()
        capture_id = CaptureId(token_hex(12))
        screenshot_path = self._screenshots_dir / f"{capture_id}.png"
        with screenshot_path.open("wb") as screenshot_file:
            _ = screenshot_file.write(screenshot_bytes)
        record = CaptureRecord(
            id=capture_id,
            created_at=datetime.now(UTC),
            screenshot_sha256=digest,
            screenshot_path=f"screenshots/{capture_id}.png",
            extracted=payload.extracted,
            confirmed=payload.confirmed,
            decision=payload.decision,
            notes=payload.notes,
            warnings=payload.warnings,
        )
        with self._journal_path.open("a", encoding="utf-8") as journal_file:
            _ = journal_file.write(record.model_dump_json())
            _ = journal_file.write("\n")
        return record

    def list_captures(self, limit: int) -> tuple[CaptureRecord, ...]:
        self.ensure_ready()
        records: list[CaptureRecord] = []
        with self._journal_path.open(encoding="utf-8") as journal_file:
            for line in journal_file:
                stripped = line.strip()
                if stripped:
                    records.append(CaptureRecord.model_validate_json(stripped))
        return tuple(reversed(records[-limit:]))

    def get_capture(self, capture_id: str) -> CaptureRecord:
        _validate_capture_id(capture_id)
        for capture in self.list_captures(limit=10_000):
            if str(capture.id) == capture_id:
                return capture
        raise CaptureNotFoundError(capture_id)

    def save_score(self, score: ScoreResult) -> ScoreResult:
        self.ensure_ready()
        _validate_capture_id(score.capture_id)
        path = self._scores_dir / f"{score.capture_id}.json"
        _ = path.write_text(score.model_dump_json(), encoding="utf-8")
        return score

    def load_score(self, capture_id: str) -> ScoreResult | None:
        _validate_capture_id(capture_id)
        path = self._scores_dir / f"{capture_id}.json"
        try:
            return ScoreResult.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_ai_review(self, review: AIReviewResult) -> AIReviewResult:
        self.ensure_ready()
        _validate_capture_id(review.capture_id)
        path = self._reviews_dir / f"{review.capture_id}.json"
        _ = path.write_text(review.model_dump_json(), encoding="utf-8")
        return review

    def load_ai_review(self, capture_id: str) -> AIReviewResult | None:
        _validate_capture_id(capture_id)
        path = self._reviews_dir / f"{capture_id}.json"
        try:
            return AIReviewResult.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None


def _decode_png_data_url(data_url: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise InvalidScreenshotError(reason="expected_png_data_url")
    raw_base64 = data_url.removeprefix(prefix)
    try:
        decoded = b64decode(raw_base64, validate=True)
    except (Base64Error, ValueError) as exc:
        raise InvalidScreenshotError(reason="invalid_base64") from exc
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise InvalidScreenshotError(reason="invalid_png_signature")
    if len(decoded) > MAX_SCREENSHOT_BYTES:
        raise InvalidScreenshotError(reason="screenshot_too_large")
    return decoded


def _validate_capture_id(capture_id: str) -> None:
    if CAPTURE_ID_PATTERN.fullmatch(capture_id) is None:
        raise CaptureNotFoundError(capture_id)
