// MNQ Asia Session Liquidity Sweep + Inverse Fair Value Gap
//
// Port of asia_atm/engine.py. The rules live in SPEC.md; this file follows that
// document. See ninjatrader/SETUP.md for install, compile and backtest steps.
//
// Marks the 6:00-7:00 PM New York range, then between 7:00 and 8:30 PM waits for
// a sweep of either level, a fair value gap on 30s/1m/2m/3m/5m, and a close back
// through that gap. Enters on the confirming close, stops at the swing extreme of
// the sweep, targets the opposite level, sized to a fixed dollar risk.

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
	public enum AsiaIfvgEntryMode
	{
		WaitForHighestTimeframe,
		FirstConfirmation
	}

	public class AsiaSessionSweepIfvg : Strategy
	{
		#region Nested state

		private class Gap
		{
			public bool		Bearish;
			public double	Bottom;
			public double	Top;
			public DateTime	FormedAt;
			public bool		Spent;

			public double Boundary { get { return Bearish ? Top : Bottom; } }

			public bool InvertedBy(double close, DateTime closeTime)
			{
				if (Spent || closeTime <= FormedAt)
					return false;
				return Bearish ? close > Top : close < Bottom;
			}
		}

		private class Slot
		{
			public int		Seconds;
			public int		Bip;
			public string	Label;
			public Gap		Bearish;
			public Gap		Bullish;

			public Gap Directional(bool wantBearish)
			{
				return wantBearish ? Bearish : Bullish;
			}
		}

		private class Inversion
		{
			public Slot		Slot;
			public Gap		Gap;
			public double	Close;
		}

		#endregion

		private const string SignalName = "AsiaIfvg";

		private List<Slot>		slots;
		private List<Inversion>	pendingInversions;

		private DateTime	sessionDate		= DateTime.MinValue;
		private double		rangeHigh;
		private double		rangeLow;
		private bool		rangeValid;
		private bool		sessionDone;
		private bool		sawQualifyingGap;
		private bool		rangeAnnounced;

		private int			direction;					// 1 long, -1 short, 0 undecided
		private DateTime	lowSweptAt		= DateTime.MinValue;
		private DateTime	highSweptAt		= DateTime.MinValue;
		private double		sweepExtreme;

		private DateTime	pendingEvalTime	= DateTime.MinValue;
		private int			pendingCount;

		private int			rangeStartSec;
		private int			rangeEndSec;
		private int			tradeEndSec;

		#region Lifecycle

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description					= "Asia session liquidity sweep into an inverse fair value gap.";
				Name						= "AsiaSessionSweepIfvg";
				Calculate					= Calculate.OnBarClose;
				EntriesPerDirection			= 1;
				EntryHandling				= EntryHandling.AllEntries;
				IsExitOnSessionCloseStrategy = false;	// the spec has no time-based exit
				IsFillLimitOnTouch			= false;
				BarsRequiredToTrade			= 4;
				StartBehavior				= StartBehavior.WaitUntilFlat;
				TimeInForce					= TimeInForce.Gtc;
				TraceOrders					= false;
				RealtimeErrorHandling		= RealtimeErrorHandling.StopCancelCloseIgnoreRejects;
				StopTargetHandling			= StopTargetHandling.PerEntryExecution;

				RiskDollars					= 250;
				EntryMode					= AsiaIfvgEntryMode.WaitForHighestTimeframe;
				MinimumRewardRisk			= 0;			// 0 disables the filter
				MaxContracts				= 0;			// 0 means no cap

				Use30Second					= true;
				Use1Minute					= true;
				Use2Minute					= true;
				Use3Minute					= true;
				Use5Minute					= true;

				RangeStartTime				= 1800;
				RangeEndTime				= 1900;
				TradeEndTime				= 2030;

				TradeSunday					= true;
				TradeMonday					= true;
				TradeTuesday				= true;
				TradeWednesday				= true;
				TradeThursday				= true;

				ShowDrawings				= true;
				LogDetail					= true;
				ExportCsvPath				= string.Empty;
			}
			else if (State == State.Configure)
			{
				slots				= new List<Slot>();
				pendingInversions	= new List<Inversion>();

				// Added smallest first. Order does not affect correctness: evaluation
				// waits until every series closing on a timestamp has been processed.
				if (Use30Second)	AddSlot(30,		"30s");
				if (Use1Minute)		AddSlot(60,		"1m");
				if (Use2Minute)		AddSlot(120,	"2m");
				if (Use3Minute)		AddSlot(180,	"3m");
				if (Use5Minute)		AddSlot(300,	"5m");

				rangeStartSec	= ToSeconds(RangeStartTime);
				rangeEndSec		= ToSeconds(RangeEndTime);
				tradeEndSec		= ToSeconds(TradeEndTime);
			}
			else if (State == State.DataLoaded)
			{
				ResolveSeriesIndexes();
			}
		}

		private void AddSlot(int seconds, string label)
		{
			if (seconds % 60 == 0)
				AddDataSeries(BarsPeriodType.Minute, seconds / 60);
			else
				AddDataSeries(BarsPeriodType.Second, seconds);

			// The real index is resolved in State.DataLoaded by inspecting each
			// loaded series, because NinjaTrader may reuse the primary series when
			// an added one matches it rather than creating a duplicate.
			slots.Add(new Slot { Seconds = seconds, Label = label, Bip = -1 });
		}

		/// <summary>
		/// Match every timeframe to the series that actually got loaded, rather than
		/// assuming series are indexed in the order they were added.
		/// </summary>
		private void ResolveSeriesIndexes()
		{
			if (slots == null || slots.Count == 0)
			{
				Print("AsiaSessionSweepIfvg: no timeframes enabled, this will never trade.");
				return;
			}

			foreach (Slot slot in slots)
			{
				slot.Bip = -1;
				for (int i = 0; i < BarsArray.Length; i++)
				{
					if (BarsArray[i] == null)
						continue;
					if (SecondsOf(BarsArray[i].BarsPeriod) == slot.Seconds)
					{
						slot.Bip = i;
						break;
					}
				}
			}

			// Two timeframes must never share a series, or their gaps would collide.
			for (int a = 0; a < slots.Count; a++)
				for (int b = a + 1; b < slots.Count; b++)
					if (slots[a].Bip >= 0 && slots[a].Bip == slots[b].Bip)
						slots[b].Bip = -1;

			Print("");
			Print("AsiaSessionSweepIfvg loaded. Series mapping:");
			foreach (Slot slot in slots)
				Print(string.Format("    {0,-4} -> {1}", slot.Label,
					slot.Bip < 0 ? "NOT LOADED, this timeframe is inactive" : "series " + slot.Bip));
			Print(string.Format("    session window {0} to {1}, last entry {2}, chart time",
				RangeStartTime, RangeEndTime, TradeEndTime));
			Print("");
		}

		private static int SecondsOf(BarsPeriod period)
		{
			if (period.BarsPeriodType == BarsPeriodType.Minute)
				return period.Value * 60;
			if (period.BarsPeriodType == BarsPeriodType.Second)
				return period.Value;
			return 0;
		}

		private static int ToSeconds(int hhmm)
		{
			return (hhmm / 100) * 3600 + (hhmm % 100) * 60;
		}

		#endregion

		#region Bar handling

		protected override void OnBarUpdate()
		{
			if (slots == null)
				return;

			// The primary series is used when it matches one of our timeframes,
			// and ignored otherwise. SlotFor decides.
			Slot slot = SlotFor(BarsInProgress);
			if (slot == null || CurrentBars[BarsInProgress] < 3)
				return;

			// NinjaTrader stamps a bar with its CLOSE time.
			DateTime closeTime	= Times[BarsInProgress][0];
			int tod				= closeTime.Hour * 3600 + closeTime.Minute * 60 + closeTime.Second;

			bool inRange	= tod > rangeStartSec && tod <= rangeEndSec;
			bool inWindow	= tod > rangeEndSec && tod <= tradeEndSec;
			bool afterHours	= tod > tradeEndSec && tod <= tradeEndSec + 3600;

			if (!inRange && !inWindow && !afterHours)
				return;

			FlushPending(closeTime);

			if (closeTime.Date != sessionDate)
			{
				FinalizeSession();
				StartSession(closeTime.Date);
			}

			if (inRange)
			{
				rangeHigh	= rangeValid ? Math.Max(rangeHigh, Highs[BarsInProgress][0]) : Highs[BarsInProgress][0];
				rangeLow	= rangeValid ? Math.Min(rangeLow, Lows[BarsInProgress][0])   : Lows[BarsInProgress][0];
				rangeValid	= true;
				return;
			}

			if (afterHours)
			{
				ExpireSession();
				return;
			}

			if (sessionDone)
				return;

			if (!rangeValid)
			{
				FinishSession("no_range");
				return;
			}

			if (!rangeAnnounced)
			{
				rangeAnnounced = true;
				LogLine(string.Format("range locked, {0} high / {1} low",
					Format(rangeHigh), Format(rangeLow)));
			}

			DrawLevels(closeTime);
			UpdateSweeps(BarsInProgress, closeTime);
			if (sessionDone)
				return;

			RegisterGap(slot, BarsInProgress, closeTime);
			CollectInversion(slot, BarsInProgress, closeTime);

			if (pendingEvalTime != closeTime)
			{
				pendingEvalTime	= closeTime;
				pendingCount	= 0;
			}
			pendingCount++;

			if (pendingCount >= ExpectedClosers(closeTime))
			{
				Evaluate(closeTime);
				pendingEvalTime	= DateTime.MinValue;
				pendingCount	= 0;
			}
		}

		private Slot SlotFor(int bip)
		{
			foreach (Slot slot in slots)
				if (slot.Bip == bip && bip >= 0)
					return slot;
			return null;
		}

		/// <summary>How many enabled series close on this timestamp.</summary>
		private int ExpectedClosers(DateTime closeTime)
		{
			int secondsIntoHour = closeTime.Minute * 60 + closeTime.Second;
			int count = 0;
			foreach (Slot slot in slots)
				if (slot.Bip >= 0 && secondsIntoHour % slot.Seconds == 0)
					count++;
			return Math.Max(count, 1);
		}

		/// <summary>
		/// Evaluate a timestamp whose series did not all report, which happens when
		/// a period contained no trades and NinjaTrader produced no bar for it.
		/// </summary>
		private void FlushPending(DateTime now)
		{
			if (pendingEvalTime != DateTime.MinValue && now > pendingEvalTime)
			{
				Evaluate(pendingEvalTime);
				pendingEvalTime	= DateTime.MinValue;
				pendingCount	= 0;
			}
		}

		#endregion

		#region Session state

		private void StartSession(DateTime date)
		{
			sessionDate			= date;
			rangeHigh			= 0;
			rangeLow			= 0;
			rangeValid			= false;
			sessionDone			= false;
			sawQualifyingGap	= false;
			rangeAnnounced		= false;
			direction			= 0;
			lowSweptAt			= DateTime.MinValue;
			highSweptAt			= DateTime.MinValue;
			sweepExtreme		= 0;
			pendingEvalTime		= DateTime.MinValue;
			pendingCount		= 0;
			pendingInversions.Clear();

			foreach (Slot slot in slots)
			{
				slot.Bearish = null;
				slot.Bullish = null;
			}

			if (!IsWeekdayEnabled(date.DayOfWeek))
				FinishSession("weekday_disabled");
		}

		private bool IsWeekdayEnabled(DayOfWeek day)
		{
			switch (day)
			{
				case DayOfWeek.Sunday:		return TradeSunday;
				case DayOfWeek.Monday:		return TradeMonday;
				case DayOfWeek.Tuesday:		return TradeTuesday;
				case DayOfWeek.Wednesday:	return TradeWednesday;
				case DayOfWeek.Thursday:	return TradeThursday;
				default:					return false;
			}
		}

		private void FinishSession(string reason)
		{
			if (sessionDone)
				return;
			sessionDone = true;
			if (LogDetail && reason != "traded")
				Print(string.Format("{0:yyyy-MM-dd}  no trade: {1}", sessionDate, reason));
		}

		private void ExpireSession()
		{
			if (sessionDone)
				return;
			if (!rangeValid)			FinishSession("no_window_data");
			else if (direction == 0)	FinishSession("no_sweep");
			else if (!sawQualifyingGap)	FinishSession("sweep_no_fvg");
			else						FinishSession("no_inversion");
		}

		private void FinalizeSession()
		{
			if (sessionDate != DateTime.MinValue)
				ExpireSession();
		}

		#endregion

		#region Sweeps

		private void UpdateSweeps(int bip, DateTime closeTime)
		{
			double high	= Highs[bip][0];
			double low	= Lows[bip][0];

			if (lowSweptAt == DateTime.MinValue && low < rangeLow)
			{
				lowSweptAt = closeTime;
				if (direction == 0)
				{
					direction = 1;
					LogLine(string.Format("sweep of the low at {0:HH:mm:ss}, {1} traded below {2}",
						closeTime, Format(low), Format(rangeLow)));
				}
			}

			if (highSweptAt == DateTime.MinValue && high > rangeHigh)
			{
				highSweptAt = closeTime;
				if (direction == 0)
				{
					direction = -1;
					LogLine(string.Format("sweep of the high at {0:HH:mm:ss}, {1} traded above {2}",
						closeTime, Format(high), Format(rangeHigh)));
				}
			}

			if (lowSweptAt != DateTime.MinValue && highSweptAt != DateTime.MinValue)
			{
				FinishSession("both_levels_swept");
				return;
			}

			if (direction == 1)
				sweepExtreme = sweepExtreme == 0 ? low : Math.Min(sweepExtreme, low);
			else if (direction == -1)
				sweepExtreme = sweepExtreme == 0 ? high : Math.Max(sweepExtreme, high);
		}

		#endregion

		#region Gaps

		private void RegisterGap(Slot slot, int bip, DateTime closeTime)
		{
			double c1High = Highs[bip][2], c1Low = Lows[bip][2];
			double c3High = Highs[bip][0], c3Low = Lows[bip][0];

			if (c3High < c1Low)
				slot.Bearish = new Gap { Bearish = true, Bottom = c3High, Top = c1Low, FormedAt = closeTime };
			else if (c3Low > c1High)
				slot.Bullish = new Gap { Bearish = false, Bottom = c1High, Top = c3Low, FormedAt = closeTime };
		}

		private void CollectInversion(Slot slot, int bip, DateTime closeTime)
		{
			double close = Closes[bip][0];

			if (slot.Bearish != null && slot.Bearish.InvertedBy(close, closeTime))
				pendingInversions.Add(new Inversion { Slot = slot, Gap = slot.Bearish, Close = close });

			if (slot.Bullish != null && slot.Bullish.InvertedBy(close, closeTime))
				pendingInversions.Add(new Inversion { Slot = slot, Gap = slot.Bullish, Close = close });
		}

		#endregion

		#region Evaluation

		private void Evaluate(DateTime closeTime)
		{
			if (sessionDone)
			{
				pendingInversions.Clear();
				return;
			}

			bool wantBearish	= direction == 1;
			bool haveDirection	= direction != 0;
			int requiredSeconds	= 0;

			if (haveDirection)
			{
				int highestLive = 0;
				foreach (Slot slot in slots)
				{
					Gap gap = slot.Directional(wantBearish);
					if (gap != null && !gap.Spent && slot.Seconds > highestLive)
						highestLive = slot.Seconds;
				}

				if (highestLive > 0)
				{
					sawQualifyingGap = true;
					if (EntryMode == AsiaIfvgEntryMode.WaitForHighestTimeframe)
						requiredSeconds = highestLive;
				}
			}

			// Highest timeframe first, so a shared timestamp resolves in its favour.
			pendingInversions.Sort(delegate(Inversion a, Inversion b)
			{
				return b.Slot.Seconds.CompareTo(a.Slot.Seconds);
			});

			bool entered = false;
			foreach (Inversion inversion in pendingInversions)
			{
				// An inversion consumes the gap whether or not it is traded.
				inversion.Gap.Spent = true;

				if (entered || sessionDone || !haveDirection)
					continue;
				if (inversion.Gap.Bearish != wantBearish)
					continue;
				if (requiredSeconds > 0 && inversion.Slot.Seconds != requiredSeconds)
				{
					LogLine(string.Format("{0:HH:mm:ss} skipped {1} inversion, waiting on the {2} gap",
						closeTime, inversion.Slot.Label, SecondsLabel(requiredSeconds)));
					continue;
				}

				entered = TryEnter(inversion, closeTime);
			}

			pendingInversions.Clear();
		}

		private bool TryEnter(Inversion inversion, DateTime closeTime)
		{
			double entry	= inversion.Close;
			double stop		= sweepExtreme;
			double target	= direction == 1 ? rangeHigh : rangeLow;
			double risk		= Math.Abs(entry - stop);
			double reward	= Math.Abs(target - entry);

			if (risk <= 0)
			{
				FinishSession("size_zero");
				return false;
			}

			double pointValue	= Instrument.MasterInstrument.PointValue;
			int quantity		= (int)Math.Floor(RiskDollars / (risk * pointValue));
			if (MaxContracts > 0)
				quantity = Math.Min(quantity, MaxContracts);

			if (quantity < 1)
			{
				FinishSession("size_zero");
				return false;
			}

			if (MinimumRewardRisk > 0 && reward / risk < MinimumRewardRisk)
			{
				FinishSession("min_rr");
				return false;
			}

			if (Position.MarketPosition != MarketPosition.Flat)
			{
				FinishSession("position_open");
				return false;
			}

			stop	= Instrument.MasterInstrument.RoundToTickSize(stop);
			target	= Instrument.MasterInstrument.RoundToTickSize(target);

			SetStopLoss(SignalName, CalculationMode.Price, stop, false);
			SetProfitTarget(SignalName, CalculationMode.Price, target);

			if (direction == 1)
				EnterLong(0, quantity, SignalName);
			else
				EnterShort(0, quantity, SignalName);

			ReportEntry(inversion, closeTime, entry, stop, target, quantity, risk, reward, pointValue);
			DrawTrade(inversion, closeTime, entry, stop, target);
			FinishSession("traded");
			return true;
		}

		#endregion

		#region Reporting

		private void ReportEntry(Inversion inversion, DateTime closeTime, double entry, double stop,
			double target, int quantity, double risk, double reward, double pointValue)
		{
			DateTime sweptAt = direction == 1 ? lowSweptAt : highSweptAt;

			if (LogDetail)
			{
				Print("");
				Print(string.Format("{0:yyyy-MM-dd}  {1} {2} contract(s) on the {3}",
					sessionDate, direction == 1 ? "LONG" : "SHORT", quantity, inversion.Slot.Label));
				Print(string.Format("    range          {0} high / {1} low", Format(rangeHigh), Format(rangeLow)));
				Print(string.Format("    swept          {0} at {1:HH:mm:ss}",
					direction == 1 ? "the low" : "the high", sweptAt));
				Print(string.Format("    sweep extreme  {0}", Format(sweepExtreme)));
				Print(string.Format("    {0} gap        {1} to {2}, formed {3:HH:mm:ss}",
					inversion.Slot.Label, Format(inversion.Gap.Bottom), Format(inversion.Gap.Top),
					inversion.Gap.FormedAt));
				Print(string.Format("    confirmed      {0:HH:mm:ss} closing at {1}", closeTime, Format(entry)));
				Print(string.Format("    entry {0}   stop {1}   target {2}",
					Format(entry), Format(stop), Format(target)));
				Print(string.Format("    risk {0} pts (${1:F2})   reward {2} pts   {3:F2}R",
					Format(risk), risk * pointValue * quantity, Format(reward), reward / risk));
			}

			AppendCsv(inversion, closeTime, entry, stop, target, quantity, risk, reward, pointValue, sweptAt);
		}

		private void AppendCsv(Inversion inversion, DateTime closeTime, double entry, double stop,
			double target, int quantity, double risk, double reward, double pointValue, DateTime sweptAt)
		{
			if (string.IsNullOrWhiteSpace(ExportCsvPath))
				return;

			try
			{
				if (!File.Exists(ExportCsvPath))
					File.AppendAllText(ExportCsvPath,
						"session_date,direction,timeframe,swept_at,sweep_extreme,gap_bottom,gap_top," +
						"gap_formed_at,confirmed_at,entry,stop,target,contracts,risk_points," +
						"reward_points,rr,risk_usd,range_high,range_low" + Environment.NewLine);

				File.AppendAllText(ExportCsvPath, string.Format(
					"{0:yyyy-MM-dd},{1},{2},{3:HH:mm:ss},{4},{5},{6},{7:HH:mm:ss},{8:HH:mm:ss}," +
					"{9},{10},{11},{12},{13},{14},{15:F2},{16:F2},{17},{18}{19}",
					sessionDate, direction == 1 ? "long" : "short", inversion.Slot.Label, sweptAt,
					sweepExtreme, inversion.Gap.Bottom, inversion.Gap.Top, inversion.Gap.FormedAt,
					closeTime, entry, stop, target, quantity, risk, reward, reward / risk,
					risk * pointValue * quantity, rangeHigh, rangeLow, Environment.NewLine));
			}
			catch (Exception error)
			{
				Print("CSV export failed: " + error.Message);
			}
		}

		private void LogLine(string message)
		{
			if (LogDetail)
				Print(string.Format("{0:yyyy-MM-dd}  {1}", sessionDate, message));
		}

		private string Format(double price)
		{
			return price.ToString("F2");
		}

		private string SecondsLabel(int seconds)
		{
			return seconds % 60 == 0 ? (seconds / 60) + "m" : seconds + "s";
		}

		#endregion

		#region Drawing

		private void DrawLevels(DateTime closeTime)
		{
			if (!ShowDrawings || !rangeValid)
				return;

			string stamp		= sessionDate.ToString("yyyyMMdd");
			DateTime windowOpen	= sessionDate.AddSeconds(rangeEndSec);
			DateTime windowEnd	= sessionDate.AddSeconds(tradeEndSec);

			Draw.Line(this, "asiaHigh" + stamp, false, windowOpen, rangeHigh, windowEnd, rangeHigh,
				Brushes.Goldenrod, DashStyleHelper.Dash, 2);
			Draw.Line(this, "asiaLow" + stamp, false, windowOpen, rangeLow, windowEnd, rangeLow,
				Brushes.IndianRed, DashStyleHelper.Dash, 2);
		}

		private void DrawTrade(Inversion inversion, DateTime closeTime, double entry, double stop, double target)
		{
			if (!ShowDrawings)
				return;

			string stamp	= sessionDate.ToString("yyyyMMdd");
			DateTime start	= inversion.Gap.FormedAt;
			DateTime finish	= closeTime.AddMinutes(45);

			Draw.Rectangle(this, "asiaGap" + stamp, false, start, inversion.Gap.Bottom, closeTime,
				inversion.Gap.Top, Brushes.DimGray, Brushes.SlateGray, 30);
			Draw.Line(this, "asiaEntry" + stamp, false, closeTime, entry, finish, entry,
				Brushes.White, DashStyleHelper.Solid, 2);
			Draw.Line(this, "asiaStop" + stamp, false, closeTime, stop, finish, stop,
				Brushes.Firebrick, DashStyleHelper.Solid, 2);
			Draw.Line(this, "asiaTarget" + stamp, false, closeTime, target, finish, target,
				Brushes.SeaGreen, DashStyleHelper.Solid, 2);
			Draw.Text(this, "asiaLabel" + stamp, false, inversion.Slot.Label + " IFVG", closeTime, entry, 12,
				Brushes.White, new SimpleFont("Arial", 11), System.Windows.TextAlignment.Left,
				Brushes.Transparent, Brushes.Transparent, 0);
		}

		#endregion

		#region Properties

		[NinjaScriptProperty]
		[Range(1, double.MaxValue)]
		[Display(Name = "Risk per trade ($)", Order = 1, GroupName = "1. Risk")]
		public double RiskDollars { get; set; }

		[NinjaScriptProperty]
		[Range(0, int.MaxValue)]
		[Display(Name = "Max contracts (0 = no cap)", Order = 2, GroupName = "1. Risk")]
		public int MaxContracts { get; set; }

		[NinjaScriptProperty]
		[Range(0, double.MaxValue)]
		[Display(Name = "Minimum reward:risk (0 = off)", Order = 3, GroupName = "1. Risk")]
		public double MinimumRewardRisk { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Entry model", Order = 1, GroupName = "2. Entry")]
		public AsiaIfvgEntryMode EntryMode { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use 30 second", Order = 2, GroupName = "2. Entry")]
		public bool Use30Second { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use 1 minute", Order = 3, GroupName = "2. Entry")]
		public bool Use1Minute { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use 2 minute", Order = 4, GroupName = "2. Entry")]
		public bool Use2Minute { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use 3 minute", Order = 5, GroupName = "2. Entry")]
		public bool Use3Minute { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Use 5 minute", Order = 6, GroupName = "2. Entry")]
		public bool Use5Minute { get; set; }

		[NinjaScriptProperty]
		[Range(0, 2359)]
		[Display(Name = "Range start (HHmm, chart time)", Order = 1, GroupName = "3. Session")]
		public int RangeStartTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 2359)]
		[Display(Name = "Range end (HHmm, chart time)", Order = 2, GroupName = "3. Session")]
		public int RangeEndTime { get; set; }

		[NinjaScriptProperty]
		[Range(0, 2359)]
		[Display(Name = "Last entry (HHmm, chart time)", Order = 3, GroupName = "3. Session")]
		public int TradeEndTime { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Sunday", Order = 1, GroupName = "4. Days")]
		public bool TradeSunday { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Monday", Order = 2, GroupName = "4. Days")]
		public bool TradeMonday { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Tuesday", Order = 3, GroupName = "4. Days")]
		public bool TradeTuesday { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Wednesday", Order = 4, GroupName = "4. Days")]
		public bool TradeWednesday { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Thursday", Order = 5, GroupName = "4. Days")]
		public bool TradeThursday { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Draw levels and gaps", Order = 1, GroupName = "5. Output")]
		public bool ShowDrawings { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Log to output window", Order = 2, GroupName = "5. Output")]
		public bool LogDetail { get; set; }

		[NinjaScriptProperty]
		[Display(Name = "Export CSV path (blank = off)", Order = 3, GroupName = "5. Output")]
		public string ExportCsvPath { get; set; }

		#endregion
	}
}
