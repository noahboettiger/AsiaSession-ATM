import unittest
from dataclasses import replace
from datetime import date

from asia_atm.bars import Bar
from asia_atm.config import FIRST_CONFIRMATION, WAIT_HIGHEST_TF, StrategyConfig
from asia_atm.engine import StrategyEngine

from . import fixtures as fx


def collect(bars, config=None):
    engine = StrategyEngine(config or StrategyConfig())
    signals = [s for bar in bars if (s := engine.on_bar(bar)) is not None]
    engine.finalize()
    return engine, signals


def skip_reasons(engine):
    return [s.reason for s in engine.skips]


class ReferenceTradeTests(unittest.TestCase):
    def test_three_minute_confirmation_matches_spec(self):
        _, signals = collect(fx.reference_3m_session())
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig.direction, "long")
        self.assertEqual(sig.timeframe, 3)
        self.assertAlmostEqual(sig.entry_price, 29427.50)
        self.assertAlmostEqual(sig.stop, 29414.50)
        self.assertAlmostEqual(sig.target, 29474.50)
        self.assertAlmostEqual(sig.risk_points, 13.00)
        self.assertEqual(sig.contracts, 9)
        self.assertLessEqual(sig.risk_points * sig.contracts * 2.0, 250.0)
        self.assertAlmostEqual(sig.fvg_top, 29426.00)
        self.assertAlmostEqual(sig.fvg_bottom, 29424.00)

    def test_one_minute_confirmation_matches_spec(self):
        _, signals = collect(fx.reference_1m_session())
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig.timeframe, 1)
        self.assertAlmostEqual(sig.entry_price, 29500.00)
        self.assertAlmostEqual(sig.stop, 29489.75)
        self.assertAlmostEqual(sig.target, 29550.25)
        self.assertAlmostEqual(sig.risk_points, 10.25)
        self.assertEqual(sig.contracts, 12)

    def test_entry_may_fill_below_the_swept_level(self):
        _, signals = collect(fx.reference_1m_session())
        self.assertLess(signals[0].entry_price, signals[0].range_low)


class TimeframeSelectionTests(unittest.TestCase):
    def test_wait_mode_holds_out_for_the_highest_timeframe(self):
        bars = fx.five_minute_gap_session()
        _, wait = collect(bars, StrategyConfig(entry_mode=WAIT_HIGHEST_TF))
        _, first = collect(bars, StrategyConfig(entry_mode=FIRST_CONFIRMATION))

        self.assertEqual(len(wait), 1)
        self.assertEqual(len(first), 1)
        self.assertEqual(wait[0].timeframe, 5)
        self.assertLess(first[0].timeframe, 5)
        self.assertGreater(wait[0].entry_ts, first[0].entry_ts)
        self.assertGreater(wait[0].entry_price, first[0].entry_price)

    def test_first_confirmation_takes_the_earlier_lower_timeframe_signal(self):
        # The reference session also carries a 1m gap that inverts two minutes
        # before the 3m one. Waiting is what reproduces the trade actually taken.
        bars = fx.reference_3m_session()
        _, wait = collect(bars, StrategyConfig(entry_mode=WAIT_HIGHEST_TF))
        _, first = collect(bars, StrategyConfig(entry_mode=FIRST_CONFIRMATION))
        self.assertEqual(wait[0].timeframe, 3)
        self.assertEqual(first[0].timeframe, 1)
        self.assertLess(first[0].entry_ts, wait[0].entry_ts)

    def test_stop_tracks_the_extreme_after_the_first_sweep(self):
        _, signals = collect(fx.reference_3m_session())
        # 7:09 PM is the first bar through the level, 7:15 PM prints the low.
        self.assertEqual(signals[0].first_sweep_ts.astimezone(fx.ET).strftime("%H:%M"), "19:09")
        self.assertAlmostEqual(signals[0].stop, 29414.50)


class NoTradeTests(unittest.TestCase):
    def test_sweeping_both_levels_kills_the_day(self):
        bars = fx.range_window(29474.50, 29422.75) + fx.sequence([
            ("19:00", 29430, 29435, 29420, 29433),   # sellside sweep
            ("19:01", 29433, 29480, 29432, 29470),   # buyside sweep
            ("19:02", 29470, 29472, 29468, 29469),
        ])
        engine, signals = collect(bars)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["both_levels_swept"])

    def test_gap_closed_through_before_the_sweep_is_spent(self):
        bars = fx.range_window(29474.50, 29422.75) + fx.sequence([
            # A bearish 1m FVG forms well above the level and is closed through
            # before any sweep happens, so it can never trigger an entry.
            ("19:00", 29460, 29462, 29458, 29459),
            ("19:01", 29459, 29460, 29450, 29452),
            ("19:02", 29452, 29457, 29450, 29455),
            ("19:03", 29455, 29465, 29454, 29463),   # closes above the gap
            ("19:04", 29463, 29464, 29420, 29425),   # sweep, no new gap
            ("19:05", 29425, 29470, 29424, 29468),
            ("19:06", 29468, 29469, 29467, 29468),
        ])
        engine, signals = collect(bars)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["sweep_no_fvg"])

    def test_gap_formed_before_the_sweep_cannot_trigger(self):
        # The decline into the level leaves a gap high above it. Price sweeps,
        # reverses, and rallies back through that stale gap. Treating it as the
        # setup would enter far above the sweep, long after the move.
        bars = fx.range_window(29623.25, 29540.25) + fx.sequence([
            ("19:00", 29600, 29602, 29596, 29598),
            ("19:01", 29598, 29599, 29590, 29592),
            ("19:02", 29588, 29589, 29585, 29586),   # stale gap 29589 to 29596
            ("19:03", 29586, 29592, 29583, 29584),
            ("19:04", 29584, 29590, 29580, 29582),
            ("19:05", 29582, 29588, 29535, 29538),   # sweep, no new gap
            ("19:06", 29538, 29590, 29536, 29588),
            ("19:07", 29588, 29600, 29586, 29598),   # closes above the stale gap
            ("19:08", 29598, 29604, 29596, 29602),
        ])
        engine, signals = collect(bars)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["sweep_no_fvg"])

    def test_session_without_a_sweep_reports_no_sweep(self):
        bars = fx.range_window(29474.50, 29422.75) + fx.drift("19:00", 60, 29440, 0.1)
        engine, signals = collect(bars)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["no_sweep"])

    def test_missing_range_hour_skips_the_day(self):
        engine, signals = collect(fx.drift("19:00", 30, 29440, 0.5))
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["no_range"])

    def test_disabled_weekday_is_skipped(self):
        cfg = StrategyConfig(enabled_weekdays=frozenset({0}))  # Monday only
        engine, signals = collect(fx.reference_3m_session(), cfg)  # a Wednesday
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["weekday_disabled"])

    def test_risk_too_large_for_one_contract_is_skipped(self):
        cfg = StrategyConfig(risk_dollars=20.0)  # 13 points needs $26
        engine, signals = collect(fx.reference_3m_session(), cfg)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["size_zero"])

    def test_min_rr_filter_blocks_a_thin_target(self):
        cfg = StrategyConfig(min_rr=5.0)  # reference trade is 47 / 13 = 3.6R
        engine, signals = collect(fx.reference_3m_session(), cfg)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["min_rr"])

    def test_freshness_limit_rejects_a_gap_that_took_too_long_to_invert(self):
        # The reference 3m gap forms at 7:15 PM and inverts at 7:21 PM, two 3m
        # candles later. Demanding a reaction on the very next candle kills it.
        cfg = StrategyConfig(max_bars_to_invert=1)
        engine, signals = collect(fx.reference_3m_session(), cfg)
        self.assertEqual(signals, [])
        # With no entry taken, the rally then runs on into the opposite level.
        self.assertEqual(skip_reasons(engine), ["both_levels_swept"])

    def test_freshness_limit_allows_a_prompt_inversion(self):
        cfg = StrategyConfig(max_bars_to_invert=2)
        _, signals = collect(fx.reference_3m_session(), cfg)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].timeframe, 3)
        self.assertAlmostEqual(signals[0].entry_price, 29427.50)

    def test_entry_far_below_the_level_is_rejected(self):
        # The 8/30 shape: price sweeps the low and keeps falling for an hour
        # instead of rejecting, then bounces. Gaps form all the way down and one
        # of them inverts far below the level, long after the premise is gone.
        bars = fx.range_window(29543, 29428) + fx.sequence([
            ("19:00", 29440, 29442, 29436, 29438),
            ("19:01", 29438, 29440, 29425, 29428),   # sweep
            ("19:02", 29428, 29430, 29400, 29405),
            ("19:03", 29405, 29407, 29360, 29365),
            ("19:04", 29365, 29367, 29330, 29335),
            ("19:05", 29335, 29337, 29320, 29322),
            ("19:06", 29322, 29345, 29320, 29342),
            ("19:07", 29342, 29365, 29340, 29363),   # closes above a low gap
        ])
        # Allowing a quarter of the range beyond the level rejects it.
        engine, signals = collect(bars, StrategyConfig(
            max_entry_distance=0.25, entry_mode=FIRST_CONFIRMATION))
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["entry_too_far"])

    def test_entry_just_past_the_level_is_allowed(self):
        # The 9/8 shape: the confirming close sits a few points below the swept
        # level, which is a fraction of the range and entirely valid.
        cfg = StrategyConfig(max_entry_distance=0.25)
        _, signals = collect(fx.reference_1m_session(), cfg)
        self.assertEqual(len(signals), 1)
        self.assertAlmostEqual(signals[0].entry_price, 29500.00)

    def test_proximity_rule_is_off_by_default(self):
        self.assertEqual(StrategyConfig().max_entry_distance, 0.0)

    def test_freshness_limit_is_off_by_default(self):
        self.assertEqual(StrategyConfig().max_bars_to_invert, 0)

    def test_min_rr_filter_allows_a_qualifying_target(self):
        cfg = StrategyConfig(min_rr=3.0)
        _, signals = collect(fx.reference_3m_session(), cfg)
        self.assertEqual(len(signals), 1)

    def test_confirmation_after_the_window_is_ignored(self):
        cfg = StrategyConfig(trade_end=__import__("datetime").time(19, 15))
        engine, signals = collect(fx.reference_3m_session(), cfg)
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["no_inversion"])

    def test_blocked_entries_record_position_open(self):
        engine = StrategyEngine(StrategyConfig())
        engine.block_entries = True
        signals = [s for bar in fx.reference_3m_session() if (s := engine.on_bar(bar))]
        self.assertEqual(signals, [])
        self.assertEqual(skip_reasons(engine), ["position_open"])


class MultiDayTests(unittest.TestCase):
    def test_levels_reset_each_session(self):
        day_one = fx.reference_3m_session(date(2026, 9, 9))
        day_two = fx.reference_1m_session(date(2026, 9, 10))
        _, signals = collect(day_one + day_two)
        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0].session_date, date(2026, 9, 9))
        self.assertEqual(signals[1].session_date, date(2026, 9, 10))
        self.assertNotEqual(signals[0].range_high, signals[1].range_high)

    def test_only_one_entry_per_session(self):
        bars = fx.reference_3m_session() + fx.drift("19:29", 45, 29470, -1.0)
        _, signals = collect(bars)
        self.assertEqual(len(signals), 1)


if __name__ == "__main__":
    unittest.main()
