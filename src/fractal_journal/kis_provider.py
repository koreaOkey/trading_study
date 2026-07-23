from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2

from fractal_journal.kis_auth import (
    AccessToken,
    KisCredentials,
    create_kis_client,
    get_access_token,
    invalidate_token_cache,
)
from fractal_journal.kis_daily_history import (
    DAILY_TIMEFRAME,
    KisDailyPageFetcher,
    collect_daily_bars,
)
from fractal_journal.kis_history import (
    KisHistoryPageFetcher,
    collect_historical_bars,
    default_history_throttle,
)
from fractal_journal.kis_models import (
    KisBar,
    KisQuoteResponse,
    parse_kis_quote_response,
    to_ohlcv_bar,
)
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvBar,
)
from fractal_journal.schemas import WarningCode

__all__ = [
    "KisBar",
    "KisHistoryPageFetcher",
    "KisOhlcvProvider",
    "KisQuoteResponse",
    "collect_historical_bars",
]

SEOUL = ZoneInfo("Asia/Seoul")
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
MINIMUM_COMPLETE_BARS = 30
INVALID_ACCESS_TOKEN_MESSAGE_CODES = frozenset({"EGW00123"})


@dataclass(frozen=True, slots=True)
class KisOhlcvProvider:
    credentials: KisCredentials
    token_cache_path: Path
    base_url: str = KIS_BASE_URL
    history_throttle: Callable[[], None] = default_history_throttle

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
            if _is_invalid_access_token(response):
                invalidate_token_cache(self.token_cache_path)
                token = get_access_token(
                    client,
                    self.credentials,
                    self.token_cache_path,
                    force_refresh=True,
                )
                response = _fetch_historical(
                    client,
                    token,
                    self.credentials,
                    request,
                    request_time,
                )
        return _to_window(request, request_time, response)

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        with create_kis_client(self.base_url) as client:
            result = self._collect_historical_bars(client, request)
            if not _history_has_invalid_access_token(result):
                return result
            invalidate_token_cache(self.token_cache_path)
            return self._collect_historical_bars(
                client,
                request,
                force_refresh=True,
            )

    def _collect_historical_bars(
        self,
        client: httpx2.Client,
        request: HistoricalBarsRequest,
        *,
        force_refresh: bool = False,
    ) -> HistoricalBarsResult:
        token = get_access_token(
            client,
            self.credentials,
            self.token_cache_path,
            force_refresh=force_refresh,
        )
        if request.timeframe == DAILY_TIMEFRAME:
            fetch_daily_page = KisDailyPageFetcher(
                client=client,
                token=token,
                credentials=self.credentials,
                request=request,
            )
            return collect_daily_bars(
                request,
                fetch_daily_page,
                self.history_throttle,
            )
        fetch_page = KisHistoryPageFetcher(
            client=client,
            token=token,
            credentials=self.credentials,
            request=request,
        )
        return collect_historical_bars(
            request,
            fetch_page,
            self.history_throttle,
        )


def _history_has_invalid_access_token(result: HistoricalBarsResult) -> bool:
    return any(
        code in INVALID_ACCESS_TOKEN_MESSAGE_CODES
        for code in result.provenance.api_message_codes
    )


def _is_invalid_access_token(response: KisQuoteResponse) -> bool:
    return (
        response.rt_cd != "0"
        and response.msg_cd in INVALID_ACCESS_TOKEN_MESSAGE_CODES
    )


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
    return parse_kis_quote_response(response)


def _to_window(
    request: MinuteWindowRequest,
    request_time: datetime,
    response: KisQuoteResponse,
) -> MinuteWindowResult:
    bars = tuple(
        sorted(
            (to_ohlcv_bar(bar) for bar in response.output2),
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
