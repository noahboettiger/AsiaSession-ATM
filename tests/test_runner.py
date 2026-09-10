import unittest
from datetime import date

from asia_atm.config import StrategyConfig
from asia_atm.backtest.runner import STOP, TARGET, run

from . import fixtures as fx

# Reference trade: long 9 lots at 29,427.50, stop 29,414.50, target 29,474.50.
WINNER = 47.00 * 2.0 * 9
LOSER = -13.00 * 2.0 * 9


def losing_session(day: date = fx.SESSION_DAY):
    """The reference setup, then price fails and takes out the swing low."""
    return fx.reference_3m_session(day)[:-8] + fx.sequence([
        ("19:21", 29427.50, 29428, 29422, 29423),
        ("19:22", 29423, 29424, 29416, 29417),
        ("19:23", 29417, 29418, 29410, 29411),
        ("19:24", 29411, 29413, 29408, 29409),
    ], day)


class ExitTests(unittest.TestCase):
    def test_target_exit_pays_planned_reward(self):
        result = run(fx.reference_3m_session())
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.outcome, TARGET)
        self.assertAlmostEqual(trade.exit_price, 29474.50)
        self.assertAlmostEqual(trade.net, WINNER)

    def test_stop_exit_loses_the_planned_risk(self):
        result = run(losing_session())
        trade = result.trades[0]
        self.assertEqual(trade.outcome, STOP)
        self.assertAlmostEqual(trade.exit_price, 29414.50)
        self.assertAlmostEqual(trade.net, LOSER)
        self.assertAlmostEqual(trade.net, -trade.planned_risk)
        self.assertLessEqual(abs(trade.net), 250.0)

    def test_bar_containing_both_levels_resolves_as_a_stop(self):
        bars = fx.reference_3m_session()[:-8] + fx.sequence([
            ("19:21", 29427.50, 29480, 29410, 29470),
        ])
        result = run(bars)
        self.assertEqual(result.trades[0].outcome, STOP)

    def test_optimistic_fills_can_be_disabled(self):
        bars = fx.reference_3m_session()[:-8] + fx.sequence([
            ("19:21", 29427.50, 29480, 29410, 29470),
        ])
        result = run(bars, StrategyConfig(stop_wins_ambiguous_bar=False))
        self.assertEqual(result.trades[0].outcome, TARGET)

    def test_entry_bar_itself_cannot_trigger_an_exit(self):
        # The 7:20 PM confirming bar dips to 29,426 which is above the stop, but
        # the position only starts being managed from the following bar.
        result = run(fx.reference_3m_session())
        self.assertGreater(result.trades[0].exit_ts, result.trades[0].signal.entry_ts)

    def test_r_multiple_is_one_on_a_full_stop(self):
        trade = run(losing_session()).trades[0]
        self.assertAlmostEqual(trade.r_multiple, -1.0)


class CostTests(unittest.TestCase):
    def test_commissions_reduce_net_only(self):
        cfg = StrategyConfig(apply_commissions=True, commission_per_contract_rt=1.24)
        trade = run(fx.reference_3m_session(), cfg).trades[0]
        self.assertAlmostEqual(trade.gross, WINNER)
        self.assertAlmostEqual(trade.commission, 9 * 1.24)
        self.assertAlmostEqual(trade.net, WINNER - 9 * 1.24)

    def test_slippage_worsens_entry_but_not_the_limit_target(self):
        cfg = StrategyConfig(apply_slippage=True, slippage_ticks=1.0)
        trade = run(fx.reference_3m_session(), cfg).trades[0]
        self.assertAlmostEqual(trade.fill_price, 29427.75)
        self.assertAlmostEqual(trade.exit_price, 29474.50)
        self.assertAlmostEqual(trade.net, (29474.50 - 29427.75) * 2.0 * 9)

    def test_slippage_worsens_a_stop_exit(self):
        cfg = StrategyConfig(apply_slippage=True, slippage_ticks=1.0)
        trade = run(losing_session(), cfg).trades[0]
        self.assertAlmostEqual(trade.fill_price, 29427.75)
        self.assertAlmostEqual(trade.exit_price, 29414.25)
        self.assertLess(trade.net, LOSER)

    def test_costs_do_not_change_position_size(self):
        plain = run(fx.reference_3m_session()).trades[0]
        costed = run(
            fx.reference_3m_session(),
            StrategyConfig(apply_slippage=True, apply_commissions=True),
        ).trades[0]
        self.assertEqual(plain.signal.contracts, costed.signal.contracts)


class PositionTests(unittest.TestCase):
    def test_a_second_session_is_skipped_while_a_position_is_open(self):
        # Day two trades entirely between day one's stop and target, so the
        # first position is still live when day two produces its own signal.
        day_one = fx.reference_3m_session(date(2026, 9, 9))[:-8]
        day_two = fx.range_window(29470, 29450, date(2026, 9, 10)) + fx.sequence([
            ("19:00", 29455, 29457, 29453, 29456),
            ("19:01", 29456, 29458, 29454, 29455),
            ("19:02", 29455, 29456, 29446, 29448),
            ("19:03", 29448, 29449, 29440, 29442),
            ("19:04", 29442, 29443, 29430, 29432),
            ("19:05", 29432, 29438, 29428, 29436),
            ("19:06", 29436, 29444, 29435, 29442),
            ("19:07", 29442, 29450, 29441, 29448),
            ("19:08", 29448, 29456, 29447, 29454),
            ("19:09", 29454, 29458, 29452, 29456),
        ], date(2026, 9, 10))
        result = run(day_one + day_two)
        self.assertEqual(len(result.trades), 1)
        self.assertIn("position_open", [s.reason for s in result.skips])

    def test_unfinished_position_is_reported_as_open(self):
        result = run(fx.reference_3m_session()[:-8])
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.closed, [])


if __name__ == "__main__":
    unittest.main()
