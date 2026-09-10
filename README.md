# AsiaSession-ATM

MNQ Asia session liquidity sweep + inverse fair value gap strategy.

Mark the 6:00 to 7:00 PM New York high and low. Between 7:00 and 8:30 PM, wait
for price to sweep one of those levels, build a fair value gap, then close back
through that gap. Enter on the confirming close, stop at the swing extreme of the
sweep, target the opposite level, risking a fixed dollar amount.

The full rule set lives in [SPEC.md](SPEC.md). That document is the source of
truth. Code follows the spec, not the other way around.

## Design

One strategy implementation, driven by different adapters:

```
                    asia_atm/engine.py
                 (pure state machine, no I/O)
                            |
             +--------------+--------------+
             |                             |
     backtest replay                 live adapter
   (historical 1m CSV)            (Tradovate, planned)
```

The engine consumes closed 1-minute bars and emits entry signals. It builds the
2m, 3m and 5m candles internally from those 1-minute bars rather than consuming
four separate feeds, so the backtest and live trading agree bar for bar. There is
no second copy of the strategy logic to drift out of sync.

Pure standard library, no dependencies.

## Running a backtest

```bash
python -m asia_atm.backtest.cli data/mnq_1m.csv
```

Useful flags:

```bash
--compare-modes           # run both entry models side by side
--risk 250                # max dollar risk per trade
--min-rr 2.0              # optional reward:risk filter, off by default
--weekdays sun,mon,tue    # per weekday on/off
--slippage --commissions  # cost modeling toggles
--trades-csv out.csv      # per-trade detail for your own analysis
```

## Input data

A CSV of 1-minute MNQ bars, oldest first, timestamps being bar OPEN times.
Column names are matched loosely, so most vendor exports work as-is:

```csv
timestamp,open,high,low,close,volume
2026-09-09 18:00:00,29450.25,29451.00,29449.50,29450.75,412
```

Separate `date` and `time` columns work too, as do epoch seconds and epoch
milliseconds. Naive timestamps are interpreted in `--input-tz`, which defaults to
`America/New_York`. Pass `--input-tz UTC` or `--input-tz America/Chicago` if your
vendor stamps bars differently, since getting this wrong silently shifts the
whole session window.

The backtest needs continuous coverage of the 6:00 PM to 8:30 PM New York window.
Sessions missing the 6 PM hour are skipped and reported as `no_range`.

## Tests

```bash
python -m unittest discover -s tests -t .
```

The suite includes both hand-verified reference sessions from SPEC.md, asserting
the engine reproduces the exact entry, stop, target and contract count of trades
that were actually taken.

## Status

Done:

- Strategy engine covering the full spec
- Backtest replay with fill simulation, cost modeling and reporting
- Both entry models (`wait_highest_tf` and `first_confirmation`) as a toggle

Next:

- Historical MNQ 1-minute data to actually validate the edge
- Tradovate live execution adapter driving the same engine
