from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import ClassVar, Final, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, model_validator

_SUFFICIENT_CODES: Final[frozenset[str]] = frozenset(
    {
        "sma50_value_available",
        "sma200_value_available",
        "vwma100_value_available",
        "sma50_slope_available",
        "sma200_slope_available",
        "vwma100_slope_available",
        "sma50_distance_available",
        "sma200_distance_available",
        "vwma100_distance_available",
        "signed_gap_available",
        "gap_narrowing",
        "gap_widening",
        "gap_flat",
        "bars_sufficient",
        "data_fresh",
        "provider_complete",
        "hypothesis_aligned",
    },
)
_MISSING_CODES: Final[frozenset[str]] = frozenset(
    {
        "sma50_value_missing",
        "sma200_value_missing",
        "vwma100_value_missing",
        "sma50_slope_missing",
        "sma200_slope_missing",
        "vwma100_slope_missing",
        "sma50_distance_missing",
        "sma200_distance_missing",
        "vwma100_distance_missing",
        "signed_gap_missing",
        "gap_trend_missing",
        "bars_insufficient",
        "data_stale",
        "provider_partial",
        "hypothesis_unsupported",
    },
)
_EXCESSIVE_CODES: Final[frozenset[str]] = frozenset(
    {
        "redundant_ma_confirmation",
        "redundant_distance_confirmation",
        "redundant_volume_confirmation",
        "single_signal_overweighted",
    },
)
_CONTRADICTION_CODES: Final[frozenset[str]] = frozenset(
    {
        "golden_gap_direction_conflict",
        "dead_gap_direction_conflict",
        "slope_hypothesis_conflict",
        "vwma_hypothesis_conflict",
        "price_distance_hypothesis_conflict",
        "provider_data_conflict",
    },
)
Assessment = Literal["insufficient", "balanced", "overconfirmed", "conflicted"]


class WorkerInputError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid worker input")


class WorkerResponseError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid Hermes model response")


class WorkerAuthoredSelection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    overall_assessment: Assessment
    sufficient_codes: tuple[str, ...]
    missing_codes: tuple[str, ...]
    excessive_codes: tuple[str, ...]
    contradiction_codes: tuple[str, ...]
    note_quality_code: Literal["specific", "vague", "missing"]

    @model_validator(mode="after")
    def validate_code_vocabulary(self) -> WorkerAuthoredSelection:
        valid = (
            set(self.sufficient_codes) <= _SUFFICIENT_CODES
            and set(self.missing_codes) <= _MISSING_CODES
            and set(self.excessive_codes) <= _EXCESSIVE_CODES
            and set(self.contradiction_codes) <= _CONTRADICTION_CODES
        )
        if not valid:
            raise WorkerResponseError
        return self


class WorkerSelectionData(TypedDict):
    overall_assessment: Assessment
    sufficient_codes: tuple[str, ...]
    missing_codes: tuple[str, ...]
    excessive_codes: tuple[str, ...]
    contradiction_codes: tuple[str, ...]
    note_quality_code: str


class WorkerEnvelopeData(TypedDict):
    schema_version: Literal["hermes_worker_envelope.v1"]
    review_created_at_utc: str
    review_model: str
    review_profile: Literal["trading"]
    input_sha256: str
    selection: WorkerSelectionData


def wrap_review_response(response: str, model: str, prompt: str) -> str:
    selection = _parse_selection(response)
    envelope = WorkerEnvelopeData(
        schema_version="hermes_worker_envelope.v1",
        review_created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        review_model=model,
        review_profile="trading",
        input_sha256=_trusted_input_hash(prompt),
        selection=WorkerSelectionData(
            overall_assessment=_derive_assessment(selection),
            sufficient_codes=selection.sufficient_codes,
            missing_codes=selection.missing_codes,
            excessive_codes=selection.excessive_codes,
            contradiction_codes=selection.contradiction_codes,
            note_quality_code=selection.note_quality_code,
        ),
    )
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def _derive_assessment(selection: WorkerAuthoredSelection) -> Assessment:
    if selection.contradiction_codes:
        return "conflicted"
    if selection.excessive_codes:
        return "overconfirmed"
    if selection.missing_codes:
        return "insufficient"
    return "balanced"


def _parse_selection(response: str) -> WorkerAuthoredSelection:
    try:
        json.loads(response, object_pairs_hook=_reject_duplicate_keys)
        return WorkerAuthoredSelection.model_validate_json(
            response,
            strict=True,
            extra="forbid",
        )
    except (json.JSONDecodeError, ValidationError, WorkerResponseError) as exc:
        raise WorkerResponseError from exc


def _reject_duplicate_keys(
    pairs: list[tuple[str, JsonValue]],
) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerResponseError
        result[key] = value
    return result


def _trusted_input_hash(prompt: str) -> str:
    first_line = prompt.partition("\n")[0]
    match = re.fullmatch(r"INPUT_SHA256=([0-9a-f]{64})", first_line)
    if match is None:
        raise WorkerInputError
    return match.group(1)
