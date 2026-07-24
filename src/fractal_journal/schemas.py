from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Final, Literal, NewType, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from pydantic_core import PydanticCustomError

CaptureId = NewType("CaptureId", str)
MAX_SCREENSHOT_DATA_URL_LENGTH = 14_000_000
INVALID_DECISION_TIME_CODE: Final = "decision_time_exchange"
INVALID_DECISION_TIME_MESSAGE: Final = "decision time must be an ISO timestamp"
MISSING_DECISION_TIME_TZ_CODE: Final = "decision_time_exchange_timezone"
MISSING_DECISION_TIME_TZ_MESSAGE: Final = "decision time must include a timezone offset"
INVALID_CAPTURE_PAYLOAD_VARIANT_CODE: Final = "capture_payload_variant"
INVALID_CAPTURE_PAYLOAD_VARIANT_MESSAGE: Final = (
    "capture must contain either setup, hypothesis, and decision_note "
    "or a legacy decision"
)


class Decision(StrEnum):
    LONG = "long"
    SHORT = "short"
    SKIP = "skip"
    WATCH = "watch"


class Setup(StrEnum):
    MA_CROSSOVER = "ma_crossover"


class Hypothesis(StrEnum):
    GOLDEN_CROSS_EXPECTED = "golden_cross_expected"
    DEAD_CROSS_EXPECTED = "dead_cross_expected"
    UNCERTAIN = "uncertain"


class EvidenceDataStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class GapTrend(StrEnum):
    NARROWING = "narrowing"
    WIDENING = "widening"
    FLAT = "flat"


class WarningCode(StrEnum):
    PROVIDER_SYMBOL_UNCONFIRMED = "provider_symbol_unconfirmed"
    PRICE_BASIS_UNVERIFIED = "price_basis_unverified"
    PARTIAL_DATA = "partial_data"
    EMPTY_DATA = "empty_data"
    REQUEST_DATE_MISMATCH = "request_date_mismatch"
    AFTER_REGULAR_CLOSE_CLAMPED = "after_regular_close_clamped"
    CLOSE_AUCTION_BAR = "close_auction_bar"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    RETRY_EXHAUSTED = "retry_exhausted"


class ProviderStatus(StrEnum):
    CANDIDATE = "candidate"
    READY = "ready"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    EMPTY = "empty"


class ExtractedMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    source_url: HttpUrl
    page_title: str = Field(min_length=1, max_length=240)
    symbol_candidate: str = Field(default="", max_length=32)
    symbol_name_candidate: str = Field(default="", max_length=80)
    timeframe_candidate: str = Field(default="", max_length=16)
    decision_time_candidate: str = Field(default="", max_length=40)
    replay_active: bool = False
    captured_at: datetime


class ConfirmedMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=32)
    provider: str = Field(default="kis", max_length=24)
    provider_symbol: str = Field(default="", max_length=32)
    market_div_code: str = Field(default="J", max_length=8)
    timeframe: str = Field(min_length=1, max_length=16)
    decision_time_exchange: str = Field(default="", max_length=40)
    exchange_tz: str = Field(default="Asia/Seoul", max_length=64)
    price_basis: str = Field(default="unknown_unadjusted_assumed", max_length=40)
    session_state: str = Field(default="regular", max_length=32)
    provider_status: ProviderStatus = ProviderStatus.CANDIDATE
    scenario: str = Field(default="wait", max_length=24)
    confidence: int = Field(default=3, ge=1, le=5)
    invalidation: str = Field(default="", max_length=400)
    supply_zone_price: Decimal | None = Field(default=None, gt=0)


class IndicatorMeasurement(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    value: Decimal | None = None
    previous_value: Decimal | None = None
    slope_pct: Decimal | None = None
    distance_from_close_pct: Decimal | None = None
    bars_used: int = Field(default=0, ge=0)
    null_reason: str | None = Field(default=None, max_length=200)


class ThresholdProjectionPoint(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    bar_offset: int = Field(ge=1)
    min_close: Decimal


class CrossProbabilityEstimate(BaseModel):
    """Bootstrap Monte Carlo estimate of the golden-cross outcome.

    Pre-cross: probability that SMA50 reaches SMA200 within horizon_bars.
    Post-cross: probability that the cross survives every bar of the horizon.
    Future closes are simulated by resampling the symbol's own recent bar
    returns — descriptive statistics under a stated assumption, not a trade
    instruction and not a market forecast.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["cross_probability.v1"] = "cross_probability.v1"
    method: Literal["bootstrap_monte_carlo"] = "bootstrap_monte_carlo"
    target: Literal["reach_cross", "hold_cross"]
    horizon_bars: int = Field(ge=1)
    paths: int = Field(ge=1)
    probability_pct: Decimal
    return_sample_bars: int = Field(ge=1)


class BreakoutProbabilityEstimate(BaseModel):
    """Monte Carlo estimate of closing above each MA for confirm_bars in a row.

    A breakout counts only when the simulated close finishes above the
    (co-simulated, moving) MA for confirm_bars consecutive bars within the
    horizon. Volumes are resampled in pairs with their bar returns so the
    VWMA keeps the symbol's own return-volume relationship. Descriptive
    statistics under a stated assumption — not a forecast or instruction.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["breakout_probability.v1"] = "breakout_probability.v1"
    method: Literal["bootstrap_monte_carlo"] = "bootstrap_monte_carlo"
    horizon_bars: int = Field(ge=1)
    confirm_bars: int = Field(ge=1)
    paths: int = Field(ge=1)
    sma50_pct: Decimal | None = None
    sma200_pct: Decimal | None = None
    vwma100_pct: Decimal | None = None
    all_above_pct: Decimal | None = None
    return_sample_bars: int = Field(ge=1)


class LevelBreakoutProbabilityEstimate(BaseModel):
    """Monte Carlo estimate of closing above a fixed manual price level.

    The level is user-supplied at submission (supply-zone upper bound), not
    detected from data. A breakout counts only when the simulated close
    finishes above the fixed level for confirm_bars consecutive bars within
    the horizon, sharing the same bootstrapped path set as the other
    estimates. Descriptive statistics under a stated assumption — not a
    forecast or instruction.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["level_breakout_probability.v1"] = (
        "level_breakout_probability.v1"
    )
    method: Literal["bootstrap_monte_carlo"] = "bootstrap_monte_carlo"
    level_source: Literal["manual_supply_zone"] = "manual_supply_zone"
    level_price: Decimal = Field(gt=0)
    horizon_bars: int = Field(ge=1)
    confirm_bars: int = Field(ge=1)
    paths: int = Field(ge=1)
    probability_pct: Decimal
    return_sample_bars: int = Field(ge=1)


class MaCrossoverThresholds(BaseModel):
    """Deterministic structure-maintenance levels for the next completed bars.

    Each value is the minimum next-bar close that keeps the stated MA
    condition true — factual indicator arithmetic, not a trade instruction.
    The projection assumes each future close lands exactly on the threshold
    (boundary path), which is the most conservative hold scenario.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["ma_crossover_thresholds.v1"] = "ma_crossover_thresholds.v1"
    basis: Literal["cross_hold", "convergence_hold"]
    convergence_min_close: Decimal | None = None
    cross_min_close: Decimal | None = None
    sma50_hold_min_close: Decimal | None = None
    vwma100_hold_min_close: Decimal | None = None
    structure_projection: tuple[ThresholdProjectionPoint, ...] = ()
    cross_probability: CrossProbabilityEstimate | None = None
    breakout_probability: BreakoutProbabilityEstimate | None = None
    level_breakout_probability: LevelBreakoutProbabilityEstimate | None = None


class MaCrossoverEvidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["ma_crossover_evidence.v1"] = "ma_crossover_evidence.v1"
    provider: str = Field(min_length=1, max_length=24)
    provider_symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=16)
    decision_time_exchange: datetime
    data_status: EvidenceDataStatus
    bar_count: int = Field(ge=0)
    last_bar_time_exchange: datetime | None = None
    close: Decimal | None = None
    volume: Decimal | None = Field(default=None, ge=0)
    sma_50: IndicatorMeasurement
    sma_200: IndicatorMeasurement
    vwma_100: IndicatorMeasurement
    sma_50_to_sma_200_gap_pct: Decimal | None = None
    gap_trend: GapTrend | None = None
    thresholds: MaCrossoverThresholds | None = None
    null_reasons: tuple[str, ...] = Field(default_factory=tuple)


class CaptureCreate(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    screenshot_data_url: str = Field(
        min_length=32,
        max_length=MAX_SCREENSHOT_DATA_URL_LENGTH,
    )
    extracted: ExtractedMetadata
    confirmed: ConfirmedMetadata
    setup: Setup = Setup.MA_CROSSOVER
    hypothesis: Hypothesis = Hypothesis.UNCERTAIN
    decision_note: str = Field(default="", max_length=2000)
    decision: Decision | None = None
    notes: str = Field(default="", max_length=2000)
    warnings: tuple[WarningCode, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_decision_time_exchange(self) -> Self:
        value = self.confirmed.decision_time_exchange
        try:
            decision_time = datetime.fromisoformat(value)
        except ValueError as exc:
            raise PydanticCustomError(
                INVALID_DECISION_TIME_CODE,
                INVALID_DECISION_TIME_MESSAGE,
            ) from exc
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise PydanticCustomError(
                MISSING_DECISION_TIME_TZ_CODE,
                MISSING_DECISION_TIME_TZ_MESSAGE,
            )
        fields = self.model_fields_set
        new_fields = {"setup", "hypothesis", "decision_note"}
        legacy_fields = {"decision", "notes"}
        new_variant = new_fields.issubset(fields) and not fields.intersection(
            legacy_fields,
        )
        legacy_variant = (
            "decision" in fields
            and self.decision is not None
            and not fields.intersection(new_fields)
        )
        if not (new_variant or legacy_variant):
            raise PydanticCustomError(
                INVALID_CAPTURE_PAYLOAD_VARIANT_CODE,
                INVALID_CAPTURE_PAYLOAD_VARIANT_MESSAGE,
            )
        return self

    @property
    def effective_decision_note(self) -> str:
        return self.decision_note or self.notes


class CaptureRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: CaptureId
    created_at: datetime
    screenshot_sha256: str
    screenshot_path: str
    extracted: ExtractedMetadata
    confirmed: ConfirmedMetadata
    setup: Setup = Setup.MA_CROSSOVER
    hypothesis: Hypothesis = Hypothesis.UNCERTAIN
    decision_note: str = Field(default="", max_length=2000)
    decision: Decision | None = None
    notes: str = Field(default="", max_length=2000)
    warnings: tuple[WarningCode, ...]

    @property
    def effective_decision_note(self) -> str:
        return self.decision_note or self.notes


class CaptureResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    capture: CaptureRecord


class CaptureDetailResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    capture: CaptureRecord
    score_status: str
    ai_review_status: str


class CaptureListResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    captures: tuple[CaptureRecord, ...]


class HealthResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: str = "ok"
    service: str = "tradingview-fractal-replay-backend"
    version: str = "dev"
    checks: dict[str, str]
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    session_id: str = "local-default"
    label: str = "Local Replay Journal"
    provider_required_warnings: tuple[WarningCode, ...] = (
        WarningCode.PROVIDER_SYMBOL_UNCONFIRMED,
        WarningCode.PRICE_BASIS_UNVERIFIED,
    )


class ErrorResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    detail: str
