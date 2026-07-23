from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

import httpx2

from fractal_journal.kis_auth import AccessToken, KisCredentials
from fractal_journal.kis_history import RATE_LIMIT_MESSAGE_CODE, history_status
from fractal_journal.kis_models import (
    KisDailyChartResponse,
    daily_bar_to_ohlcv,
    parse_kis_daily_response,
)
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalProvenance,
    HistoricalStopReason,
    OhlcvBar,
)

SEOUL = ZoneInfo("Asia/Seoul")
DAILY_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
DAILY_TR_ID = "FHKST03010100"
DAILY_TIMEFRAME = "1D"
DAILY_TIMEFRAME_MINUTES = 1440
DAILY_SESSION_CLOSE = time(15, 30)
# The daily chart endpoint returns at most ~100 rows per call; 140 calendar days
# covers fewer trading days than that cap, so one page never truncates silently.
DAILY_PAGE_SPAN_DAYS = 140
# "0" requests adjusted prices so SMA/VWMA windows spanning corporate actions
# stay comparable; the stored price basis remains provenance, not verification.
DAILY_ADJUSTED_PRICE_FLAG = "0"
DAILY_PRICE_BASIS = "kis_daily_adjusted_requested_unverified"


@dataclass(frozen=True, slots=True)
class KisDailyPageFetcher:
    client: httpx2.Client
    token: AccessToken
    credentials: KisCredentials
    request: HistoricalBarsRequest

    def __call__(self, start_date: date, end_date: date) -> KisDailyChartResponse:
        response = self.client.get(
            DAILY_ENDPOINT,
            headers={
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.token}",
                "appkey": self.credentials.app_key,
                "appsecret": self.credentials.app_secret,
                "tr_id": DAILY_TR_ID,
            },
            params={
                "FID_COND_MRKT_DIV_CODE": self.request.market_div_code,
                "FID_INPUT_ISCD": self.request.provider_symbol,
                "FID_INPUT_DATE_1": start_date.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": DAILY_ADJUSTED_PRICE_FLAG,
            },
        )
        return parse_kis_daily_response(response)


def collect_daily_bars(
    request: HistoricalBarsRequest,
    fetch_page: Callable[[date, date], KisDailyChartResponse],
    throttle: Callable[[], None],
) -> HistoricalBarsResult:
    decision_utc = request.decision_time_exchange.astimezone(UTC)
    end_cursor = request.decision_time_exchange.astimezone(SEOUL).date()
    last_cursor: datetime | None = None
    daily_bars: dict[datetime, OhlcvBar] = {}
    response_payloads: list[str] = []
    api_codes: list[str] = []
    raw_bar_count = 0
    future_bars_filtered = 0
    stop_reason = HistoricalStopReason.PAGE_CAP_REACHED

    for page_index in range(request.max_pages):
        page_start = end_cursor - timedelta(days=DAILY_PAGE_SPAN_DAYS - 1)
        last_cursor = datetime.combine(end_cursor, DAILY_SESSION_CLOSE, tzinfo=SEOUL)
        response = fetch_page(page_start, end_cursor)
        response_payloads.append(response.model_dump_json())
        api_codes.append(response.msg_cd)
        raw_bar_count += len(response.output2)
        if response.rt_cd != "0":
            stop_reason = (
                HistoricalStopReason.RATE_LIMITED
                if response.msg_cd == RATE_LIMIT_MESSAGE_CODE
                else HistoricalStopReason.API_ERROR
            )
            break
        page_bars = tuple(
            daily_bar_to_ohlcv(bar)
            for bar in response.output2
            if bar.stck_bsop_date
        )
        if not page_bars:
            stop_reason = HistoricalStopReason.EMPTY_PAGE
            break

        # A daily bar becomes evidence at its session close, so an intraday
        # decision time excludes that date's still-forming bar.
        eligible_bars = tuple(
            bar for bar in page_bars if bar.time_utc <= decision_utc
        )
        future_bars_filtered += len(page_bars) - len(eligible_bars)
        for bar in eligible_bars:
            _ = daily_bars.setdefault(bar.time_utc, bar)
        if len(daily_bars) >= request.target_bars:
            stop_reason = HistoricalStopReason.TARGET_REACHED
            break

        earliest_date = min(
            bar.time_utc.astimezone(SEOUL).date() for bar in page_bars
        )
        next_cursor = earliest_date - timedelta(days=1)
        if next_cursor >= end_cursor:
            stop_reason = HistoricalStopReason.NO_PROGRESS
            break
        end_cursor = next_cursor
        if page_index + 1 < request.max_pages:
            throttle()

    bars = tuple(
        bar for _, bar in sorted(daily_bars.items())
    )
    raw_hash = sha256("\n".join(response_payloads).encode()).hexdigest()
    return HistoricalBarsResult(
        provider="kis",
        status=history_status(stop_reason, bars, request.target_bars),
        bars=bars,
        provenance=HistoricalProvenance(
            endpoint=DAILY_ENDPOINT,
            tr_id=DAILY_TR_ID,
            request_end_exchange=request.decision_time_exchange,
            source_timeframe_minutes=DAILY_TIMEFRAME_MINUTES,
            aggregated_timeframe_minutes=DAILY_TIMEFRAME_MINUTES,
            target_bars=request.target_bars,
            page_count=len(response_payloads),
            raw_bar_count=raw_bar_count,
            unique_minute_bar_count=len(daily_bars),
            future_bars_filtered=future_bars_filtered,
            price_basis=DAILY_PRICE_BASIS,
            api_message_codes=tuple(api_codes),
            last_cursor_exchange=last_cursor,
            raw_response_sha256=raw_hash,
            stop_reason=stop_reason,
        ),
    )
