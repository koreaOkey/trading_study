"""Ordered OhlcvProvider chain: primary first, fall back on failure.

A provider "fails" either by raising a fetch-level error (network, token
issue, malformed payload) or by returning a non-OK result. The first OK
result short-circuits; when every provider degrades, the least-degraded
result wins (status rank, then bar count, then chain order), so a Toss
empty-retention response still yields KIS bars while a total outage still
surfaces a typed result instead of an exception.
"""

import json
from dataclasses import dataclass
from decimal import InvalidOperation

import httpx2
from pydantic import ValidationError

from fractal_journal.kis_auth import KisTokenIssueError
from fractal_journal.provider import (
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalDataStatus,
    MinuteWindowRequest,
    MinuteWindowResult,
    OhlcvProvider,
)
from fractal_journal.toss_auth import TossTokenIssueError

_PROVIDER_ERRORS = (
    httpx2.HTTPError,
    InvalidOperation,
    json.JSONDecodeError,
    KisTokenIssueError,
    TossTokenIssueError,
    ValidationError,
    ValueError,
)

_UNRANKED = 99

_HISTORICAL_STATUS_RANK = {
    HistoricalDataStatus.OK: 0,
    HistoricalDataStatus.PARTIAL_DATA: 1,
    HistoricalDataStatus.EMPTY_DATA: 2,
    HistoricalDataStatus.RATE_LIMITED: 3,
    HistoricalDataStatus.UNSUPPORTED_TIMEFRAME: 4,
    HistoricalDataStatus.API_ERROR: 5,
    HistoricalDataStatus.PROVIDER_UNAVAILABLE: 6,
}

_WINDOW_STATUS_RANK = {
    "ok": 0,
    "partial_data": 1,
    "empty_data": 2,
    "api_error": 3,
}


class EmptyProviderChainError(ValueError):
    def __init__(self) -> None:
        super().__init__("fallback_provider_chain_empty")


@dataclass(frozen=True, slots=True)
class FallbackOhlcvProvider:
    providers: tuple[OhlcvProvider, ...]

    def __post_init__(self) -> None:
        """Reject an empty chain at construction time."""
        if not self.providers:
            raise EmptyProviderChainError

    def fetch_minute_window(self, request: MinuteWindowRequest) -> MinuteWindowResult:
        results: list[MinuteWindowResult] = []
        failure: Exception | None = None
        for provider in self.providers:
            try:
                result = provider.fetch_minute_window(request)
            except _PROVIDER_ERRORS as exc:
                failure = exc
                continue
            if result.data_status == "ok":
                return result
            results.append(result)
        if results:
            return min(results, key=_window_quality_key)
        if failure is None:
            raise EmptyProviderChainError
        raise failure

    def fetch_historical_bars(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsResult:
        results: list[HistoricalBarsResult] = []
        failure: Exception | None = None
        for provider in self.providers:
            try:
                result = provider.fetch_historical_bars(request)
            except _PROVIDER_ERRORS as exc:
                failure = exc
                continue
            if result.status is HistoricalDataStatus.OK:
                return result
            results.append(result)
        if results:
            return min(results, key=_historical_quality_key)
        if failure is None:
            raise EmptyProviderChainError
        raise failure


def _historical_quality_key(result: HistoricalBarsResult) -> tuple[int, int]:
    rank = _HISTORICAL_STATUS_RANK.get(result.status, _UNRANKED)
    return (rank, -len(result.bars))


def _window_quality_key(result: MinuteWindowResult) -> tuple[int, int]:
    rank = _WINDOW_STATUS_RANK.get(result.data_status, _UNRANKED)
    return (rank, -len(result.bars))
