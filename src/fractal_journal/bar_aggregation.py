from datetime import UTC, datetime, time, timedelta

from fractal_journal.provider import OhlcvBar

REGULAR_SESSION_OPEN = time(9, 0)
REGULAR_SESSION_CLOSE = time(15, 30)


def aggregate_minute_bars(
    bars: tuple[OhlcvBar, ...],
    timeframe_minutes: int,
) -> tuple[OhlcvBar, ...]:
    buckets: dict[datetime, list[OhlcvBar]] = {}
    for bar in sorted(bars, key=lambda candidate: candidate.time_utc):
        exchange_time = datetime.fromisoformat(bar.time_exchange)
        exchange_clock = exchange_time.time().replace(tzinfo=None)
        if not REGULAR_SESSION_OPEN <= exchange_clock <= REGULAR_SESSION_CLOSE:
            continue
        session_start = exchange_time.replace(hour=9, minute=0, second=0, microsecond=0)
        elapsed_minutes = int((exchange_time - session_start).total_seconds() // 60)
        bucket_start = session_start + timedelta(
            minutes=(elapsed_minutes // timeframe_minutes) * timeframe_minutes,
        )
        buckets.setdefault(bucket_start, []).append(bar)

    return tuple(
        _aggregate_bucket(bucket_start, bucket_bars)
        for bucket_start, bucket_bars in sorted(buckets.items())
    )


def _aggregate_bucket(
    bucket_start: datetime,
    bars: list[OhlcvBar],
) -> OhlcvBar:
    ordered = sorted(bars, key=lambda candidate: candidate.time_utc)
    return OhlcvBar(
        time_utc=bucket_start.astimezone(UTC),
        time_exchange=bucket_start.isoformat(),
        open=ordered[0].open,
        high=max(bar.high for bar in ordered),
        low=min(bar.low for bar in ordered),
        close=ordered[-1].close,
        volume=sum(bar.volume for bar in ordered),
    )
