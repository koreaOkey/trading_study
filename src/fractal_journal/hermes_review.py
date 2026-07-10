from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import ValidationError

from fractal_journal.ai_review import DecisionReview, DecisionReviewFailureCode
from fractal_journal.hermes_safety import build_review_prompt, contains_blocked_action
from fractal_journal.hermes_selection import HermesWorkerEnvelope
from fractal_journal.hermes_semantics import review_from_trusted_context

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from fractal_journal.config import Settings
    from fractal_journal.schemas import CaptureRecord, Hypothesis, MaCrossoverEvidence

_JSON_FENCE: Final = re.compile(r"\A```json\n(?P<body>.+)\n```\s*\Z", re.DOTALL)


@dataclass(frozen=True, slots=True)
class HermesProcessRequest:
    argv: tuple[str, ...]
    stdin: bytes
    env: Mapping[str, str]
    timeout_seconds: float
    output_max_bytes: int


@dataclass(frozen=True, slots=True)
class HermesProcessResult:
    exit_code: int | None
    stdout: bytes
    timed_out: bool = False
    oversized: bool = False


class HermesProcessRunner(Protocol):
    def run(self, request: HermesProcessRequest) -> HermesProcessResult: ...


@dataclass(frozen=True, slots=True)
class HermesReviewOutput:
    review: DecisionReview
    raw_output_sha256: str


class DecisionReviewer(Protocol):
    def review(
        self, capture: CaptureRecord, evidence: MaCrossoverEvidence,
    ) -> HermesReviewOutput: ...


class HermesReviewError(Exception):
    code: DecisionReviewFailureCode
    message: str
    retryable: bool
    raw_output_sha256: str | None

    def __init__(
        self,
        *,
        code: DecisionReviewFailureCode,
        message: str,
        retryable: bool,
        raw_output_sha256: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.raw_output_sha256 = raw_output_sha256


@dataclass(frozen=True, slots=True)
class SubprocessHermesRunner:
    def run(self, request: HermesProcessRequest) -> HermesProcessResult:
        try:
            process = subprocess.Popen(  # noqa: S603
                request.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=True,
                env=dict(request.env),
            )
        except OSError as exc:
            raise HermesReviewError(
                code=DecisionReviewFailureCode.HERMES_UNAVAILABLE,
                message="Hermes reviewer is unavailable",
                retryable=True,
            ) from exc

        with process:
            stdin = process.stdin
            stdout = process.stdout
            if stdin is None or stdout is None:
                _kill_process(process)
                raise HermesReviewError(
                    code=DecisionReviewFailureCode.HERMES_UNAVAILABLE,
                    message="Hermes reviewer is unavailable",
                    retryable=True,
                )
            try:
                _ = stdin.write(request.stdin)
            except BrokenPipeError:
                _ = process.poll()
            finally:
                stdin.close()

            output = bytearray()
            deadline = monotonic() + request.timeout_seconds
            with selectors.DefaultSelector() as selector:
                _ = selector.register(stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        _kill_process(process)
                        return HermesProcessResult(
                            exit_code=None,
                            stdout=bytes(output),
                            timed_out=True,
                        )
                    chunk = os.read(
                        stdout.fileno(),
                        min(65_536, request.output_max_bytes + 1 - len(output)),
                    )
                    if not chunk:
                        try:
                            exit_code = process.wait(timeout=max(remaining, 0.001))
                        except subprocess.TimeoutExpired:
                            _kill_process(process)
                            return HermesProcessResult(
                                exit_code=None,
                                stdout=bytes(output),
                                timed_out=True,
                            )
                        return HermesProcessResult(
                            exit_code=exit_code,
                            stdout=bytes(output),
                        )
                    output.extend(chunk)
                    if len(output) > request.output_max_bytes:
                        _kill_process(process)
                        return HermesProcessResult(
                            exit_code=process.returncode,
                            stdout=bytes(output[: request.output_max_bytes]),
                            oversized=True,
                        )


@dataclass(frozen=True, slots=True)
class HermesReviewer:
    settings: Settings
    runner: HermesProcessRunner

    def review(
        self,
        capture: CaptureRecord,
        evidence: MaCrossoverEvidence,
    ) -> HermesReviewOutput:
        prompt = build_review_prompt(capture, evidence)
        request = HermesProcessRequest(
            argv=(
                str(self.settings.hermes_python_path),
                str(self.settings.hermes_worker_path),
            ),
            stdin=prompt.stdin,
            env=build_hermes_subprocess_env(self.settings.hermes_home),
            timeout_seconds=self.settings.hermes_timeout_seconds,
            output_max_bytes=self.settings.hermes_output_max_bytes,
        )
        process = self.runner.run(request)
        return parse_hermes_process_result(
            process,
            expected_input_sha256=prompt.input_sha256,
            evidence=evidence,
            hypothesis=capture.hypothesis,
            decision_note_present=bool(capture.effective_decision_note.strip()),
        )


def create_hermes_reviewer(settings: Settings) -> HermesReviewer:
    return HermesReviewer(settings=settings, runner=SubprocessHermesRunner())


def build_hermes_subprocess_env(hermes_home: Path) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "LANG", "LC_ALL", "TZ") if key in os.environ
    }
    return env | {"HERMES_HOME": str(hermes_home)}


def parse_hermes_process_result(
    process: HermesProcessResult,
    *,
    expected_input_sha256: str,
    evidence: MaCrossoverEvidence,
    hypothesis: Hypothesis,
    decision_note_present: bool,
) -> HermesReviewOutput:
    raw_hash = sha256(process.stdout).hexdigest()
    if process.timed_out:
        raise HermesReviewError(
            code=DecisionReviewFailureCode.HERMES_TIMEOUT,
            message="Hermes reviewer timed out",
            retryable=True,
        )
    if process.oversized:
        raise _invalid_response(raw_hash)
    if process.exit_code != 0:
        raise HermesReviewError(
            code=DecisionReviewFailureCode.HERMES_UNAVAILABLE,
            message="Hermes reviewer is unavailable",
            retryable=True,
            raw_output_sha256=raw_hash if process.stdout else None,
        )
    response = _unwrap_json_fence(process.stdout)
    try:
        envelope = HermesWorkerEnvelope.model_validate_json(
            response,
            strict=True,
            extra="forbid",
        )
    except ValidationError as exc:
        raise _invalid_response(raw_hash) from exc
    if envelope.input_sha256 != expected_input_sha256:
        raise _invalid_response(raw_hash)
    try:
        review = review_from_trusted_context(
            envelope,
            evidence,
            hypothesis,
            decision_note_present=decision_note_present,
        )
    except ValueError as exc:
        raise _invalid_response(raw_hash) from exc
    if contains_blocked_action(review):
        raise _invalid_response(raw_hash)
    return HermesReviewOutput(review=review, raw_output_sha256=raw_hash)


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        _ = process.poll()
    try:
        _ = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        return


def _unwrap_json_fence(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise _invalid_response(sha256(raw).hexdigest()) from exc
    if not text.startswith("```"):
        return text.encode()
    match = _JSON_FENCE.fullmatch(text)
    if match is None:
        raise _invalid_response(sha256(raw).hexdigest())
    return match.group("body").encode()


def _invalid_response(raw_hash: str) -> HermesReviewError:
    return HermesReviewError(
        code=DecisionReviewFailureCode.INVALID_RESPONSE,
        message="Hermes reviewer returned an invalid response",
        retryable=False,
        raw_output_sha256=raw_hash,
    )
