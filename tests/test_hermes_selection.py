import json

import pytest
from pydantic import ValidationError

from fractal_journal.hermes_selection import HermesAuthoredSelection


def test_selection_rejects_duplicate_codes() -> None:
    # Given
    raw = _selection_json().replace(
        b'["sma50_value_available"]',
        b'["sma50_value_available","sma50_value_available"]',
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = HermesAuthoredSelection.model_validate_json(raw)

    # Then
    assert raised.value.error_count() == 1


@pytest.mark.parametrize(
    "stem",
    [
        "sma50_value",
        "sma200_value",
        "vwma100_value",
        "sma50_slope",
        "sma200_slope",
        "vwma100_slope",
        "sma50_distance",
        "sma200_distance",
        "vwma100_distance",
        "signed_gap",
    ],
)
def test_selection_rejects_available_and_missing_counterparts(stem: str) -> None:
    # Given
    raw = _selection_json(
        assessment="insufficient",
        sufficient_codes=[f"{stem}_available"],
        missing_codes=[f"{stem}_missing"],
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = HermesAuthoredSelection.model_validate_json(raw)

    # Then
    assert raised.value.error_count() == 1


@pytest.mark.parametrize(
    ("sufficient", "missing"),
    [
        (["gap_narrowing", "gap_widening"], []),
        (["gap_narrowing", "gap_flat"], []),
        (["bars_sufficient"], ["bars_insufficient"]),
        (["data_fresh"], ["data_stale"]),
        (["provider_complete"], ["provider_partial"]),
        (["hypothesis_aligned"], ["hypothesis_unsupported"]),
    ],
)
def test_selection_rejects_mutually_exclusive_facts(
    sufficient: list[str],
    missing: list[str],
) -> None:
    # Given
    raw = _selection_json(
        assessment="insufficient" if missing else "balanced",
        sufficient_codes=sufficient,
        missing_codes=missing,
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = HermesAuthoredSelection.model_validate_json(raw)

    # Then
    assert raised.value.error_count() == 1


def test_selection_rejects_balanced_assessment_with_contradiction() -> None:
    # Given
    raw = _selection_json(
        contradiction_codes=["golden_gap_direction_conflict"],
    )

    # When
    with pytest.raises(ValidationError) as raised:
        _ = HermesAuthoredSelection.model_validate_json(raw)

    # Then
    assert raised.value.error_count() == 1


def _selection_json(
    *,
    assessment: str = "balanced",
    sufficient_codes: list[str] | None = None,
    missing_codes: list[str] | None = None,
    contradiction_codes: list[str] | None = None,
) -> bytes:
    return json.dumps(
        {
            "overall_assessment": assessment,
            "sufficient_codes": sufficient_codes or ["sma50_value_available"],
            "missing_codes": missing_codes or [],
            "excessive_codes": [],
            "contradiction_codes": contradiction_codes or [],
            "note_quality_code": "specific",
        },
    ).encode()
