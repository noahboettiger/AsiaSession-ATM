"""Backtest statistics and reporting."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from .runner import OPEN, STOP, TARGET, BacktestResult, Trade

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def summarize(result: BacktestResult) -> dict:
    closed = result.closed
    wins = [t for t in closed if t.net > 0]
    losses = [t for t in closed if t.net <= 0]
    gross_win = sum(t.net for t in wins)
    gross_loss = -sum(t.net for t in losses)
    net = sum(t.net for t in closed)

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for trade in closed:
        equity += trade.net
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "trades": len(closed),
        "open_positions": len(result.trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "net": net,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "commissions": sum(t.commission for t in closed),
        "avg_win": gross_win / len(wins) if wins else 0.0,
        "avg_loss": gross_loss / len(losses) if losses else 0.0,
        "expectancy": net / len(closed) if closed else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "avg_r": sum(t.r_multiple for t in closed) / len(closed) if closed else 0.0,
        "max_drawdown": max_dd,
        "best": max((t.net for t in closed), default=0.0),
        "worst": min((t.net for t in closed), default=0.0),
        "max_losing_streak": _longest_streak(closed, win=False),
        "max_winning_streak": _longest_streak(closed, win=True),
        "target_hits": sum(1 for t in closed if t.outcome == TARGET),
        "stop_hits": sum(1 for t in closed if t.outcome == STOP),
        "avg_contracts": (
            sum(t.signal.contracts for t in closed) / len(closed) if closed else 0.0
        ),
    }


def _longest_streak(trades: list[Trade], win: bool) -> int:
    best = current = 0
    for trade in trades:
        if (trade.net > 0) == win:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _group(trades: list[Trade], key) -> dict:
    buckets: dict = defaultdict(list)
    for trade in trades:
        buckets[key(trade)].append(trade)
    return {
        k: {
            "n": len(v),
            "wins": sum(1 for t in v if t.net > 0),
            "net": sum(t.net for t in v),
        }
        for k, v in sorted(buckets.items(), key=lambda kv: str(kv[0]))
    }


def format_text(result: BacktestResult) -> str:
    stats = summarize(result)
    cfg = result.config
    lines: list[str] = []

    def row(label: str, value: str) -> None:
        lines.append(f"  {label:<22} {value}")

    span = "no data"
    if result.first_bar and result.last_bar:
        span = f"{result.first_bar.date()} to {result.last_bar.date()}"

    lines.append("=" * 62)
    lines.append(f"  MNQ Asia Session Sweep + IFVG   [{cfg.entry_mode}]")
    lines.append("=" * 62)
    row("Data span", span)
    row("Risk per trade", f"${cfg.risk_dollars:,.2f}")
    row("Timeframes", ", ".join(f"{tf}m" for tf in cfg.timeframes))
    row("Min R:R", f"{cfg.min_rr}" if cfg.min_rr else "off")
    row("Slippage", f"{cfg.slippage_ticks} ticks" if cfg.apply_slippage else "off")
    row(
        "Commissions",
        f"${cfg.commission_per_contract_rt}/RT" if cfg.apply_commissions else "off",
    )
    lines.append("")
    lines.append("  RESULTS")
    row("Trades", str(stats["trades"]))
    row("Win rate", f"{stats['win_rate']:.1%}  ({stats['wins']}W / {stats['losses']}L)")
    row("Net P&L", f"${stats['net']:,.2f}")
    row("Expectancy", f"${stats['expectancy']:,.2f} per trade")
    row("Average R", f"{stats['avg_r']:.2f}R")
    row("Profit factor", f"{stats['profit_factor']:.2f}")
    row("Max drawdown", f"${stats['max_drawdown']:,.2f}")
    row("Avg win / loss", f"${stats['avg_win']:,.2f} / ${stats['avg_loss']:,.2f}")
    row("Best / worst", f"${stats['best']:,.2f} / ${stats['worst']:,.2f}")
    row("Longest streaks", f"{stats['max_winning_streak']}W / {stats['max_losing_streak']}L")
    row("Avg contracts", f"{stats['avg_contracts']:.1f}")
    if stats["commissions"]:
        row("Commissions paid", f"${stats['commissions']:,.2f}")
    if stats["open_positions"]:
        row("Still open at end", str(stats["open_positions"]))

    closed = result.closed
    if closed:
        lines.append("")
        lines.append("  BY CONFIRMATION TIMEFRAME")
        for tf, agg in _group(closed, lambda t: t.signal.timeframe).items():
            rate = agg["wins"] / agg["n"]
            lines.append(
                f"    {tf}m   n={agg['n']:<4} win={rate:>5.0%}   net=${agg['net']:>10,.2f}"
            )

        lines.append("")
        lines.append("  BY WEEKDAY")
        for day, agg in _group(closed, lambda t: t.session_date.weekday()).items():
            rate = agg["wins"] / agg["n"]
            lines.append(
                f"    {_WEEKDAYS[day]}  n={agg['n']:<4} win={rate:>5.0%}   net=${agg['net']:>10,.2f}"
            )

        lines.append("")
        lines.append("  BY DIRECTION")
        for direction, agg in _group(closed, lambda t: t.signal.direction).items():
            rate = agg["wins"] / agg["n"]
            lines.append(
                f"    {direction:<5} n={agg['n']:<4} win={rate:>5.0%}   net=${agg['net']:>10,.2f}"
            )

    lines.append("")
    lines.append("  SESSIONS WITHOUT A TRADE")
    reasons = Counter(skip.reason for skip in result.skips)
    total_sessions = len(result.skips) + len(result.trades)
    for reason, count in reasons.most_common():
        share = count / total_sessions if total_sessions else 0
        lines.append(f"    {reason:<20} {count:>4}  ({share:.0%})")
    took = len(result.trades) / total_sessions if total_sessions else 0
    lines.append(f"    {'TRADED':<20} {len(result.trades):>4}  ({took:.0%})")
    lines.append("=" * 62)
    return "\n".join(lines)


def write_trades_csv(result: BacktestResult, path: str | Path) -> None:
    fields = [
        "session_date", "direction", "timeframe", "entry_ts", "entry_price",
        "fill_price", "stop", "target", "contracts", "risk_points",
        "reward_points", "planned_rr", "planned_risk_usd", "range_high",
        "range_low", "first_sweep_ts", "fvg_bottom", "fvg_top", "exit_ts",
        "exit_price", "outcome", "gross", "commission", "net", "r_multiple",
    ]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in result.trades:
            s = trade.signal
            writer.writerow({
                "session_date": s.session_date,
                "direction": s.direction,
                "timeframe": s.timeframe,
                "entry_ts": s.entry_ts.isoformat(),
                "entry_price": s.entry_price,
                "fill_price": trade.fill_price,
                "stop": s.stop,
                "target": s.target,
                "contracts": s.contracts,
                "risk_points": round(s.risk_points, 2),
                "reward_points": round(s.reward_points, 2),
                "planned_rr": round(s.reward_points / s.risk_points, 2),
                "planned_risk_usd": round(trade.planned_risk, 2),
                "range_high": s.range_high,
                "range_low": s.range_low,
                "first_sweep_ts": s.first_sweep_ts.isoformat(),
                "fvg_bottom": s.fvg_bottom,
                "fvg_top": s.fvg_top,
                "exit_ts": trade.exit_ts.isoformat() if trade.exit_ts else "",
                "exit_price": trade.exit_price if trade.exit_price is not None else "",
                "outcome": trade.outcome,
                "gross": round(trade.gross, 2),
                "commission": round(trade.commission, 2),
                "net": round(trade.net, 2),
                "r_multiple": round(trade.r_multiple, 3),
            })
