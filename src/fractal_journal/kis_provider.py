from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel, ConfigDict

from fractal_journal.kis_auth import (
    AccessToken,
    KisCredentials,
    create_kis_client,
    get_access_token,
)
from fractal_journal.provider import MinuteWindowRequest, MinuteWindowResult, OhlcvBar
from fractal_journal.schemas import WarningCode

SEOUL = ZoneInfo("Asia/Seoul")
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
MINIMUM_COMPLETE_BARS = 30


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


@dataclass(frozen=True, slots=True)
class KisOhlcvProvider:
    credentials: KisCredentials
    token_cache_path: Path
    base_url: str = KIS_BASE_URL

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        decision_time = datetime.fromisoformat(request.decision_time_exchange)
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=SEOUL)
        request_time = decision_time + timedelta(minutes=request.forward_minutes)
        with create_kis_client(self.base_url) as client:
            token = get_access_token(client, self.credentials, self.token_cache_path)
            response = _fetch_historical(
                client,
                token,
                self.credentials,
                request,
                request_time,
            )
        return _to_window(request, request_time, response)


def _fetch_historical(
    client: httpx2.Client,
    token: AccessToken,
    credentials: KisCredentials,
    request: MinuteWindowRequest,
    request_time: datetime,
) -> KisQuoteResponse:
    response = client.get(
        "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
        headers={
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": credentials.app_key,
            "appsecret": credentials.app_secret,
            "tr_id": "FHKST03010230",
        },
        params={
            "FID_COND_MRKT_DIV_CODE": request.market_div_code,
            "FID_INPUT_ISCD": request.provider_symbol,
            "FID_INPUT_HOUR_1": request_time.strftime("%H%M%S"),
            "FID_INPUT_DATE_1": request_time.strftime("%Y%m%d"),
            "FID_PW_DATA_INCU_YN": "N",
            "FID_FAKE_TICK_INCU_YN": "",
        },
    )
    return KisQuoteResponse.model_validate(response.json())


def _to_window(
    request: MinuteWindowRequest,
    request_time: datetime,
    response: KisQuoteResponse,
) -> MinuteWindowResult:
    bars = tuple(
        sorted(
            (_to_bar(bar) for bar in response.output2),
            key=lambda bar: bar.time_utc,
        ),
    )
    return MinuteWindowResult(
        endpoint="/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
        tr_id="FHKST03010230",
        request_date=request_time.strftime("%Y%m%d"),
        request_hour=request_time.strftime("%H%M%S"),
        price_basis=request.price_basis_policy,
        session_state=_session_state(request_time, bars),
        data_status=_data_status(response, bars),
        raw_response_sha256=sha256(response.model_dump_json().encode("utf-8")).hexdigest(),
        bars=bars,
        warnings=_warnings(request_time, bars, response),
    )


def _to_bar(bar: KisBar) -> OhlcvBar:
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


def _warnings(
    request_time: datetime,
    bars: tuple[OhlcvBar, ...],
    response: KisQuoteResponse,
) -> tuple[WarningCode, ...]:
    warnings: list[WarningCode] = [WarningCode.PRICE_BASIS_UNVERIFIED]
    if response.msg_cd == "EGW00201":
        warnings.append(WarningCode.RETRY_EXHAUSTED)
    if not bars:
        warnings.append(WarningCode.EMPTY_DATA)
        return tuple(warnings)
    returned_date = datetime.fromisoformat(bars[-1].time_exchange).strftime("%Y%m%d")
    if returned_date != request_time.strftime("%Y%m%d"):
        warnings.append(WarningCode.REQUEST_DATE_MISMATCH)
    if request_time.strftime("%H%M") > "1530":
        warnings.append(WarningCode.AFTER_REGULAR_CLOSE_CLAMPED)
    return tuple(warnings)


def _session_state(request_time: datetime, bars: tuple[OhlcvBar, ...]) -> str:
    if not bars:
        return "depth_exhausted_empty"
    if request_time.strftime("%H%M") > "1530":
        return "after_regular_close_clamped"
    if request_time.strftime("%H%M") >= "1520":
        return "regular_close_edge"
    return "regular"


def _data_status(response: KisQuoteResponse, bars: tuple[OhlcvBar, ...]) -> str:
    if response.rt_cd != "0":
        return "api_error"
    if not bars:
        return "empty_data"
    if len(bars) < MINIMUM_COMPLETE_BARS:
        return "partial_data"
    return "ok"
