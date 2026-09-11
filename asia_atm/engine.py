"""Core strategy state machine.

Pure logic with no I/O. Consumes closed 1-minute bars in chronological order and
emits entry signals. The backtester and the live execution adapter both drive
this same object, so there is exactly one implementation of the strategy.

See SPEC.md for the rules this implements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .bars import Bar, TimeframeAggregator
from .config import FIRST_CONFIRMATION, WAIT_HIGHEST_TF, StrategyConfig
from .fvg import BEARISH, BULLISH, DIRECTION_FVG, FVG, detect

LONG = "long"
SHORT = "short"


@dataclass(frozen=True)
class EntrySignal:
    session_date: date
    direction: str
    timeframe: int
    entry_ts: datetime
    entry_price: float
    stop: float
    target: float
    contracts: int
    risk_points: float
    reward_points: float
    range_high: float
    range_low: float
    first_sweep_ts: datetime
    fvg_bottom: float
    fvg_top: float

    @property
    def risk_dollars(self) -> float:
        return self.risk_points * self.contracts * 2.0


@dataclass
class SessionSkip:
    session_date: date
    reason: str


@dataclass
class _Session:
    date: date
    aggs: dict[int, TimeframeAggregator]
    history: dict[int, list[Bar]]
    range_high: float | None = None
    range_low: float | None = None
    locked: bool = False
    low_swept_ts: datetime | None = None
    high_swept_ts: datetime | None = None
    direction: str | None = None
    extreme: float | None = None
    fvgs: dict[tuple[int, str], FVG] = field(default_factory=dict)
    saw_qualifying_fvg: bool = False
    done: bool = False


class StrategyEngine:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.cfg = config or StrategyConfig()
        self.tz = ZoneInfo(self.cfg.timezone)
        self.skips: list[SessionSkip] = []
        self.block_entries = False  # set by the caller while a position is open
        self._session: _Session | None = None

    # ------------------------------------------------------------------ public

    def on_bar(self, bar: Bar) -> EntrySignal | None:
        """Feed one closed 1-minute bar. Returns an entry signal or None."""
        et = bar.ts.astimezone(self.tz)
        if et.time() < self.cfg.range_start:
            return None

        if self._session is None or self._session.date != et.date():
            self._open_session(et.date())

        s = self._session
        assert s is not None

        if et.time() < self.cfg.range_end:
            self._extend_range(s, bar)
            return None

        if not s.locked:
            self._lock_levels(s)
        if s.done:
            return None

        if et.time() >= self.cfg.trade_end:
            self._expire(s)
            return None

        self._update_sweeps(s, bar)
        if s.done:
            return None

        completed: dict[int, Bar] = {}
        for tf, agg in s.aggs.items():
            for htf in agg.push(bar):
                completed[tf] = htf
        for tf, htf in completed.items():
            self._register_fvg(s, tf, htf)

        return self._evaluate(s, completed, bar.close_ts)

    # ----------------------------------------------------------------- session

    def finalize(self) -> None:
        """Close out the session in progress. Call once the feed is exhausted."""
        if self._session is not None and not self._session.done:
            self._expire(self._session)

    def _open_session(self, day: date) -> None:
        self.finalize()
        s = _Session(
            date=day,
            aggs={tf: TimeframeAggregator(tf) for tf in self.cfg.timeframes},
            history={tf: [] for tf in self.cfg.timeframes},
        )
        self._session = s
        if day.weekday() not in self.cfg.enabled_weekdays:
            self._finish(s, "weekday_disabled")

    def _extend_range(self, s: _Session, bar: Bar) -> None:
        s.range_high = bar.high if s.range_high is None else max(s.range_high, bar.high)
        s.range_low = bar.low if s.range_low is None else min(s.range_low, bar.low)

    def _lock_levels(self, s: _Session) -> None:
        s.locked = True
        if s.range_high is None or s.range_low is None:
            self._finish(s, "no_range")

    def _finish(self, s: _Session, reason: str) -> None:
        if not s.done:
            s.done = True
            self.skips.append(SessionSkip(s.date, reason))

    def _expire(self, s: _Session) -> None:
        if not s.locked:
            reason = "no_window_data"
        elif s.direction is None:
            reason = "no_sweep"
        elif not s.saw_qualifying_fvg:
            reason = "sweep_no_fvg"
        else:
            reason = "no_inversion"
        self._finish(s, reason)

    # ------------------------------------------------------------------ sweeps

    def _update_sweeps(self, s: _Session, bar: Bar) -> None:
        assert s.range_high is not None and s.range_low is not None

        if s.low_swept_ts is None and bar.low < s.range_low:
            s.low_swept_ts = bar.ts
            if s.direction is None:
                s.direction = LONG
        if s.high_swept_ts is None and bar.high > s.range_high:
            s.high_swept_ts = bar.ts
            if s.direction is None:
                s.direction = SHORT

        if s.low_swept_ts is not None and s.high_swept_ts is not None:
            self._finish(s, "both_levels_swept")
            return

        if s.direction == LONG:
            s.extreme = bar.low if s.extreme is None else min(s.extreme, bar.low)
        elif s.direction == SHORT:
            s.extreme = bar.high if s.extreme is None else max(s.extreme, bar.high)

    # --------------------------------------------------------------------- fvg

    def _register_fvg(self, s: _Session, tf: int, htf: Bar) -> None:
        hist = s.history[tf]
        hist.append(htf)
        if len(hist) > 3:
            hist.pop(0)
        if len(hist) < 3:
            return
        gap = detect(*hist)
        if gap is not None:
            s.fvgs[(tf, gap.direction)] = gap

    def _qualifies(self, s: _Session, gap: FVG | None, now: datetime) -> bool:
        """A gap must belong to the sweep, and still be fresh enough to act on."""
        if gap is None or gap.spent:
            return False
        swept_at = s.low_swept_ts if s.direction == LONG else s.high_swept_ts
        if swept_at is None or gap.formed_at < swept_at:
            return False
        if self.cfg.max_bars_to_invert:
            age = (now - gap.formed_at).total_seconds() / (gap.timeframe * 60)
            if age > self.cfg.max_bars_to_invert:
                return False
        return True

    def _evaluate(
        self, s: _Session, completed: dict[int, Bar], now: datetime
    ) -> EntrySignal | None:
        wanted = DIRECTION_FVG[s.direction] if s.direction else None

        live = [
            tf
            for tf in self.cfg.timeframes
            if self._qualifies(s, s.fvgs.get((tf, wanted)), now)
        ] if wanted else []
        if live:
            s.saw_qualifying_fvg = True

        required_tf: int | None = None
        if self.cfg.entry_mode == WAIT_HIGHEST_TF and live:
            required_tf = max(live)

        signal: EntrySignal | None = None
        for tf in sorted(completed, reverse=True):
            htf = completed[tf]
            for direction in (BEARISH, BULLISH):
                gap = s.fvgs.get((tf, direction))
                if gap is None or not gap.inverted_by(htf):
                    continue
                belonged_to_sweep = self._qualifies(s, gap, now)
                # An inversion consumes the gap whether or not we trade it.
                gap.spent = True
                if direction != wanted or signal is not None or s.done:
                    continue
                if not belonged_to_sweep:
                    continue
                if required_tf is not None and tf != required_tf:
                    continue
                signal = self._build_signal(s, tf, htf, gap)
        return signal

    # ------------------------------------------------------------------- entry

    def _build_signal(
        self, s: _Session, tf: int, htf: Bar, gap: FVG
    ) -> EntrySignal | None:
        assert s.direction and s.extreme is not None
        assert s.range_high is not None and s.range_low is not None

        entry = htf.close
        # ICT: a stop sitting exactly on the swept extreme invites a second hunt.
        buffer = self.cfg.stop_buffer_ticks * self.cfg.tick_size
        stop = s.extreme - buffer if s.direction == LONG else s.extreme + buffer
        target = s.range_high if s.direction == LONG else s.range_low
        risk_points = abs(entry - stop)
        reward_points = abs(target - entry)

        if risk_points <= 0:
            self._finish(s, "size_zero")
            return None

        contracts = math.floor(
            self.cfg.risk_dollars / (risk_points * self.cfg.point_value)
        )
        if self.cfg.max_contracts is not None:
            contracts = min(contracts, self.cfg.max_contracts)
        if contracts < 1:
            self._finish(s, "size_zero")
            return None

        if self.cfg.min_rr is not None and reward_points / risk_points < self.cfg.min_rr:
            self._finish(s, "min_rr")
            return None

        # A sweep that keeps running is a breakdown, not a stop hunt. If price
        # never came back toward the level, the reversal premise is gone.
        if self.cfg.max_entry_distance:
            level = s.range_low if s.direction == LONG else s.range_high
            beyond = level - entry if s.direction == LONG else entry - level
            if beyond > (s.range_high - s.range_low) * self.cfg.max_entry_distance:
                self._finish(s, "entry_too_far")
                return None

        if self.block_entries:
            self._finish(s, "position_open")
            return None

        s.done = True
        first_sweep = s.low_swept_ts if s.direction == LONG else s.high_swept_ts
        assert first_sweep is not None
        return EntrySignal(
            session_date=s.date,
            direction=s.direction,
            timeframe=tf,
            entry_ts=htf.close_ts,
            entry_price=entry,
            stop=stop,
            target=target,
            contracts=contracts,
            risk_points=risk_points,
            reward_points=reward_points,
            range_high=s.range_high,
            range_low=s.range_low,
            first_sweep_ts=first_sweep,
            fvg_bottom=gap.bottom,
            fvg_top=gap.top,
        )
