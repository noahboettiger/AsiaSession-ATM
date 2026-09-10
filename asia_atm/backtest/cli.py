"""Command line backtest runner.

    python -m asia_atm.backtest.cli data/mnq_1m.csv --compare-modes
"""

from __future__ import annotations

import argparse
from datetime import time

from ..config import FIRST_CONFIRMATION, WAIT_HIGHEST_TF, StrategyConfig
from . import report
from .data import load_csv
from .runner import run

_WEEKDAY_NAMES = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _parse_time(text: str) -> time:
    hour, _, minute = text.partition(":")
    return time(int(hour), int(minute or 0))


def _parse_weekdays(text: str) -> frozenset[int]:
    days = set()
    for token in text.split(","):
        token = token.strip().lower()[:3]
        if token not in _WEEKDAY_NAMES:
            raise argparse.ArgumentTypeError(f"unknown weekday: {token}")
        days.add(_WEEKDAY_NAMES[token])
    return frozenset(days)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MNQ Asia session sweep + IFVG backtest")
    p.add_argument("csv", help="1-minute MNQ bar CSV")
    p.add_argument("--input-tz", default="America/New_York",
                   help="timezone of naive timestamps in the CSV")
    p.add_argument("--risk", type=float, default=250.0, help="max dollar risk per trade")
    p.add_argument("--entry-mode", choices=[WAIT_HIGHEST_TF, FIRST_CONFIRMATION],
                   default=WAIT_HIGHEST_TF)
    p.add_argument("--compare-modes", action="store_true",
                   help="run both entry models and print both reports")
    p.add_argument("--timeframes", default="1,2,3,5")
    p.add_argument("--min-rr", type=float, default=None,
                   help="minimum reward:risk filter (off by default)")
    p.add_argument("--weekdays", type=_parse_weekdays, default=None,
                   help="e.g. sun,mon,tue,wed,thu")
    p.add_argument("--range-start", type=_parse_time, default=time(18, 0))
    p.add_argument("--range-end", type=_parse_time, default=time(19, 0))
    p.add_argument("--trade-start", type=_parse_time, default=time(19, 0))
    p.add_argument("--trade-end", type=_parse_time, default=time(20, 30))
    p.add_argument("--slippage", action="store_true", help="apply entry/stop slippage")
    p.add_argument("--slippage-ticks", type=float, default=1.0)
    p.add_argument("--commissions", action="store_true")
    p.add_argument("--commission-rt", type=float, default=1.24)
    p.add_argument("--max-contracts", type=int, default=None)
    p.add_argument("--trades-csv", default=None, help="write per-trade detail here")
    return p


def config_from_args(args, entry_mode: str) -> StrategyConfig:
    kwargs = dict(
        range_start=args.range_start,
        range_end=args.range_end,
        trade_start=args.trade_start,
        trade_end=args.trade_end,
        timeframes=tuple(int(t) for t in args.timeframes.split(",")),
        entry_mode=entry_mode,
        risk_dollars=args.risk,
        min_rr=args.min_rr,
        apply_slippage=args.slippage,
        slippage_ticks=args.slippage_ticks,
        apply_commissions=args.commissions,
        commission_per_contract_rt=args.commission_rt,
        max_contracts=args.max_contracts,
    )
    if args.weekdays is not None:
        kwargs["enabled_weekdays"] = args.weekdays
    return StrategyConfig(**kwargs)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bars = load_csv(args.csv, args.input_tz)
    if not bars:
        print("no bars loaded")
        return 1

    modes = [WAIT_HIGHEST_TF, FIRST_CONFIRMATION] if args.compare_modes else [args.entry_mode]
    for mode in modes:
        result = run(bars, config_from_args(args, mode))
        print(report.format_text(result))
        print()
        if args.trades_csv:
            path = args.trades_csv
            if len(modes) > 1:
                path = path.replace(".csv", f".{mode}.csv")
            report.write_trades_csv(result, path)
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
