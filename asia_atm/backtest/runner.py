"""Replay historical 1-minute bars through the strategy engine and simulate fills.

Fill conventions are documented in SPEC.md section 13.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from ..bars import Bar
from ..config import StrategyConfig
from ..engine import LONG, EntrySignal, SessionSkip, StrategyEngine

TARGET = "target"
STOP = "stop"
OPEN = "open"


@dataclass
class Trade:
    signal: EntrySignal
    fill_price: float
    exit_ts: datetime | None = None
    exit_price: float | None = None
    outcome: str = OPEN
    gross: float = 0.0
    commission: float = 0.0

    @property
    def net(self) -> float:
        return self.gross - self.commission

    @property
    def session_date(self) -> date:
        return self.signal.session_date

    @property
    def planned_risk(self) -> float:
        return self.signal.risk_points * self.signal.contracts * 2.0

    @property
    def r_multiple(self) -> float:
        risk = self.signal.risk_points * self.signal.contracts
        return self.net / (risk * 2.0) if risk else 0.0


@dataclass
class BacktestResult:
    trades: list[Trade]
    skips: list[SessionSkip]
    config: StrategyConfig
    first_bar: datetime | None = None
    last_bar: datetime | None = None

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if t.outcome != OPEN]


def run(bars: Iterable[Bar], config: StrategyConfig | None = None) -> BacktestResult:
    cfg = config or StrategyConfig()
    engine = StrategyEngine(cfg)
    trades: list[Trade] = []
    position: Trade | None = None
    first_bar: datetime | None = None
    last_bar: datetime | None = None

    slip = cfg.slippage_points
    for bar in bars:
        if first_bar is None:
            first_bar = bar.ts
        last_bar = bar.ts

        if position is not None and bar.ts >= position.signal.entry_ts:
            if _try_exit(position, bar, cfg, slip):
                position = None

        engine.block_entries = position is not None
        signal = engine.on_bar(bar)
        if signal is not None and position is None:
            fill = signal.entry_price + (slip if signal.direction == LONG else -slip)
            position = Trade(signal=signal, fill_price=fill)
            trades.append(position)

    engine.finalize()
    return BacktestResult(trades, engine.skips, cfg, first_bar, last_bar)


def _try_exit(trade: Trade, bar: Bar, cfg: StrategyConfig, slip: float) -> bool:
    sig = trade.signal
    long = sig.direction == LONG
    hit_stop = bar.low <= sig.stop if long else bar.high >= sig.stop
    hit_target = bar.high >= sig.target if long else bar.low <= sig.target

    if not hit_stop and not hit_target:
        return False
    if hit_stop and (not hit_target or cfg.stop_wins_ambiguous_bar):
        outcome = STOP
        # Stops are market orders on trigger, so slippage applies.
        price = sig.stop - slip if long else sig.stop + slip
    else:
        outcome = TARGET
        # The target is a resting limit at the level.
        price = sig.target

    trade.outcome = outcome
    trade.exit_ts = bar.close_ts
    trade.exit_price = price
    points = (price - trade.fill_price) if long else (trade.fill_price - price)
    trade.gross = points * cfg.point_value * sig.contracts
    if cfg.apply_commissions:
        trade.commission = cfg.commission_per_contract_rt * sig.contracts
    return True
