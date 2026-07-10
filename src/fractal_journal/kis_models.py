from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel, ConfigDict

from fractal_journal.provider import OhlcvBar

SEOUL = ZoneInfo("Asia/Seoul")
REDIRECT_REJECTED_MESSAGE_CODE = "KIS_REDIRECT_REJECTED"
HTTP_REDIRECT_MIN = 300
HTTP_REDIRECT_MAX = 400


class KisBar(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    stck_bsop_date: str
    stck_cntg_hour: str
    stck_oprc: str | None = None
    stck_hgpr: str | None = None
    stck_lwpr: str | None = None
    stck_prpr: str | None = None
    cntg_vol: str | None = None


class KisQuoteResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rt_cd: str
    msg_cd: str
    msg1: str
    output2: tuple[KisBar, ...] = ()


def parse_kis_quote_response(response: httpx2.Response) -> KisQuoteResponse:
    if HTTP_REDIRECT_MIN <= response.status_code < HTTP_REDIRECT_MAX:
        return KisQuoteResponse(
            rt_cd="1",
            msg_cd=REDIRECT_REJECTED_MESSAGE_CODE,
            msg1="redirect_rejected",
        )
    return KisQuoteResponse.model_validate(response.json())


def to_ohlcv_bar(bar: KisBar) -> OhlcvBar:
    exchange_time = datetime.strptime(
        f"{bar.stck_bsop_date}{bar.stck_cntg_hour}",
        "%Y%m%d%H%M%S",
    ).replace(tzinfo=SEOUL)
    close = Decimal(bar.stck_prpr or "0")
    return OhlcvBar(
        time_utc=exchange_time.astimezone(UTC),
        time_exchange=exchange_time.isoformat(),
        open=Decimal(bar.stck_oprc or close),
        high=Decimal(bar.stck_hgpr or close),
        low=Decimal(bar.stck_lwpr or close),
        close=close,
        volume=int(bar.cntg_vol or "0"),
    )
