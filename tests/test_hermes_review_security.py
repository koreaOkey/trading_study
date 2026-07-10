import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from fractal_journal.ai_review import RISK_NOTE, DecisionReviewFailureCode
from fractal_journal.hermes_review import (
    HermesProcessResult,
    HermesReviewError,
    HermesReviewOutput,
    build_hermes_subprocess_env,
    parse_hermes_process_result,
)
from fractal_journal.schemas import (
    EvidenceDataStatus,
    GapTrend,
    Hypothesis,
    IndicatorMeasurement,
    MaCrossoverEvidence,
)


def test_worker_environment_forwards_only_non_secret_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    allowed = {
        "HOME": "/home/test",
        "PATH": "/usr/bin",
        "LANG": "ko_KR.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "Asia/Seoul",
    }
    blocked = {
        "ARBITRARY_SENTINEL": "private",
        "KIS_APP_SECRET": "kis-secret",
        "TRFJ_SHARED_API_TOKEN": "journal-secret",
        "OPENAI_API_KEY": "provider-secret",
        "HTTPS_PROXY": "http://user:password@proxy",
        "HERMES_HOME": "/wrong/profile",
    }
    for key, value in (allowed | blocked).items():
        monkeypatch.setenv(key, value)

    # When
    env = build_hermes_subprocess_env(Path("/profiles/trading"))

    # Then
    assert env == allowed | {"HERMES_HOME": "/profiles/trading"}


@pytest.mark.parametrize(
    "action_advice",
    [
        "buy now",
        "sell now",
        "enter now",
        "go long",
        "go short",
        "purchase immediately",
        "\uff42\uff55\uff59\u200b\u3000\uff4e\uff4f\uff57",
        "매\u200b수하세요",
        "지금 사세요",
        "매수를 권장합니다",
    ],
)
def test_review_rejects_english_action_advice_after_validation(
    action_advice: str,
) -> None:
    # Given
    input_hash = "a" * 64
    raw = _selection_json(input_hash, sufficient_codes=[action_advice])

    # When
    with pytest.raises(HermesReviewError) as raised:
        _ = _parse(raw, input_hash)

    # Then
    assert raised.value.code is DecisionReviewFailureCode.INVALID_RESPONSE


def test_review_rejects_unicode_escaped_action_advice_after_json_decode() -> None:
    # Given
    input_hash = "a" * 64
    raw = _selection_json(input_hash, sufficient_codes=["매수하세요"]).replace(
        "매수하세요".encode(),
        b"\\ub9e4\\uc218\\ud558\\uc138\\uc694",
    )

    # When
    with pytest.raises(HermesReviewError) as raised:
        _ = _parse(raw, input_hash)

    # Then
    assert raised.value.code is DecisionReviewFailureCode.INVALID_RESPONSE


def test_review_rejects_model_authored_prose_even_without_action_advice() -> None:
    # Given
    input_hash = "a" * 64
    raw = (
        _selection_json(input_hash)[:-1]
        + ',"summary":"모델이 자유롭게 작성한 임의 평가 문장"}'.encode()
    )

    # When
    with pytest.raises(HermesReviewError) as raised:
        _ = _parse(raw, input_hash)

    # Then
    assert raised.value.code is DecisionReviewFailureCode.INVALID_RESPONSE


def test_review_maps_code_only_selection_to_server_owned_text() -> None:
    # Given
    input_hash = "a" * 64
    raw = _selection_json(input_hash)

    # When
    output = _parse(raw, input_hash)

    # Then
    assert output.review.summary == "판단 근거의 균형이 적절한 상태다."
    assert output.review.sufficient_evidence == (
        "SMA50 값이 판단 시점 데이터에 포함되어 있다.",
    )
    assert "가설: 골든크로스 예상" in output.review.revised_decision_note
    assert "SMA50=100" in output.review.revised_decision_note
    assert output.review.risk_note == RISK_NOTE


@pytest.mark.parametrize(
    "instruction",
    ["buy now", "purchase immediately", "매수하세요", "지금 사세요"],
)
def test_selection_rejects_instruction_in_model_metadata(instruction: str) -> None:
    # Given
    input_hash = "a" * 64
    raw = _selection_json(input_hash).replace(b"gpt-5.5", instruction.encode())

    # When
    with pytest.raises(HermesReviewError) as raised:
        _ = _parse(raw, input_hash)

    # Then
    assert raised.value.code is DecisionReviewFailureCode.INVALID_RESPONSE


def test_selection_rejects_unknown_finding_code() -> None:
    # Given
    input_hash = "a" * 64
    raw = _selection_json(input_hash, sufficient_codes=["future_magic_signal"])

    # When
    with pytest.raises(HermesReviewError) as raised:
        _ = _parse(raw, input_hash)

    # Then
    assert raised.value.code is DecisionReviewFailureCode.INVALID_RESPONSE


def test_selection_rejects_mismatched_input_hash() -> None:
    # Given
    raw = _selection_json("a" * 64)

    # When
    with pytest.raises(HermesReviewError) as raised:
        _ = _parse(raw, "b" * 64)

    # Then
    assert raised.value.code is DecisionReviewFailureCode.INVALID_RESPONSE


def _selection_json(
    input_hash: str,
    *,
    sufficient_codes: list[str] | None = None,
) -> bytes:
    return json.dumps(
        {
            "schema_version": "hermes_worker_envelope.v1",
            "review_created_at_utc": "2026-07-10T01:00:00Z",
            "review_model": "gpt-5.5",
            "review_profile": "trading",
            "input_sha256": input_hash,
            "selection": {
                "overall_assessment": "balanced",
                "sufficient_codes": sufficient_codes
                or ["sma50_value_available"],
                "missing_codes": [],
                "excessive_codes": [],
                "contradiction_codes": [],
                "note_quality_code": "specific",
            },
        },
        ensure_ascii=False,
    ).encode()


def _parse(raw: bytes, input_hash: str) -> HermesReviewOutput:
    return parse_hermes_process_result(
        HermesProcessResult(exit_code=0, stdout=raw),
        expected_input_sha256=input_hash,
        evidence=_evidence(),
        hypothesis=Hypothesis.GOLDEN_CROSS_EXPECTED,
        decision_note_present=True,
    )


def _evidence() -> MaCrossoverEvidence:
    measurement = IndicatorMeasurement(
        value=Decimal(100),
        previous_value=Decimal(99),
        slope_pct=Decimal("1.01"),
        distance_from_close_pct=Decimal("0.5"),
        bars_used=200,
    )
    decision_time = datetime.fromisoformat("2026-07-10T10:00:00+09:00")
    return MaCrossoverEvidence(
        provider="kis",
        provider_symbol="005930",
        timeframe="5",
        decision_time_exchange=decision_time,
        data_status=EvidenceDataStatus.READY,
        bar_count=200,
        last_bar_time_exchange=decision_time,
        close=Decimal(101),
        volume=Decimal(100000),
        sma_50=measurement,
        sma_200=measurement,
        vwma_100=measurement,
        sma_50_to_sma_200_gap_pct=Decimal("-0.2"),
        gap_trend=GapTrend.NARROWING,
    )
