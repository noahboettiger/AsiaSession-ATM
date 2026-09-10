"""Synthetic bar builders for engine tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from asia_atm.bars import Bar

ET = ZoneInfo("America/New_York")

# A Wednesday, matching the reference sessions in SPEC.md.
SESSION_DAY = date(2026, 9, 9)


def et_bar(hhmm: str, o: float, h: float, l: float, c: float,
           day: date = SESSION_DAY, volume: float = 100.0) -> Bar:
    hour, minute = (int(x) for x in hhmm.split(":"))
    stamp = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)
    return Bar(ts=stamp.astimezone(timezone.utc), open=o, high=h, low=l,
               close=c, volume=volume)


def range_window(high: float, low: float, day: date = SESSION_DAY) -> list[Bar]:
    """Sixty 1-minute bars for 18:00-18:59 whose extremes are exactly high/low."""
    mid = (high + low) / 2
    bars: list[Bar] = []
    for minute in range(60):
        hhmm = f"18:{minute:02d}"
        if minute == 10:
            bars.append(et_bar(hhmm, mid, high, mid - 1, mid, day))
        elif minute == 20:
            bars.append(et_bar(hhmm, mid, mid + 1, low, mid, day))
        else:
            bars.append(et_bar(hhmm, mid, mid + 1, mid - 1, mid, day))
    return bars


def sequence(rows: list[tuple], day: date = SESSION_DAY) -> list[Bar]:
    return [et_bar(row[0], *row[1:], day=day) for row in rows]


def drift(start: str, count: int, price: float, step: float,
          day: date = SESSION_DAY) -> list[Bar]:
    """Overlapping bars that walk `price` by `step` and create no gaps."""
    hour, minute = (int(x) for x in start.split(":"))
    bars: list[Bar] = []
    for i in range(count):
        total = hour * 60 + minute + i
        hhmm = f"{total // 60:02d}:{total % 60:02d}"
        level = price + step * i
        bars.append(et_bar(hhmm, level, level + 2, level - 2, level + step, day))
    return bars


# ---------------------------------------------------------------------------
# Reference session 1: 3-minute confirmation (SPEC.md, 2026-09-09)
# Range high 29,474.50 / range low 29,422.75. Sweep at 7:09 PM, extreme
# 29,414.50 at 7:15 PM, bearish 3m FVG [29,424.00, 29,426.00], confirming 3m
# close of 29,427.50 at 7:21 PM. The 7:02 wick to 29,423.00 keeps a 5m gap from
# forming, so the 3m is the highest qualifying timeframe.
# ---------------------------------------------------------------------------

_REFERENCE_3M_CORE = [
    ("19:00", 29436, 29438, 29434, 29435),
    ("19:01", 29435, 29437, 29433, 29434),
    ("19:02", 29434, 29436, 29423, 29433),
    ("19:03", 29433, 29435, 29431, 29432),
    ("19:04", 29432, 29434, 29430, 29431),
    ("19:05", 29431, 29433, 29429, 29430),
    ("19:06", 29430, 29432, 29428, 29429),
    ("19:07", 29429, 29431, 29427, 29428),
    ("19:08", 29428, 29430, 29426, 29427),
    ("19:09", 29427, 29428, 29420, 29422),
    ("19:10", 29422, 29424, 29418, 29420),
    ("19:11", 29420, 29423, 29417, 29419),
    ("19:12", 29419, 29423, 29416, 29418),
    ("19:13", 29418, 29424, 29416, 29423),
    ("19:14", 29423, 29424, 29419, 29421),
    ("19:15", 29421, 29422, 29414.50, 29418),
    ("19:16", 29418, 29421, 29417, 29420),
    ("19:17", 29420, 29426, 29419, 29425),
    ("19:18", 29425, 29428, 29424, 29427),
    ("19:19", 29427, 29429, 29426, 29428),
    ("19:20", 29428, 29429, 29426, 29427.50),
]

_RALLY_TO_TARGET = [
    ("19:21", 29427.50, 29434, 29427, 29432),
    ("19:22", 29432, 29438, 29431, 29436),
    ("19:23", 29436, 29442, 29435, 29440),
    ("19:24", 29440, 29446, 29439, 29444),
    ("19:25", 29444, 29452, 29443, 29450),
    ("19:26", 29450, 29460, 29449, 29458),
    ("19:27", 29458, 29470, 29457, 29468),
    ("19:28", 29468, 29480, 29467, 29476),
]


def reference_3m_session(day: date = SESSION_DAY) -> list[Bar]:
    return (
        range_window(29474.50, 29422.75, day)
        + sequence(_REFERENCE_3M_CORE, day)
        + sequence(_RALLY_TO_TARGET, day)
    )


def five_minute_gap_session(day: date = SESSION_DAY) -> list[Bar]:
    """Same shape, but the 7:02 wick is removed so a 5m FVG also forms."""
    rows = [
        r if r[0] != "19:02" else ("19:02", 29434, 29436, 29432, 29433)
        for r in _REFERENCE_3M_CORE
    ]
    return (
        range_window(29474.50, 29422.75, day)
        + sequence(rows, day)
        + sequence(_RALLY_TO_TARGET, day)
    )


# ---------------------------------------------------------------------------
# Reference session 2: 1-minute confirmation (SPEC.md, 2026-09-08)
# Range high 29,550.25 / range low 29,503.25. Sweep at 7:06 PM, extreme
# 29,489.75, tiny bearish 1m FVG [29,495.75, 29,496.00], confirming 1m close of
# 29,500.00. No other timeframe produces a qualifying gap.
# ---------------------------------------------------------------------------

_REFERENCE_1M_CORE = [
    ("19:00", 29506, 29508, 29505, 29506),
    ("19:01", 29506, 29508, 29505, 29507),
    ("19:02", 29507, 29508, 29505, 29506),
    ("19:03", 29506, 29508, 29505, 29507),
    ("19:04", 29507, 29508, 29505, 29506),
    ("19:05", 29506, 29508, 29505, 29507),
    ("19:06", 29507, 29508, 29501, 29505),
    ("19:07", 29505, 29507, 29503, 29506),
    ("19:08", 29506, 29507, 29504, 29506),
    ("19:09", 29506, 29507, 29499, 29500),
    ("19:10", 29500, 29502, 29496, 29497),
    ("19:11", 29497, 29498, 29490, 29492),
    ("19:12", 29492, 29495.75, 29489.75, 29494),
    ("19:13", 29494, 29500.50, 29493, 29500),
]


def reference_1m_session(day: date = SESSION_DAY) -> list[Bar]:
    return (
        range_window(29550.25, 29503.25, day)
        + sequence(_REFERENCE_1M_CORE, day)
        + drift("19:14", 30, 29501, 2.0, day)
    )
