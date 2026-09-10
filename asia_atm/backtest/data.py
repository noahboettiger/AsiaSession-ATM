"""CSV loading for 1-minute MNQ bars.

Tolerant of the column names and timestamp formats the common futures data
vendors emit. Everything is normalized to UTC-aware `Bar` objects.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from ..bars import Bar

_TS_COLUMNS = ("timestamp", "datetime", "date_time", "time", "date", "ts")
_ALIASES = {
    "open": ("open", "o", "openprice"),
    "high": ("high", "h", "highprice"),
    "low": ("low", "l", "lowprice"),
    "close": ("close", "c", "closeprice", "last"),
    "volume": ("volume", "v", "vol"),
}


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _pick(header: list[str], names: tuple[str, ...]) -> str | None:
    lookup = {_norm(h): h for h in header}
    for candidate in names:
        if candidate in lookup:
            return lookup[candidate]
    return None


def parse_timestamp(raw: str, tz: ZoneInfo) -> datetime:
    text = raw.strip()
    if text.isdigit():
        value = int(text)
        if value >= 10**11:  # milliseconds
            value /= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)

    normalized = text.replace("Z", "+00:00").replace("/", "-")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def load_csv(path: str | Path, input_timezone: str = "America/New_York") -> list[Bar]:
    """Read a 1-minute bar CSV. Timestamps are bar OPEN times."""
    tz = ZoneInfo(input_timezone)
    bars: list[Bar] = []

    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header row")
        header = list(reader.fieldnames)

        date_col = _pick(header, ("date",))
        time_col = _pick(header, ("time",))
        split_ts = date_col is not None and time_col is not None
        ts_col = None if split_ts else _pick(header, _TS_COLUMNS)
        if ts_col is None and not split_ts:
            raise ValueError(f"{path}: no timestamp column found in {header}")

        cols = {}
        for field, names in _ALIASES.items():
            found = _pick(header, names)
            if found is None and field != "volume":
                raise ValueError(f"{path}: no '{field}' column found in {header}")
            cols[field] = found

        for row in reader:
            raw_ts = (
                f"{row[date_col]} {row[time_col]}" if split_ts else row[ts_col]
            )
            if not raw_ts or not raw_ts.strip():
                continue
            volume_col = cols["volume"]
            bars.append(
                Bar(
                    ts=parse_timestamp(raw_ts, tz),
                    open=float(row[cols["open"]]),
                    high=float(row[cols["high"]]),
                    low=float(row[cols["low"]]),
                    close=float(row[cols["close"]]),
                    volume=float(row[volume_col] or 0) if volume_col else 0.0,
                    minutes=1,
                )
            )

    bars.sort(key=lambda b: b.ts)
    return _dedupe(bars)


def _dedupe(bars: list[Bar]) -> list[Bar]:
    out: list[Bar] = []
    for bar in bars:
        if out and out[-1].ts == bar.ts:
            continue
        out.append(bar)
    return out


def iter_bars(bars: list[Bar]) -> Iterator[Bar]:
    yield from bars
