"""Fair value gap detection and inversion. See SPEC.md section 5."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .bars import Bar

BEARISH = "bearish"
BULLISH = "bullish"

# A sellside sweep looks for a bearish gap to invert upward, and vice versa.
DIRECTION_FVG = {"long": BEARISH, "short": BULLISH}


@dataclass
class FVG:
    timeframe: int
    direction: str
    bottom: float
    top: float
    formed_at: datetime
    spent: bool = False

    @property
    def boundary(self) -> float:
        """The edge price must close beyond to invert the gap."""
        return self.top if self.direction == BEARISH else self.bottom

    def inverted_by(self, bar: Bar) -> bool:
        if self.spent or bar.close_ts <= self.formed_at:
            return False
        if self.direction == BEARISH:
            return bar.close > self.top
        return bar.close < self.bottom


def detect(c1: Bar, c2: Bar, c3: Bar) -> FVG | None:
    """Standard three candle gap between the first and third candle."""
    if c3.high < c1.low:
        return FVG(c1.minutes, BEARISH, c3.high, c1.low, c3.close_ts)
    if c3.low > c1.high:
        return FVG(c1.minutes, BULLISH, c1.high, c3.low, c3.close_ts)
    return None
