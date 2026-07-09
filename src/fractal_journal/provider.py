from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import ClassVar, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

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


class OhlcvProvider(Protocol):
    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
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
