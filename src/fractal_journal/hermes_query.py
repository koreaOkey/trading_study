from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from fractal_journal.chart_query import (
    ChartQueryError,
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


class QueryEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    answered_at_utc: str
    model: str
    input_sha256: str
    answer: str


@dataclass(frozen=True, slots=True)
class ChartQueryAnswer:
    answer: str
    model: str


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
        prompt = build_query_prompt(
            symbol=symbol,
            timeframe=timeframe,
            question=question,
            context=context,
        )
        process = self.runner.run(
            HermesProcessRequest(
                argv=(
                    str(self.settings.hermes_python_path),
                    str(self.settings.hermes_query_worker_path),
                ),
                stdin=prompt.stdin,
                env=build_hermes_subprocess_env(self.settings.hermes_home),
                timeout_seconds=self.settings.hermes_timeout_seconds,
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
        if envelope.schema_version != "hermes_query_envelope.v1":
            raise ChartQueryError(_INVALID)
        if envelope.input_sha256 != prompt.input_sha256:
            raise ChartQueryError(_INVALID)
        if not envelope.answer.strip():
            raise ChartQueryError(_EMPTY)
        if answer_contains_blocked_action(envelope.answer):
            raise ChartQueryError(_BLOCKED)
        return ChartQueryAnswer(answer=envelope.answer, model=envelope.model)


def create_chart_query_service(settings: Settings) -> HermesChartQueryService:
    return HermesChartQueryService(settings=settings, runner=SubprocessHermesRunner())
