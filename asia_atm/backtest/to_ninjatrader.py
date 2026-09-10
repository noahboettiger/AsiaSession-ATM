"""Convert a vendor 1-minute CSV into NinjaTrader 8's historical import format.

NinjaTrader imports semicolon-delimited text, one bar per line:

    yyyyMMdd HHmmss;open;high;low;close;volume

Reads through the same tolerant loader the backtester uses, so most vendor
exports work without preprocessing.

    python -m asia_atm.backtest.to_ninjatrader vendor.csv --instrument "MNQ 09-26"
"""

from __future__ import annotations

import argparse
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import load_csv


def write_ninjatrader(bars, path: Path, output_timezone: str) -> int:
    tz = timezone.utc if output_timezone.upper() == "UTC" else ZoneInfo(output_timezone)
    with open(path, "w", newline="\n") as handle:
        for bar in bars:
            stamp = bar.ts.astimezone(tz)
            handle.write("{0};{1};{2};{3};{4};{5}\n".format(
                stamp.strftime("%Y%m%d %H%M%S"),
                bar.open, bar.high, bar.low, bar.close, int(bar.volume),
            ))
    return len(bars)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="vendor 1-minute bar CSV")
    parser.add_argument("--instrument", default="MNQ 09-26",
                        help="names the output file, which is how NinjaTrader "
                             "identifies the instrument on import")
    parser.add_argument("--input-tz", default="America/New_York",
                        help="timezone of naive timestamps in the source CSV")
    parser.add_argument("--output-tz", default="UTC",
                        help="timezone to stamp the export in")
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args(argv)

    bars = load_csv(args.csv, args.input_tz)
    if not bars:
        print("no bars loaded")
        return 1

    path = Path(args.out_dir) / "{0}.Last.txt".format(args.instrument)
    count = write_ninjatrader(bars, path, args.output_tz)

    print("wrote {0} bars to {1}".format(count, path))
    print("first {0}, last {1}".format(bars[0].ts, bars[-1].ts))
    print("Import via Tools > Historical Data > Import, then verify one known "
          "session before importing the rest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
