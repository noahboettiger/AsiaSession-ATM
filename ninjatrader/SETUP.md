# NinjaTrader setup, compile and backtest

Step by step for `AsiaSessionSweepIfvg.cs`. Written assuming you have never
compiled a NinjaScript strategy before.

This code has never been compiled. I do not have NinjaTrader or a C# compiler
available, so expect a round of compile errors on the first attempt. Copy the
Errors tab text back to me and I will fix them.

---

## 1. Install the file

1. On the machine running NinjaTrader, open File Explorer.
2. Go to `Documents\NinjaTrader 8\bin\Custom\Strategies\`.
3. Copy `AsiaSessionSweepIfvg.cs` into that folder.

Do not rename the file. NinjaTrader matches the class name inside it.

## 2. Compile

1. Open NinjaTrader.
2. Menu bar: **New > NinjaScript Editor**.
3. In the editor's left panel, expand **Strategies**. You should see
   `AsiaSessionSweepIfvg` in the list. Double-click it to open.
4. Press **F5**, or right-click in the code window and choose **Compile**.
5. Watch the **Errors** tab at the bottom of the editor.
   - No errors: a small "Compile successful" toast appears and the strategy is
     ready. Move to step 3.
   - Errors: each row gives a line number and a message. Send me the full list
     and I will correct the file.

Compiling rebuilds every custom script you have, so an unrelated broken script
in your folder will also show up here. Errors referencing a different file name
are not from this strategy.

## 3. Set the time zone

The session inputs are `1800`, `1900` and `2030` in **chart time**, not
automatically New York time.

Easiest option, do this once:

1. **Tools > Options > General**.
2. Set **Time zone** to `(UTC-05:00) Eastern Time (US & Canada)`.
3. Restart NinjaTrader.

Now `1800` means 6:00 PM New York, and daylight saving is handled for you.

If you would rather leave NinjaTrader on Central time, change the three inputs to
`1700`, `1800` and `1930` instead. New York and Chicago shift for daylight saving
on the same dates, so a flat one hour offset is always correct. Do not mix the
two approaches.

## 4. Download the data

1. **Tools > Historical Data Manager**.
2. **Load** tab.
3. Instrument: `MNQ ##-##` (the continuous contract, not a single expiry).
4. Type: **Tick**. This matters. The 30-second timeframe cannot be built from
   minute data, so without tick history the 30s rung is silently unavailable.
5. Set your date range and click **Load**.

Tick data for several years of MNQ is a large download and will take a while.
Start with three to six months to prove the strategy works, then extend.

If you want to skip tick data for the first pass, turn **Use 30 second** off in
the strategy inputs and load **Minute** data instead. Everything from 1m up will
work. Add the 30s rung once you have tick history.

For the continuous contract, set **Merge Policy** to **Merge Non-Back Adjusted**
so prices match what actually traded on each date. The strategy computes all its
levels inside a single session, so roll adjustments do not affect the logic, but
non-back-adjusted makes manual chart verification much easier.

## 5. Run a backtest

1. **New > Strategy Analyzer**.
2. Top left, click the instrument selector and pick `MNQ ##-##`.
3. In the right-hand properties panel:
   - **Strategy**: `AsiaSessionSweepIfvg`
   - **Start date / End date**: your test range
   - **Bars type**: `Minute`, **Value**: `1`
   - **Order fill resolution**: `High`
   - **Fill resolution type**: `Tick`, **Value**: `1`
   - **Slippage**: start at `0`, then rerun at `1` to see the cost
   - **Commission**: select your Lucid/CQG commission template if you have one
4. Set the strategy inputs (they appear below the general settings):
   - **Risk per trade ($)**: `250`
   - **Entry model**: `WaitForHighestTimeframe`
   - Timeframe toggles as desired
   - **Log to output window**: `True`
   - **Export CSV path**: something like `C:\Users\you\Documents\asia_trades.csv`
5. Click **Run**.

### About the primary series

The strategy ignores the primary chart series for its logic and drives
everything off the five series it adds itself. But orders are submitted against
the primary series, so a market order sent at a 30-second close does not fill
until the primary series advances.

Rule of thumb: **the primary series should be at least as fine as your finest
enabled timeframe.**

- Using 1m through 5m: set Bars type to `Minute` / `1`
- Using the 30s rung too: set Bars type to `Second` / `30`

A 30-second primary over multiple years is memory hungry. Test a shorter range
first and watch NinjaTrader's memory use.

## 6. Verify the entries by hand

This is the part that matters before you trust any statistics.

1. After the backtest, open the **Output** window (**New > Output**).
   Every session prints either a full trade breakdown or the reason it was
   skipped, like `2026-09-09  no trade: no_sweep`.
2. A traded session prints the range, the sweep time and price, the sweep
   extreme, the gap boundaries and when it formed, the confirming close, and the
   final entry, stop, target, contracts and R multiple. That is everything you
   need to check a trade without opening a chart.
3. To check it visually, open a chart on `MNQ ##-##` at the same interval, then
   right-click the chart, **Strategies**, add `AsiaSessionSweepIfvg`, enable it,
   and set **Draw levels and gaps** to `True`. The chart will show the range
   high and low as dashed lines, the confirming gap as a shaded box, and entry,
   stop and target as solid lines.
4. The CSV export gives you the same data one row per trade, so you can sort and
   filter in Excel while you audit.

The skip reasons are deliberately specific so you can tell the difference
between "no setup existed" and "the code missed a setup that was there":

| Reason | Meaning |
|---|---|
| `no_sweep` | Neither level was taken between 7:00 and 8:30 PM |
| `sweep_no_fvg` | A level was swept but no qualifying gap ever formed |
| `no_inversion` | A gap formed but never got closed through in time |
| `both_levels_swept` | Both levels were taken, so no target was left |
| `size_zero` | The stop was too wide for even one contract at your risk |
| `min_rr` | The reward:risk filter rejected it |
| `no_range` | The 6 PM hour had no data |
| `weekday_disabled` | That weekday is switched off |
| `position_open` | A prior trade was still running |

If you find a session where the chart clearly shows a valid setup but the log
says `no_sweep` or `sweep_no_fvg`, that is a bug worth sending to me with the
date. That is exactly what this logging is for.

## 7. Things to check on the first run

Specific risks in code that has not been executed yet:

1. **Order submission from a secondary series.** Orders are sent with
   `EnterLong(0, quantity, ...)`. If NinjaTrader complains about submitting
   orders from a non-primary series, tell me and I will restructure it.
2. **Series indexing.** The five added series are assumed to be indexed 1 to 5
   in the order added. If gaps appear on the wrong timeframe, this is the first
   suspect.
3. **The 30-second rung.** If no 30s data exists, that series produces no bars.
   The evaluation is written to tolerate it, but confirm the log never shows a
   30s entry on a range where you have no tick data.
4. **Drawing from a secondary series.** All drawing uses time-based overloads to
   avoid bar index problems. If the chart objects land in the wrong place, turn
   **Draw levels and gaps** off and tell me.
5. **First session skipped.** `BarsRequiredToTrade` and the three-bar gap
   history mean the first session in your range may not trade. That is expected.

## 8. Going live later

Once the statistics look good, the same file runs live. Chart > Strategies tab,
add it, set the account to your Lucid account, and enable. No code changes.

Before that: confirm your prop firm permits automated execution, and paper trade
it on a Sim account for a few weeks first, comparing the Sim fills against what
the backtest expected on the same sessions.
