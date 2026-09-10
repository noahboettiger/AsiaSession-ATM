"""Bar primitives and 1-minute to N-minute aggregation.

Buckets are floored on minute-of-hour. Every US Eastern UTC offset is a whole
number of hours, so flooring in UTC gives the same bucket boundaries as flooring
on the New York clock for any timeframe that divides evenly into an hour.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Bar:
    ts: datetime  # UTC, bar OPEN time
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    minutes: int = 1

    @property
    def close_ts(self) -> datetime:
        return self.ts + timedelta(minutes=self.minutes)


class TimeframeAggregator:
    """Folds 1-minute bars into `minutes`-minute bars."""

    def __init__(self, minutes: int) -> None:
        self.minutes = minutes
        self._working: Bar | None = None
        self._key: datetime | None = None

    def _bucket(self, ts: datetime) -> datetime:
        floored = ts.replace(second=0, microsecond=0)
        return floored - timedelta(minutes=floored.minute % self.minutes)

    def _flush(self) -> Bar:
        bar = self._working
        assert bar is not None
        self._working = None
        self._key = None
        return bar

    def push(self, bar: Bar) -> list[Bar]:
        """Feed one 1-minute bar. Returns any bars completed by it."""
        if bar.minutes != 1:
            raise ValueError("aggregator consumes 1-minute bars only")

        key = self._bucket(bar.ts)
        completed: list[Bar] = []

        if self._key is not None and key != self._key:
            completed.append(self._flush())

        if self._working is None:
            self._key = key
            self._working = replace(bar, ts=key, minutes=self.minutes)
        else:
            w = self._working
            self._working = replace(
                w,
                high=max(w.high, bar.high),
                low=min(w.low, bar.low),
                close=bar.close,
                volume=w.volume + bar.volume,
            )

        # Complete as soon as the bar covering the bucket's final minute lands,
        # rather than waiting for the next bucket to open.
        if bar.close_ts >= key + timedelta(minutes=self.minutes):
            completed.append(self._flush())

        return completed
