import unittest

from asia_atm.bars import TimeframeAggregator
from asia_atm.fvg import BEARISH, BULLISH, detect

from .fixtures import et_bar


class AggregatorTests(unittest.TestCase):
    def test_five_minute_bar_folds_the_hour_aligned_bucket(self):
        agg = TimeframeAggregator(5)
        rows = [
            ("19:00", 100, 110, 95, 105),
            ("19:01", 105, 120, 104, 118),
            ("19:02", 118, 119, 90, 92),
            ("19:03", 92, 100, 91, 99),
            ("19:04", 99, 101, 98, 100),
        ]
        out = []
        for row in rows:
            out.extend(agg.push(et_bar(*row)))

        self.assertEqual(len(out), 1)
        bar = out[0]
        self.assertEqual(bar.minutes, 5)
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (100, 120, 90, 100))
        self.assertEqual(bar.ts, et_bar("19:00", 0, 0, 0, 0).ts)

    def test_bucket_completes_on_its_final_minute(self):
        agg = TimeframeAggregator(3)
        self.assertEqual(agg.push(et_bar("19:00", 1, 2, 0, 1)), [])
        self.assertEqual(agg.push(et_bar("19:01", 1, 2, 0, 1)), [])
        self.assertEqual(len(agg.push(et_bar("19:02", 1, 2, 0, 1))), 1)

    def test_partial_bucket_flushes_when_the_next_one_opens(self):
        agg = TimeframeAggregator(5)
        agg.push(et_bar("19:02", 10, 12, 9, 11))
        agg.push(et_bar("19:03", 11, 13, 10, 12))
        out = agg.push(et_bar("19:06", 20, 21, 19, 20))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].high, 13)
        self.assertEqual(out[0].ts, et_bar("19:00", 0, 0, 0, 0).ts)

    def test_one_minute_aggregator_passes_bars_straight_through(self):
        agg = TimeframeAggregator(1)
        out = agg.push(et_bar("19:07", 5, 6, 4, 5))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].close, 5)


class FVGTests(unittest.TestCase):
    def test_bearish_gap_boundaries(self):
        gap = detect(
            et_bar("19:00", 100, 105, 98, 99),
            et_bar("19:01", 99, 99, 92, 93),
            et_bar("19:02", 93, 96, 90, 95),
        )
        self.assertIsNotNone(gap)
        self.assertEqual(gap.direction, BEARISH)
        self.assertEqual((gap.bottom, gap.top), (96, 98))
        self.assertEqual(gap.boundary, 98)

    def test_bullish_gap_boundaries(self):
        gap = detect(
            et_bar("19:00", 90, 92, 88, 91),
            et_bar("19:01", 91, 99, 90, 98),
            et_bar("19:02", 98, 101, 95, 100),
        )
        self.assertEqual(gap.direction, BULLISH)
        self.assertEqual((gap.bottom, gap.top), (92, 95))
        self.assertEqual(gap.boundary, 92)

    def test_overlapping_candles_are_not_a_gap(self):
        self.assertIsNone(detect(
            et_bar("19:00", 100, 105, 95, 99),
            et_bar("19:01", 99, 100, 92, 93),
            et_bar("19:02", 93, 97, 90, 96),
        ))

    def test_inversion_requires_closing_past_the_far_edge(self):
        gap = detect(
            et_bar("19:00", 100, 105, 98, 99),
            et_bar("19:01", 99, 99, 92, 93),
            et_bar("19:02", 93, 96, 90, 95),
        )
        inside = et_bar("19:03", 95, 99, 94, 97)   # closes inside the gap
        beyond = et_bar("19:04", 97, 100, 96, 98.25)
        self.assertFalse(gap.inverted_by(inside))
        self.assertTrue(gap.inverted_by(beyond))

    def test_spent_gap_never_inverts_again(self):
        gap = detect(
            et_bar("19:00", 100, 105, 98, 99),
            et_bar("19:01", 99, 99, 92, 93),
            et_bar("19:02", 93, 96, 90, 95),
        )
        gap.spent = True
        self.assertFalse(gap.inverted_by(et_bar("19:04", 97, 100, 96, 99)))


if __name__ == "__main__":
    unittest.main()
