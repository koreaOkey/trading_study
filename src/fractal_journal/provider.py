from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fractal_journal.schemas import WarningCode

SEOUL = ZoneInfo("Asia/Seoul")


class OhlcvBar(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    time_utc: datetime
    time_exchange: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class MinuteWindowRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    provider_symbol: str = Field(min_length=1, max_length=32)
    market_div_code: str = "J"
    decision_time_exchange: str
    lookback_minutes: int = Field(default=60, ge=1, le=240)
    forward_minutes: int = Field(default=30, ge=1, le=240)
    price_basis_policy: str = "unknown_unadjusted_assumed"


class MinuteWindowResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    provider: str = "kis"
    endpoint: str
    tr_id: str
    request_date: str
    request_hour: str
    price_basis: str
    session_state: str
    data_status: str
    source_order: str = "ascending"
    raw_response_sha256: str
    bars: tuple[OhlcvBar, ...]
    warnings: tuple[WarningCode, ...]


class HistoricalDataStatus(StrEnum):
    OK = "ok"
    PARTIAL_DATA = "partial_data"
    EMPTY_DATA = "empty_data"
    API_ERROR = "api_error"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED_TIMEFRAME = "unsupported_timeframe"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class HistoricalStopReason(StrEnum):
    TARGET_REACHED = "target_reached"
    PAGE_CAP_REACHED = "page_cap_reached"
    NO_PROGRESS = "no_progress"
    EMPTY_PAGE = "empty_page"
    API_ERROR = "api_error"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED_TIMEFRAME = "unsupported_timeframe"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class NaiveDecisionTimeError(ValueError):
    def __init__(self) -> None:
        super().__init__("decision_time_exchange_requires_timezone")


class HistoricalBarsRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    provider_symbol: str = Field(min_length=1, max_length=32)
    market_div_code: str = "J"
    decision_time_exchange: datetime
    timeframe: str = Field(min_length=1, max_length=8)
    target_bars: int = Field(default=201, ge=201, le=5000)
    max_pages: int = Field(default=256, ge=1, le=1000)
    price_basis_policy: str = "unknown_unadjusted_assumed"

    @field_validator("decision_time_exchange")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise NaiveDecisionTimeError
        return value


class HistoricalProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    endpoint: str
    tr_id: str
    request_end_exchange: datetime
    source_timeframe_minutes: int = 1
    aggregated_timeframe_minutes: int | None
    target_bars: int
    page_count: int
    raw_bar_count: int
    unique_minute_bar_count: int
    future_bars_filtered: int
    price_basis: str
    api_message_codes: tuple[str, ...]
    last_cursor_exchange: datetime | None
    raw_response_sha256: str
    stop_reason: HistoricalStopReason


class HistoricalBarsResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    provider: str
    status: HistoricalDataStatus
    bars: tuple[OhlcvBar, ...]
    provenance: HistoricalProvenance


class OhlcvProvider(Protocol):
    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        ...

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        ...


@dataclass(frozen=True, slots=True)
class FixtureOhlcvProvider:
    slope: Decimal = Decimal("0.15")

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        decision_time = datetime.fromisoformat(request.decision_time_exchange)
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=SEOUL)
        start = decision_time - timedelta(minutes=request.lookback_minutes)
        total = request.lookback_minutes + request.forward_minutes + 1
        bars = tuple(
            self._bar(start + timedelta(minutes=offset), offset)
            for offset in range(total)
        )
        warnings = (WarningCode.PRICE_BASIS_UNVERIFIED,)
        raw_hash = sha256(
            b64encode(request.model_dump_json().encode("utf-8")),
        ).hexdigest()
        return MinuteWindowResult(
            endpoint="fixture://kis/inquire-time-dailychartprice",
            tr_id="FHKST03010230",
            request_date=decision_time.strftime("%Y%m%d"),
            request_hour=decision_time.strftime("%H%M%S"),
            price_basis=request.price_basis_policy,
            session_state=_classify_session(decision_time),
            data_status="ok",
            raw_response_sha256=raw_hash,
            bars=bars,
            warnings=warnings,
        )

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        empty_hash = sha256(b"").hexdigest()
        return HistoricalBarsResult(
            provider="fixture",
            status=HistoricalDataStatus.PROVIDER_UNAVAILABLE,
            bars=(),
            provenance=HistoricalProvenance(
                endpoint="fixture://kis/inquire-time-dailychartprice",
                tr_id="FHKST03010230",
                request_end_exchange=request.decision_time_exchange,
                aggregated_timeframe_minutes=None,
                target_bars=request.target_bars,
                page_count=0,
                raw_bar_count=0,
                unique_minute_bar_count=0,
                future_bars_filtered=0,
                price_basis=request.price_basis_policy,
                api_message_codes=(),
                last_cursor_exchange=None,
                raw_response_sha256=empty_hash,
                stop_reason=HistoricalStopReason.PROVIDER_UNAVAILABLE,
            ),
        )

    def _bar(self, exchange_time: datetime, offset: int) -> OhlcvBar:
        base = Decimal(70000) + (Decimal(offset) * self.slope)
        return OhlcvBar(
            time_utc=exchange_time.astimezone(UTC),
            time_exchange=exchange_time.isoformat(),
            open=base,
            high=base + Decimal("1.2"),
            low=base - Decimal("0.8"),
            close=base + Decimal("0.4"),
            volume=1000 + offset,
        )


def _classify_session(exchange_time: datetime) -> str:
    hhmm = exchange_time.strftime("%H%M")
    if hhmm == "0900":
        return "regular_open_edge"
    if "1520" <= hhmm <= "1530":
        return "regular_close_edge"
    if hhmm > "1530":
        return "after_regular_close_clamped"
    return "regular"
