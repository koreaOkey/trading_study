"""Registered TradingView chart-export bar series.

After a replay session ends the user exports the chart as CSV (TradingView's
official "Export chart data" feature) and registers it here, keyed by
symbol x timeframe. The series then serves two consumers with a strict
temporal split:

- review evidence uses only bars at/before a capture's decision time
  (RegisteredBarsProvider enforces this cut, so lookahead cannot leak);
- outcome scoring reads bars after the decision time from the normalized
  CSV file directly (trading-ta-knowledge's scorer).

Series files are normalized CSV (date,open,high,low,close,volume with
exchange-local ISO dates) so the scoring tooling can consume them as-is.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from secrets import token_hex
from typing import TYPE_CHECKING, ClassVar
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    HistoricalProvenance,
    HistoricalStopReason,
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvBar,
    OhlcvProvider,
)

SEOUL = ZoneInfo("Asia/Seoul")
SERIES_DIRNAME = "bar_series"
SERIES_ENDPOINT = "registered://tradingview-chart-export"
SERIES_TR_ID = "TV_CSV_EXPORT"
CSV_FIELDNAMES = ("date", "open", "high", "low", "close", "volume")
MAX_CSV_TEXT_LENGTH = 8_000_000

_TIME_COLUMNS = ("time", "date", "datetime")
_VOLUME_COLUMNS = ("volume", "vol")
_ALLOWED_KEY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


class BarSeriesError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason


class BarSeriesCoverage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    bar_count: int
    first_time_exchange: str
    last_time_exchange: str


class BarSeriesRegisterRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=16)
    csv_text: str = Field(min_length=1, max_length=MAX_CSV_TEXT_LENGTH)


def _validate_key(value: str, label: str) -> str:
    if not value or not set(value) <= _ALLOWED_KEY_CHARS:
        raise BarSeriesError(reason=f"invalid_{label}")
    return value


def _parse_time(raw: str) -> datetime:
    text = raw.strip()
    if not text:
        raise BarSeriesError(reason="empty_time_value")
    if text.replace(".", "", 1).isdecimal():
        return datetime.fromtimestamp(float(text), tz=UTC)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BarSeriesError(reason=f"unparseable_time:{text[:32]}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SEOUL)
    return parsed.astimezone(UTC)


def _parse_decimal(raw: str, column: str) -> Decimal:
    try:
        return Decimal(raw.strip())
    except InvalidOperation as exc:
        raise BarSeriesError(reason=f"invalid_number:{column}") from exc


def _resolve_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {name.lower().strip(): name for name in fieldnames}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def parse_tradingview_csv(csv_text: str) -> tuple[OhlcvBar, ...]:
    """Parse a TradingView chart export into ascending, deduplicated bars.

    Accepts unix-second or ISO timestamps (naive values are assumed KST).
    Indicator columns are ignored — evidence indicators are recomputed from
    OHLCV so every consumer shares one definition. Rows without a complete
    OHLC set are skipped (e.g. blank indicator warm-up rows).
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    time_column = _resolve_column(fieldnames, _TIME_COLUMNS)
    ohlc_columns = {
        key: _resolve_column(fieldnames, (key,))
        for key in ("open", "high", "low", "close")
    }
    if time_column is None or any(column is None for column in ohlc_columns.values()):
        raise BarSeriesError(reason="missing_required_columns")
    volume_column = _resolve_column(fieldnames, _VOLUME_COLUMNS)

    bars: dict[datetime, OhlcvBar] = {}
    for row in reader:
        raw_values = {
            key: (row.get(column) or "").strip()
            for key, column in ohlc_columns.items()
        }
        if not all(raw_values.values()):
            continue
        time_utc = _parse_time(row.get(time_column) or "")
        raw_volume = (row.get(volume_column) or "").strip() if volume_column else ""
        volume = int(_parse_decimal(raw_volume, "volume")) if raw_volume else 0
        bars[time_utc] = OhlcvBar(
            time_utc=time_utc,
            time_exchange=time_utc.astimezone(SEOUL).isoformat(),
            open=_parse_decimal(raw_values["open"], "open"),
            high=_parse_decimal(raw_values["high"], "high"),
            low=_parse_decimal(raw_values["low"], "low"),
            close=_parse_decimal(raw_values["close"], "close"),
            volume=volume,
        )
    if not bars:
        raise BarSeriesError(reason="no_bars_parsed")
    return tuple(bars[key] for key in sorted(bars))


class FileBarSeriesStore:
    def __init__(self, data_dir: Path, dirname: str = SERIES_DIRNAME) -> None:
        self._series_dir: Path = data_dir / dirname

    def series_path(self, symbol: str, timeframe: str) -> Path:
        symbol = _validate_key(symbol, "symbol")
        timeframe = _validate_key(timeframe, "timeframe")
        return self._series_dir / f"{symbol}_{timeframe}.csv"

    def register(
        self,
        symbol: str,
        timeframe: str,
        new_bars: tuple[OhlcvBar, ...],
    ) -> BarSeriesCoverage:
        merged = {bar.time_utc: bar for bar in self.load(symbol, timeframe) or ()}
        for bar in new_bars:
            merged[bar.time_utc] = bar
        ordered = tuple(merged[key] for key in sorted(merged))

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_FIELDNAMES)
        for bar in ordered:
            local = bar.time_utc.astimezone(SEOUL)
            writer.writerow(
                [
                    local.strftime("%Y-%m-%dT%H:%M:%S"),
                    str(bar.open),
                    str(bar.high),
                    str(bar.low),
                    str(bar.close),
                    bar.volume,
                ]
            )
        path = self.series_path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{token_hex(6)}.tmp")
        _ = temporary.write_text(buffer.getvalue(), encoding="utf-8")
        _ = temporary.replace(path)
        return self._coverage_from_bars(symbol, timeframe, ordered)

    def load(self, symbol: str, timeframe: str) -> tuple[OhlcvBar, ...] | None:
        path = self.series_path(symbol, timeframe)
        if not path.exists():
            return None
        reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
        bars: list[OhlcvBar] = []
        for row in reader:
            time_utc = _parse_time(row["date"])
            bars.append(
                OhlcvBar(
                    time_utc=time_utc,
                    time_exchange=time_utc.astimezone(SEOUL).isoformat(),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=int(row["volume"]),
                )
            )
        return tuple(sorted(bars, key=lambda bar: bar.time_utc))

    def coverage(self, symbol: str, timeframe: str) -> BarSeriesCoverage | None:
        bars = self.load(symbol, timeframe)
        if not bars:
            return None
        return self._coverage_from_bars(symbol, timeframe, bars)

    def _coverage_from_bars(
        self,
        symbol: str,
        timeframe: str,
        bars: tuple[OhlcvBar, ...],
    ) -> BarSeriesCoverage:
        return BarSeriesCoverage(
            symbol=symbol,
            timeframe=timeframe,
            bar_count=len(bars),
            first_time_exchange=bars[0].time_exchange,
            last_time_exchange=bars[-1].time_exchange,
        )


@dataclass(frozen=True, slots=True)
class RegisteredBarsProvider:
    """OhlcvProvider that serves registered series and falls back otherwise.

    The decision-time cut lives here: only bars at/before the requested
    decision time are ever returned, regardless of how far the registered
    series extends into the (post-decision) future.
    """

    series_store: FileBarSeriesStore
    fallback: OhlcvProvider

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        return self.fallback.fetch_minute_window(request)

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        try:
            series = self.series_store.load(request.provider_symbol, request.timeframe)
        except BarSeriesError:
            series = None
        if not series:
            return self.fallback.fetch_historical_bars(request)

        cutoff = request.decision_time_exchange.astimezone(UTC)
        eligible = tuple(bar for bar in series if bar.time_utc <= cutoff)
        if not eligible:
            return self.fallback.fetch_historical_bars(request)

        selected = eligible[-request.target_bars :]
        complete = len(selected) >= request.target_bars
        digest = sha256(
            "\n".join(bar.time_exchange for bar in selected).encode("utf-8"),
        ).hexdigest()
        status = (
            HistoricalDataStatus.OK if complete else HistoricalDataStatus.PARTIAL_DATA
        )
        return HistoricalBarsResult(
            provider="tradingview_csv",
            status=status,
            bars=selected,
            provenance=HistoricalProvenance(
                endpoint=SERIES_ENDPOINT,
                tr_id=SERIES_TR_ID,
                request_end_exchange=request.decision_time_exchange,
                aggregated_timeframe_minutes=None,
                target_bars=request.target_bars,
                page_count=1,
                raw_bar_count=len(series),
                unique_minute_bar_count=0,
                future_bars_filtered=len(series) - len(eligible),
                price_basis="tradingview_chart_export",
                api_message_codes=(),
                last_cursor_exchange=None,
                raw_response_sha256=digest,
                stop_reason=(
                    HistoricalStopReason.TARGET_REACHED
                    if complete
                    else HistoricalStopReason.EMPTY_PAGE
                ),
            ),
        )
