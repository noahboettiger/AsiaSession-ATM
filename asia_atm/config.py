"""Strategy configuration. See SPEC.md section 12."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

MNQ_POINT_VALUE = 2.0
MNQ_TICK_SIZE = 0.25

WAIT_HIGHEST_TF = "wait_highest_tf"
FIRST_CONFIRMATION = "first_confirmation"

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)

# Friday and Saturday evenings have no CME session.
DEFAULT_WEEKDAYS = frozenset({SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY})


@dataclass(frozen=True)
class StrategyConfig:
    timezone: str = "America/New_York"

    range_start: time = time(18, 0)
    range_end: time = time(19, 0)
    trade_start: time = time(19, 0)
    trade_end: time = time(20, 30)

    timeframes: tuple[int, ...] = (1, 2, 3, 5)
    entry_mode: str = WAIT_HIGHEST_TF

    risk_dollars: float = 250.0
    point_value: float = MNQ_POINT_VALUE
    tick_size: float = MNQ_TICK_SIZE
    max_contracts: int | None = None

    min_rr: float | None = None
    max_bars_to_invert: int = 0  # 0 disables the freshness requirement
    enabled_weekdays: frozenset[int] = DEFAULT_WEEKDAYS

    apply_slippage: bool = False
    slippage_ticks: float = 1.0
    apply_commissions: bool = False
    commission_per_contract_rt: float = 1.24

    stop_wins_ambiguous_bar: bool = True

    def __post_init__(self) -> None:
        if self.entry_mode not in (WAIT_HIGHEST_TF, FIRST_CONFIRMATION):
            raise ValueError(f"unknown entry_mode: {self.entry_mode}")
        if not self.timeframes:
            raise ValueError("timeframes must not be empty")
        for tf in self.timeframes:
            if 60 % tf != 0:
                raise ValueError(f"timeframe {tf} does not divide evenly into an hour")
        if self.risk_dollars <= 0:
            raise ValueError("risk_dollars must be positive")

    @property
    def slippage_points(self) -> float:
        return self.slippage_ticks * self.tick_size if self.apply_slippage else 0.0
