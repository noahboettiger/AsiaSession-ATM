# MNQ Asia Session Sweep + IFVG Strategy

Locked specification. This document is the source of truth. Code follows this
document, not the other way around. Changes to behavior start with a change here.

## Instrument

Micro E-mini Nasdaq-100 futures (MNQ), most recent front-month contract, rolled
the same way a continuous MNQ chart rolls.

- Point value: $2.00 per index point
- Tick size: 0.25 points ($0.50 per tick)

## Timezone

All session times are America/New_York and follow the New York clock, so they
shift with daylight saving. "6 PM Eastern" means 6 PM in New York on that date,
EST or EDT.

## 1. Range definition

Each session day, record the highest high and lowest low printed from
6:00:00 PM through 6:59:59 PM New York time, measured from 1-minute candles and
including wicks.

- `range_high` is the buyside liquidity level
- `range_low` is the sellside liquidity level

Levels are locked at 7:00 PM and reset every day. Nothing carries over.
If the 6 PM hour has no data (holiday, outage), the day is skipped.

## 2. Trading window

The sweep and the confirming inversion close must both occur between 7:00 PM and
8:30 PM New York time. A confirming candle whose close stamps exactly 8:30 PM is
valid. After 8:30 PM the day is over, whether or not a setup was developing.

## 3. Sweep

A level is swept when price trades through it by any amount. A wick through
counts and a full candle close through counts. Detection uses 1-minute bars.

- Sellside sweep: a 1-minute low prints strictly below `range_low`
- Buyside sweep: a 1-minute high prints strictly above `range_high`

## 4. Direction

The first level swept inside the window sets the direction for the day.

| First sweep | Direction | FVG sought | Inversion event |
|---|---|---|---|
| `range_low` | Long | Bearish FVG | Candle closes above the FVG's upper boundary |
| `range_high` | Short | Bullish FVG | Candle closes below the FVG's lower boundary |

If both levels are swept before an entry is taken, the day is dead. There is no
take profit target left, so no trade.

## 5. Fair value gap qualification

Timeframes monitored: 30s, 1m, 2m, 3m, 5m, aligned to the hour (the 6 PM session
start is on an exact hour, so hour alignment matches TradingView's session
alignment for all of these intervals).

The 30-second rung is the last resort, used only when no higher timeframe
produced a qualifying gap. Building it requires tick data.

A three candle pattern `c1, c2, c3` on a given timeframe forms an FVG when:

- Bearish: `c3.high < c1.low`. Gap range is `[c3.high, c1.low]`, upper boundary `c1.low`.
- Bullish: `c3.low > c1.high`. Gap range is `[c1.high, c3.low]`, lower boundary `c1.high`.

An FVG qualifies when:

1. It completes at or after 7:00 PM (only bars from 7:00 PM onward feed the
   timeframe aggregators).
2. Its direction matches the sweep direction per section 4.
3. It has not already been closed through.

The FVG does not have to be created by the sweeping candle itself. This sequence
is explicitly valid: FVG forms, price trades back up into it, price re-sweeps the
level, then price closes through the FVG. The only hard requirement is that the
confirming close lands after at least one sweep has occurred.

Only the **most recently formed** qualifying FVG per timeframe and direction is
tracked. A newer FVG replaces the older one.

An FVG is **spent** the first time price closes through its boundary. If that
close happens before any sweep, the FVG is consumed and can never trigger an
entry. Price must build a fresh FVG.

## 6. Timeframe selection

Two selectable entry models, both implemented, switched by `entry_mode`:

**`wait_highest_tf`** (default) - At each candle close, `H` is the highest
timeframe currently holding a live qualifying FVG. Only a close on timeframe `H`
can trigger entry. If a 30s FVG inverts while a live 5m FVG is waiting, the 30s
signal is ignored and the engine waits for the 5m candle to close. If `H` never
inverts before 8:30 PM, no trade is taken that day.

**`first_confirmation`** - The first qualifying inversion close on any timeframe
triggers entry. When several timeframes close on the same minute, the highest
timeframe wins.

In both modes, an inversion close marks its FVG spent whether or not the engine
acts on it.

## 7. Entry

Market order at the close of the confirming candle, in the direction from
section 4. One trade per day maximum. Once an entry is taken, no further setups
are evaluated that day regardless of outcome. Only one position may be open at a
time across days.

## 8. Stop loss

The most extreme price printed during the sweep episode, measured on 1-minute
bars from the first sweep of the traded level through the entry bar inclusive.

- Long: lowest low over that span
- Short: highest high over that span

No buffer or padding is added.

## 9. Take profit

The opposite level, exactly. Long targets `range_high`, short targets
`range_low`. If the opposite level was already swept at any point before entry,
the trade is skipped (section 4).

## 10. Position sizing

```
risk_points       = abs(entry - stop)
risk_per_contract = risk_points * point_value
contracts         = floor(risk_dollars / risk_per_contract)
```

`risk_dollars` defaults to $250 and is user-configurable. If one contract's risk
exceeds `risk_dollars`, the trade is skipped.

## 11. Exits

No time-based exit. The position runs until the stop or the target is hit.

## 12. Optional filters and toggles

| Setting | Default | Notes |
|---|---|---|
| `risk_dollars` | 250.0 | Max dollar risk per trade |
| `entry_mode` | `wait_highest_tf` | Or `first_confirmation` |
| `timeframes` | 1, 2, 3, 5 | Monitored FVG timeframes |
| `min_rr` | off | Optional minimum reward:risk, skip trade if below |
| `enabled_weekdays` | Sun-Thu | Per-weekday on/off, keyed to the 6 PM session date |
| `apply_slippage` | off | Ticks of adverse fill on entries and stops |
| `slippage_ticks` | 1.0 | Used when slippage is on |
| `apply_commissions` | off | Round-turn commission per contract |
| `commission_per_contract_rt` | 1.24 | Used when commissions are on |
| `max_contracts` | none | Optional hard cap on position size |

Take profit is a resting limit at the level, so no slippage is applied to it.
Slippage and commissions affect reported P&L only, not position sizing.

## 13. Backtest fill conventions

- Entry fills at the confirming candle's close price, adjusted for slippage.
- Exits are evaluated from the bar after entry onward, on 1-minute bars.
- If a single 1-minute bar contains both the stop and the target, the stop is
  assumed hit first.

## 14. Session skip reasons

Every session that produces no trade is recorded with a reason, so the backtest
reports how often each stage of the setup fails:

`weekday_disabled`, `no_range`, `no_sweep`, `sweep_no_fvg`, `no_inversion`,
`both_levels_swept`, `size_zero`, `min_rr`, `position_open`

## Reference trades

Two hand-verified sessions used as behavioral fixtures.

**2026-09-09, 3-minute entry, long**

| Field | Value |
|---|---|
| Range high | 29,474.50 |
| Range low | 29,422.75 |
| First sweep | 7:09 PM |
| Sweep extreme | 29,414.50 (7:15 PM candle) |
| Confirming timeframe | 3m (no qualifying 5m FVG existed) |
| Entry | 29,427.50 |
| Stop | 29,414.50 |
| Target | 29,474.50 |
| Risk | 13.00 points, 9 contracts, $234.00 |
| Result | Target hit near 8:00 PM |

**2026-09-08, 1-minute entry, long**

| Field | Value |
|---|---|
| Range high | 29,550.25 |
| Range low | 29,503.25 |
| Sweep extreme | 29,489.75 |
| Confirming timeframe | 1m (only timeframe with a qualifying FVG) |
| Entry | 29,500.00 |
| Stop | 29,489.75 |
| Target | 29,550.25 |
| Risk | 10.25 points, 12 contracts, $246.00 |
| Result | Target hit |

Note that the second entry filled below the swept level. That is expected and
valid. The inversion close is what matters, not where it sits relative to the
level.
