import re
from _thread import RLock
from base64 import b64decode
from binascii import Error as Base64Error
from datetime import UTC, datetime
from hashlib import sha256
from os import fsync
from pathlib import Path
from secrets import token_hex
from shutil import copyfileobj

from fractal_journal.ai_review import AIReviewResult, DecisionReviewResult
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
        self._decision_reviews_dir: Path = data_dir / "decision_reviews"
        self._lock: RLock = RLock()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def ensure_ready(self) -> None:
        with self._lock:
            self._ensure_ready()

    def _ensure_ready(self) -> None:
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._scores_dir.mkdir(parents=True, exist_ok=True)
        self._reviews_dir.mkdir(parents=True, exist_ok=True)
        self._decision_reviews_dir.mkdir(parents=True, exist_ok=True)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._journal_path.touch(exist_ok=True)

    def create_capture(self, payload: CaptureCreate) -> CaptureRecord:
        with self._lock:
            self._ensure_ready()
            screenshot_bytes = _decode_png_data_url(payload.screenshot_data_url)
            capture_id = CaptureId(token_hex(12))
            screenshot_path = self._screenshots_dir / f"{capture_id}.png"
            screenshot_temp = self._screenshots_dir / (
                f".{capture_id}.{token_hex(6)}.png.tmp"
            )
            journal_temp = self._journal_path.with_name(
                f".{self._journal_path.name}.{token_hex(6)}.tmp",
            )
            record = CaptureRecord(
                id=capture_id,
                created_at=datetime.now(UTC),
                screenshot_sha256=sha256(screenshot_bytes).hexdigest(),
                screenshot_path=f"screenshots/{capture_id}.png",
                extracted=payload.extracted,
                confirmed=payload.confirmed,
                setup=payload.setup,
                hypothesis=payload.hypothesis,
                decision_note=payload.decision_note,
                decision=payload.decision,
                notes=payload.notes,
                warnings=payload.warnings,
            )
            try:
                _write_bytes_temp(screenshot_temp, screenshot_bytes)
                _ = screenshot_temp.replace(screenshot_path)
                _replace_journal(
                    self._journal_path,
                    journal_temp,
                    f"{record.model_dump_json()}\n".encode(),
                )
            except OSError:
                for path in (screenshot_temp, journal_temp, screenshot_path):
                    path.unlink(missing_ok=True)
                raise
            return record

    def list_captures(self, limit: int) -> tuple[CaptureRecord, ...]:
        with self._lock:
            self._ensure_ready()
            return self._list_captures(limit)

    def _list_captures(self, limit: int) -> tuple[CaptureRecord, ...]:
        records: list[CaptureRecord] = []
        with self._journal_path.open(encoding="utf-8") as journal_file:
            for line in journal_file:
                stripped = line.strip()
                if stripped:
                    records.append(CaptureRecord.model_validate_json(stripped))
        return tuple(reversed(records[-limit:]))

    def get_capture(self, capture_id: str) -> CaptureRecord:
        with self._lock:
            _validate_capture_id(capture_id)
            self._ensure_ready()
            for capture in self._list_captures(limit=10_000):
                if str(capture.id) == capture_id:
                    return capture
            raise CaptureNotFoundError(capture_id)

    def save_score(self, score: ScoreResult) -> ScoreResult:
        self.ensure_ready()
        _validate_capture_id(score.capture_id)
        path = self._scores_dir / f"{score.capture_id}.json"
        _atomic_write(path, score.model_dump_json())
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
        _atomic_write(path, review.model_dump_json())
        return review

    def load_ai_review(self, capture_id: str) -> AIReviewResult | None:
        _validate_capture_id(capture_id)
        path = self._reviews_dir / f"{capture_id}.json"
        try:
            return AIReviewResult.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_decision_review(
        self,
        review: DecisionReviewResult,
    ) -> DecisionReviewResult:
        self.ensure_ready()
        _validate_capture_id(review.capture_id)
        path = self._decision_reviews_dir / f"{review.capture_id}.json"
        _atomic_write(path, review.model_dump_json())
        return review

    def load_decision_review(self, capture_id: str) -> DecisionReviewResult | None:
        _validate_capture_id(capture_id)
        path = self._decision_reviews_dir / f"{capture_id}.json"
        try:
            return DecisionReviewResult.model_validate_json(
                path.read_text(encoding="utf-8"),
            )
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


def _atomic_write(path: Path, content: str) -> None:
    temporary_path = path.with_name(f".{path.name}.{token_hex(6)}.tmp")
    try:
        _write_bytes_temp(temporary_path, content.encode())
        _ = temporary_path.replace(path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_bytes_temp(path: Path, content: bytes) -> None:
    with path.open("xb") as temporary_file:
        _ = temporary_file.write(content)
        temporary_file.flush()
        fsync(temporary_file.fileno())


def _replace_journal(journal_path: Path, temporary_path: Path, line: bytes) -> None:
    with (
        journal_path.open("rb") as source,
        temporary_path.open("xb") as destination,
    ):
        copyfileobj(source, destination)
        _ = destination.write(line)
        destination.flush()
        fsync(destination.fileno())
    _ = temporary_path.replace(journal_path)
