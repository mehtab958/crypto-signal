// RajaVsa for cTrader - Malaysian SnR (Raja Banks style) entries that must be
// confirmed by Volume Spread Analysis. Built for gold (XAUUSD); works on any symbol.
//
// A trade needs ALL of these at the same time:
//  1. Storyline: on the higher timeframe (default 4-hour) the latest wick
//     rejection of a fresh level sets the direction.
//  2. SnR entry: on the chart timeframe (start it on m15) the candle that just
//     closed wicked into a fresh A / V / gap / RBS / SBR level on the storyline's
//     side and closed back.
//  3. VSA confirmation: that candle, or the one before it, shows strength for a
//     buy (stopping volume, spring, no supply, effort without result, or a
//     demand bar) or weakness for a sell (buying climax, upthrust, no demand,
//     effort without result, or a supply bar).
// Stop beyond the rejection wick. Target = next fresh higher-timeframe level
// (or a fixed multiple of the risk). Stop moves to break-even at 1x risk.
// Expect few trades. Test on a demo account first.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class RajaVsa : Robot
    {
        [Parameter("Lots per trade", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double Lots { get; set; }

        [Parameter("Max open trades", DefaultValue = 2, MinValue = 1, MaxValue = 10)]
        public int MaxPositions { get; set; }

        [Parameter("Max risk per trade (money)", DefaultValue = 10.0, MinValue = 0.5)]
        public double MaxRiskMoney { get; set; }

        [Parameter("Daily loss limit (money, 0 = off)", DefaultValue = 20.0, MinValue = 0)]
        public double DailyLossLimit { get; set; }

        [Parameter("Storyline timeframe", DefaultValue = "Hour4", Group = "Storyline")]
        public TimeFrame StorylineTimeFrame { get; set; }

        [Parameter("Storyline lasts (storyline candles)", DefaultValue = 12, MinValue = 1, Group = "Storyline")]
        public int StorylineBars { get; set; }

        [Parameter("Candles scanned for levels", DefaultValue = 300, MinValue = 50, MaxValue = 1000, Group = "Levels")]
        public int Lookback { get; set; }

        [Parameter("Use gap levels", DefaultValue = true, Group = "Levels")]
        public bool UseGapLevels { get; set; }

        [Parameter("Fixed reward : risk (0 = aim for the next level)", DefaultValue = 0.0, MinValue = 0, Step = 0.5, Group = "Exits")]
        public double FixedRewardRisk { get; set; }

        [Parameter("Learn from its own results", DefaultValue = true, Group = "Learning")]
        public bool UseLearning { get; set; }

        [Parameter("Judge a setup type on its last trades", DefaultValue = 15, MinValue = 5, MaxValue = 100, Group = "Learning")]
        public int LearnTrades { get; set; }

        [Parameter("Trades needed before judging", DefaultValue = 5, MinValue = 3, MaxValue = 50, Group = "Learning")]
        public int LearnMinTrades { get; set; }

        [Parameter("A losing setup type rests for (hours)", DefaultValue = 24, MinValue = 1, Group = "Learning")]
        public int LearnRestHours { get; set; }

        [Parameter("Need VSA confirmation", DefaultValue = true, Group = "VSA")]
        public bool NeedVsa { get; set; }

        [Parameter("High volume = this x average", DefaultValue = 2.0, MinValue = 1.2, Step = 0.1, Group = "VSA")]
        public double HighVolume { get; set; }

        [Parameter("Low volume = this x average", DefaultValue = 0.8, MinValue = 0.3, MaxValue = 1.0, Step = 0.1, Group = "VSA")]
        public double LowVolume { get; set; }

        [Parameter("Minimum reward : risk", DefaultValue = 1.5, MinValue = 0.5, Step = 0.1, Group = "Exits")]
        public double MinRewardRisk { get; set; }

        [Parameter("Reward : risk when no target level exists", DefaultValue = 2.0, MinValue = 0.5, Step = 0.1, Group = "Exits")]
        public double FallbackRewardRisk { get; set; }

        [Parameter("Move stop to break-even at 1x risk", DefaultValue = true, Group = "Exits")]
        public bool UseBreakEven { get; set; }

        private const string Label = "RajaVsa";

        private class Level
        {
            public double Price;
            public bool IsResistance;
            public bool Fresh = true;
            public int Uses;
            public int Flips;
            public int Born;
            public string Kind;
            public bool Dead;
        }

        private class Rejection
        {
            public int Bar = -1;
            public int Direction;      // +1 bullish (support held), -1 bearish (resistance held)
            public double Price;
            public string Kind = "";
        }

        private Bars _story;
        private AverageTrueRange _atr;
        private ExponentialMovingAverage _trend;
        private readonly HashSet<string> _usedLevels = new HashSet<string>();
        private string _lastStoryText = "";
        private DateTime _lastStatus = DateTime.MinValue;
        private DateTime _lastReport = DateTime.MinValue;

        protected override void OnStart()
        {
            _story = MarketData.GetBars(StorylineTimeFrame);
            _atr = Indicators.AverageTrueRange(14, MovingAverageType.Simple);
            _trend = Indicators.ExponentialMovingAverage(Bars.ClosePrices, 50);
            Print("RajaVsa started on {0} {1}, storyline {2}, account {3}", SymbolName, TimeFrame, StorylineTimeFrame, Account.IsLive ? "LIVE" : "demo");
        }

        // Walk the candles forward, creating levels and applying the fresh / unfresh / flip rules.
        // Returns the surviving levels and the most recent wick rejection of a fresh level.
        private List<Level> Scan(Bars b, out Rejection lastRejection)
        {
            var levels = new List<Level>();
            lastRejection = new Rejection();
            int end = b.Count - 2;                       // last closed candle
            int start = Math.Max(22, end - Lookback);
            if (end <= start)
                return levels;

            for (int j = start; j <= end; j++)
            {
                double open = b.OpenPrices[j], close = b.ClosePrices[j], high = b.HighPrices[j], low = b.LowPrices[j];

                // 1. Existing levels meet candle j
                foreach (var lv in levels)
                {
                    if (lv.Dead || lv.Born >= j)
                        continue;
                    if (lv.IsResistance)
                    {
                        if (close > lv.Price)
                        {
                            lv.IsResistance = false; lv.Fresh = true; lv.Flips++; lv.Kind = "RBS";
                        }
                        else if (high >= lv.Price)
                        {
                            if (lv.Fresh)
                                lastRejection = new Rejection { Bar = j, Direction = -1, Price = lv.Price, Kind = lv.Kind };
                            lv.Fresh = false; lv.Uses++;
                        }
                    }
                    else
                    {
                        if (close < lv.Price)
                        {
                            lv.IsResistance = true; lv.Fresh = true; lv.Flips++; lv.Kind = "SBR";
                        }
                        else if (low <= lv.Price)
                        {
                            if (lv.Fresh)
                                lastRejection = new Rejection { Bar = j, Direction = 1, Price = lv.Price, Kind = lv.Kind };
                            lv.Fresh = false; lv.Uses++;
                        }
                    }
                    if (lv.Uses > 2 || lv.Flips > 2)
                        lv.Dead = true;
                }

                // 2. New levels from the pair of candles (j-1, j), at the close of candle j-1
                double prevOpen = b.OpenPrices[j - 1], prevClose = b.ClosePrices[j - 1];
                bool prevBull = prevClose > prevOpen, prevBear = prevClose < prevOpen;
                bool curBull = close > open, curBear = close < open;
                if (prevBull && curBear)
                    levels.Add(new Level { Price = prevClose, IsResistance = true, Born = j, Kind = "A" });
                else if (prevBear && curBull)
                    levels.Add(new Level { Price = prevClose, IsResistance = false, Born = j, Kind = "V" });
                else if (UseGapLevels && ((prevBull && curBull) || (prevBear && curBear)))
                {
                    double avgBody = 0;
                    for (int k = j - 21; k < j - 1; k++)
                        avgBody += Math.Abs(b.ClosePrices[k] - b.OpenPrices[k]);
                    avgBody /= 20;
                    if (avgBody > 0 && Math.Abs(prevClose - prevOpen) >= 1.5 * avgBody && Math.Abs(close - open) >= 1.5 * avgBody)
                        levels.Add(new Level { Price = prevClose, IsResistance = curBear, Born = j, Kind = "GAP" });
                }
            }
            return levels.Where(l => !l.Dead).ToList();
        }

        protected override void OnBar()
        {
            if (_story.Count < 40 || Bars.Count < 40)
                return;
            if (UseLearning)
                DailyReport();

            // Storyline from the higher timeframe
            Rejection storyRejection;
            var storyLevels = Scan(_story, out storyRejection);
            int storyEnd = _story.Count - 2;
            int story = storyRejection.Bar >= 0 && storyEnd - storyRejection.Bar <= StorylineBars ? storyRejection.Direction : 0;

            string storyText = story == 0 ? "none" : string.Format(CultureInfo.InvariantCulture, "{0} (rejected {1} level {2})", story > 0 ? "BULLISH" : "BEARISH", storyRejection.Kind, storyRejection.Price);
            if (storyText != _lastStoryText)
            {
                _lastStoryText = storyText;
                Print("Storyline: {0}", storyText);
            }
            if (story == 0)
                return;

            // Entry: the candle that just closed rejected a fresh level on the storyline's side
            Rejection entry;
            Scan(Bars, out entry);
            int last = Bars.Count - 2;
            if (entry.Bar != last || entry.Direction != story)
                return;

            string key = entry.Price.ToString("0.00000", CultureInfo.InvariantCulture);
            if (_usedLevels.Contains(key))
                return;

            // VSA must agree, on the rejection candle or the one before it
            string vsaName = "";
            if (NeedVsa)
            {
                string nameNow, nameBefore;
                int now = ReadVsa(last, out nameNow);
                int before = ReadVsa(last - 1, out nameBefore);
                if (now == story) vsaName = nameNow;
                else if (before == story && now == 0) vsaName = nameBefore;
                else
                {
                    Print("Setup skipped: {0} level {1} rejected, but no VSA confirmation", entry.Kind, entry.Price.ToString(CultureInfo.InvariantCulture));
                    return;
                }
            }
            // Self-learning: a level type or VSA signal whose own recent trades lost money rests for a while
            if (UseLearning && (IsLosing(0, entry.Kind) || (vsaName.Length > 0 && IsLosing(2, vsaName))))
            {
                Print("Setup skipped by learning: '{0}' or '{1}' has been losing recently", entry.Kind, vsaName);
                return;
            }
            if (Positions.FindAll(Label, SymbolName).Length >= MaxPositions)
            {
                Print("Setup skipped: maximum trades already open");
                return;
            }
            if (DailyLossLimit > 0 && TodayClosedProfit() <= -DailyLossLimit)
            {
                Print("Setup skipped: daily loss limit reached");
                return;
            }

            double buffer = _atr.Result.Last(1) * 0.25;
            double price = story > 0 ? Symbol.Ask : Symbol.Bid;
            double stop = story > 0 ? Bars.LowPrices[last] - buffer : Bars.HighPrices[last] + buffer + Symbol.Spread;
            double risk = Math.Abs(price - stop);
            if (risk <= 0)
                return;

            // Target: nearest fresh storyline-timeframe level ahead of price
            var ahead = storyLevels
                .Where(l => l.Fresh && (story > 0 ? l.IsResistance && l.Price > price : !l.IsResistance && l.Price < price))
                .OrderBy(l => Math.Abs(l.Price - price))
                .FirstOrDefault();
            double reward;
            string targetText;
            if (FixedRewardRisk > 0)
            {
                reward = risk * FixedRewardRisk;
                targetText = string.Format(CultureInfo.InvariantCulture, "target {0}x the risk", FixedRewardRisk);
            }
            else if (ahead == null)
            {
                reward = risk * FallbackRewardRisk;
                targetText = "no level ahead, using fixed reward";
            }
            else
            {
                reward = Math.Abs(ahead.Price - price);
                targetText = string.Format(CultureInfo.InvariantCulture, "target {0} level {1}", ahead.Kind, ahead.Price);
                if (reward / risk < MinRewardRisk)
                {
                    Print("Setup skipped: roadblock, {0} is only {1:0.0}x the risk", targetText, reward / risk);
                    return;
                }
            }

            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(Lots), RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin)
                volume = Symbol.VolumeInUnitsMin;
            double slPips = Math.Round(risk / Symbol.PipSize, 1);
            double tpPips = Math.Round(reward / Symbol.PipSize, 1);
            double riskMoney = slPips * Symbol.PipValue * volume;
            if (riskMoney > MaxRiskMoney)
            {
                Print("Setup skipped: stop would risk {0:0.00}, above the {1:0.00} limit", riskMoney, MaxRiskMoney);
                return;
            }

            _usedLevels.Add(key);
            var type = story > 0 ? TradeType.Buy : TradeType.Sell;
            string comment = entry.Kind + "|" + (story > 0 ? "bull" : "bear") + "|" + vsaName;
            var result = ExecuteMarketOrder(type, SymbolName, volume, Label, slPips, tpPips, comment);
            if (result.IsSuccessful)
                Print("{0} at {1} level {2}, VSA '{3}': risk {4:0.00}, {5}", type, entry.Kind, entry.Price.ToString(CultureInfo.InvariantCulture), vsaName, riskMoney, targetText);
            else
                Print("Order failed: {0}", result.Error);
        }

        protected override void OnTick()
        {
            if ((Server.Time - _lastStatus).TotalMinutes >= 60)
            {
                _lastStatus = Server.Time;
                Print("Running. Storyline: {0}. Open trades: {1}.", _lastStoryText.Length == 0 ? "not read yet" : _lastStoryText, Positions.FindAll(Label, SymbolName).Length);
            }

            if (!UseBreakEven)
                return;
            foreach (var position in Positions.FindAll(Label, SymbolName))
            {
                if (!position.StopLoss.HasValue)
                    continue;
                double stop = position.StopLoss.Value;
                bool buy = position.TradeType == TradeType.Buy;
                bool alreadySafe = buy ? stop >= position.EntryPrice : stop <= position.EntryPrice;
                if (alreadySafe)
                    continue;
                double riskPips = Math.Abs(position.EntryPrice - stop) / Symbol.PipSize;
                if (position.Pips >= riskPips)
                {
                    var result = ModifyPosition(position, position.EntryPrice, position.TakeProfit);
                    if (result.IsSuccessful)
                        Print("Stop moved to break-even on position {0}", position.Id);
                }
            }
        }

        // Trade comments look like "V|bull|spring": part 0 is the level type, part 2 the VSA signal
        private static string Part(string comment, int index)
        {
            var parts = (comment ?? "").Split('|');
            return parts.Length > index ? parts[index] : "";
        }

        private List<HistoricalTrade> RecentOf(int part, string value)
        {
            return History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName && Part(t.Comment, part) == value)
                .OrderByDescending(t => t.ClosingTime)
                .Take(LearnTrades)
                .ToList();
        }

        private bool IsLosing(int part, string value)
        {
            var mine = RecentOf(part, value);
            return mine.Count >= LearnMinTrades
                && mine.Sum(t => t.NetProfit) < 0
                && mine[0].ClosingTime > Server.Time.AddHours(-LearnRestHours);
        }

        // Once a day, write what the bot has learned so far to the log
        private void DailyReport()
        {
            if (Server.Time.Date == _lastReport.Date)
                return;
            _lastReport = Server.Time;
            var all = History.Where(t => t.Label == Label && t.SymbolName == SymbolName).ToList();
            if (all.Count == 0)
            {
                Print("Daily learning report: no closed trades yet");
                return;
            }
            Print("Daily learning report: {0} trades, total {1:0.00}", all.Count, all.Sum(t => t.NetProfit));
            foreach (int part in new[] { 0, 2 })
            {
                foreach (var group in all.GroupBy(t => Part(t.Comment, part)).Where(g => g.Key.Length > 0))
                {
                    var recent = RecentOf(part, group.Key);
                    Print("  {0} '{1}': last {2} trades net {3:0.00}{4}", part == 0 ? "level" : "VSA", group.Key, recent.Count,
                        recent.Sum(t => t.NetProfit), IsLosing(part, group.Key) ? " -> resting" : "");
                }
            }
        }

        // VSA reading of candle i on the chart timeframe: +1 strength, -1 weakness, 0 nothing
        private int ReadVsa(int i, out string name)
        {
            name = "";
            double avgVolume = 0, avgSpread = 0, highest = double.MinValue, lowest = double.MaxValue;
            for (int j = i - 20; j < i; j++)
            {
                avgVolume += Bars.TickVolumes[j];
                avgSpread += Bars.HighPrices[j] - Bars.LowPrices[j];
                highest = Math.Max(highest, Bars.HighPrices[j]);
                lowest = Math.Min(lowest, Bars.LowPrices[j]);
            }
            avgVolume /= 20;
            avgSpread /= 20;
            double high = Bars.HighPrices[i], low = Bars.LowPrices[i], close = Bars.ClosePrices[i];
            double spread = high - low, volume = Bars.TickVolumes[i];
            if (spread <= 0 || avgVolume <= 0 || avgSpread <= 0)
                return 0;
            double closePosition = (close - low) / spread;      // 0 = closed on the low, 1 = on the high
            bool up = close > Bars.ClosePrices[i - 1], down = close < Bars.ClosePrices[i - 1];
            bool highVol = volume >= HighVolume * avgVolume, lowVol = volume <= LowVolume * avgVolume;
            bool wide = spread >= 1.3 * avgSpread, narrow = spread <= 0.7 * avgSpread;

            if (down && highVol && wide && closePosition >= 0.5 && low <= lowest) { name = "stopping volume"; return 1; }
            if (low < lowest && close > lowest && closePosition >= 0.6 && volume >= 1.2 * avgVolume) { name = "spring"; return 1; }
            if (up && highVol && wide && closePosition <= 0.5 && high >= highest) { name = "buying climax"; return -1; }
            if (high > highest && close < highest && closePosition <= 0.4 && volume >= 1.2 * avgVolume) { name = "upthrust"; return -1; }
            if (highVol && narrow)
            {
                if (up && close > Bars.ClosePrices[i - 5]) { name = "effort no result"; return -1; }
                if (down && close < Bars.ClosePrices[i - 5]) { name = "effort no result"; return 1; }
            }
            bool quieter = volume < Bars.TickVolumes[i - 1] && volume < Bars.TickVolumes[i - 2];
            if (down && narrow && lowVol && quieter && close > _trend.Result[i]) { name = "no supply"; return 1; }
            if (up && narrow && lowVol && quieter && close < _trend.Result[i]) { name = "no demand"; return -1; }
            // A rejection candle on clearly above-average volume that closes in its favourable part
            if (volume >= 1.3 * avgVolume && closePosition >= 0.65) { name = "demand bar"; return 1; }
            if (volume >= 1.3 * avgVolume && closePosition <= 0.35) { name = "supply bar"; return -1; }
            return 0;
        }

        private double TodayClosedProfit()
        {
            var today = Server.Time.Date;
            return History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName && t.ClosingTime >= today)
                .Sum(t => t.NetProfit);
        }
    }
}
