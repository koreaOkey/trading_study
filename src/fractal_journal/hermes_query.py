from __future__ import annotations

import csv
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from fractal_journal.chart_query import (
    BARS_CSV_COLUMNS,
    BARS_CSV_FILENAME,
    ChartQueryError,
    QueryComputation,
    answer_contains_blocked_action,
    build_query_context,
    build_query_prompt,
)
from fractal_journal.hermes_review import (
    HermesProcessRequest,
    HermesProcessRunner,
    SubprocessHermesRunner,
    build_hermes_subprocess_env,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fractal_journal.config import Settings
    from fractal_journal.provider import OhlcvBar

_TIMEOUT: Final = "hermes_timeout"
_UNAVAILABLE: Final = "hermes_unavailable"
_INVALID: Final = "invalid_response"
_EMPTY: Final = "empty_answer"
_BLOCKED: Final = "blocked_action_in_answer"

QUERY_ENVELOPE_SCHEMA: Final = "hermes_query_envelope.v2"


class QueryEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    answered_at_utc: str
    model: str
    input_sha256: str
    answer: str
    computations: tuple[QueryComputation, ...] = ()


@dataclass(frozen=True, slots=True)
class ChartQueryAnswer:
    answer: str
    model: str
    computations: tuple[QueryComputation, ...] = ()


def _write_bars_csv(path: Path, bars: Sequence[OhlcvBar]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(BARS_CSV_COLUMNS)
        for bar in bars:
            writer.writerow(
                (
                    bar.time_exchange,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                ),
            )


@dataclass(frozen=True, slots=True)
class HermesChartQueryService:
    settings: Settings
    runner: HermesProcessRunner

    def ask(
        self,
        *,
        symbol: str,
        timeframe: str,
        question: str,
        bars: Sequence[OhlcvBar],
    ) -> ChartQueryAnswer:
        context = build_query_context(bars)
        with tempfile.TemporaryDirectory(prefix="fjq-workdir-") as workdir:
            _write_bars_csv(Path(workdir) / BARS_CSV_FILENAME, bars)
            prompt = build_query_prompt(
                symbol=symbol,
                timeframe=timeframe,
                question=question,
                context=context,
                workdir=workdir,
                bar_count=len(bars),
            )
            process = self.runner.run(
                HermesProcessRequest(
                    argv=(
                        str(self.settings.hermes_python_path),
                        str(self.settings.hermes_query_worker_path),
                    ),
                    stdin=prompt.stdin,
                    env=build_hermes_subprocess_env(self.settings.hermes_home),
                    timeout_seconds=self.settings.hermes_query_timeout_seconds,
                    output_max_bytes=self.settings.hermes_output_max_bytes,
                ),
            )
        if process.timed_out:
            raise ChartQueryError(_TIMEOUT)
        if process.oversized or process.exit_code != 0:
            raise ChartQueryError(_UNAVAILABLE)
        try:
            envelope = QueryEnvelope.model_validate(json.loads(process.stdout))
        except (ValidationError, ValueError) as exc:
            raise ChartQueryError(_INVALID) from exc
        if envelope.schema_version != QUERY_ENVELOPE_SCHEMA:
            raise ChartQueryError(_INVALID)
        if envelope.input_sha256 != prompt.input_sha256:
            raise ChartQueryError(_INVALID)
        if not envelope.answer.strip():
            raise ChartQueryError(_EMPTY)
        if answer_contains_blocked_action(envelope.answer):
            raise ChartQueryError(_BLOCKED)
        return ChartQueryAnswer(
            answer=envelope.answer,
            model=envelope.model,
            computations=envelope.computations,
        )


def create_chart_query_service(settings: Settings) -> HermesChartQueryService:
    return HermesChartQueryService(settings=settings, runner=SubprocessHermesRunner())
