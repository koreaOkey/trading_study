"""Toss candle payloads normalized to OhlcvBar, mirroring kis_models.

Toss wraps every payload in a result/error envelope and reports failures
via HTTP status plus an error object, unlike KIS's rt_cd/msg_cd body codes.
parse_toss_candles_page flattens both shapes into one TossCandlesPage so the
collectors can branch on a single error_code/status_code pair.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus
from typing import ClassVar

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fractal_journal.provider import OhlcvBar

HTTP_REDIRECT_MIN = 300
HTTP_REDIRECT_MAX = 400
REDIRECT_REJECTED_ERROR_CODE = "redirect_rejected"
INVALID_BODY_ERROR_CODE = "invalid_response_body"


class TossCandle(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, populate_by_name=True)

    timestamp: str
    open_price: Decimal | None = Field(default=None, alias="openPrice")
    high_price: Decimal | None = Field(default=None, alias="highPrice")
    low_price: Decimal | None = Field(default=None, alias="lowPrice")
    close_price: Decimal | None = Field(default=None, alias="closePrice")
    volume: Decimal | None = None
    currency: str | None = None


class TossCandlesResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, populate_by_name=True)

    candles: tuple[TossCandle, ...] = ()
    next_before: str | None = Field(default=None, alias="nextBefore")


class TossErrorDetail(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    code: str = "unknown"
    message: str | None = None


class TossCandlesEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    result: TossCandlesResult | None = None
    error: TossErrorDetail | None = None


class TossCandlesPage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status_code: int
    error_code: str | None = None
    candles: tuple[TossCandle, ...] = ()
    next_before: str | None = None


def parse_toss_candles_page(response: httpx2.Response) -> TossCandlesPage:
    if HTTP_REDIRECT_MIN <= response.status_code < HTTP_REDIRECT_MAX:
        return TossCandlesPage(
            status_code=response.status_code,
            error_code=REDIRECT_REJECTED_ERROR_CODE,
        )
    try:
        envelope = TossCandlesEnvelope.model_validate(response.json())
    except (json.JSONDecodeError, ValidationError):
        return TossCandlesPage(
            status_code=response.status_code,
            error_code=INVALID_BODY_ERROR_CODE,
        )
    if (
        envelope.error is not None
        or response.status_code != HTTPStatus.OK
        or envelope.result is None
    ):
        error_code = (
            envelope.error.code
            if envelope.error is not None
            else f"http_{response.status_code}"
        )
        return TossCandlesPage(
            status_code=response.status_code,
            error_code=error_code,
        )
    return TossCandlesPage(
        status_code=response.status_code,
        candles=envelope.result.candles,
        next_before=envelope.result.next_before,
    )


def to_ohlcv_bar(candle: TossCandle) -> OhlcvBar:
    exchange_time = datetime.fromisoformat(candle.timestamp)
    close = candle.close_price if candle.close_price is not None else Decimal(0)
    return OhlcvBar(
        time_utc=exchange_time.astimezone(UTC),
        time_exchange=exchange_time.isoformat(),
        open=candle.open_price if candle.open_price is not None else close,
        high=candle.high_price if candle.high_price is not None else close,
        low=candle.low_price if candle.low_price is not None else close,
        close=close,
        volume=int(candle.volume) if candle.volume is not None else 0,
    )


# Toss stamps daily candles at exchange-local midnight, but a daily bar only
# exists as evidence once its session has completed, so it is re-stamped at
# the regular-session close (15:30 in the candle's own timezone) to match the
# KIS daily convention and keep the intraday lookahead cut working.
def daily_bar_to_ohlcv(candle: TossCandle) -> OhlcvBar:
    stamped = datetime.fromisoformat(candle.timestamp)
    exchange_time = stamped.replace(hour=15, minute=30, second=0, microsecond=0)
    close = candle.close_price if candle.close_price is not None else Decimal(0)
    return OhlcvBar(
        time_utc=exchange_time.astimezone(UTC),
        time_exchange=exchange_time.isoformat(),
        open=candle.open_price if candle.open_price is not None else close,
        high=candle.high_price if candle.high_price is not None else close,
        low=candle.low_price if candle.low_price is not None else close,
        close=close,
        volume=int(candle.volume) if candle.volume is not None else 0,
    )
