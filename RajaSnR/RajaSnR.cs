// RajaSnR for cTrader - Malaysian SnR (Raja Banks style), built for gold (XAUUSD)
//
// What it implements, from the publicly described rules of the method:
//  1. Levels on candle CLOSES: A-levels (resistance at a close peak), V-levels
//     (support at a close valley) and optional gap levels between two strong
//     candles of the same colour.
//  2. Fresh / unfresh: a level is fresh until a wick touches it. A body close
//     through it flips its role (resistance becomes support = RBS, support
//     becomes resistance = SBR) and makes it fresh again. A level is dropped
//     after 2 uses or 2 flips.
//  3. Storyline: on the higher timeframe (default 4-hour), the latest wick
//     rejection of a fresh level sets the direction.
//  4. Entry: on the chart timeframe (start it on m15), a candle wicks into a
//     fresh level on the storyline's side and closes back.
//  5. Stop beyond the rejection wick. Target = the next fresh higher-timeframe
//     level. A target that is too close (a "roadblock") cancels the trade.
//  6. Optional move of the stop to break-even after 1x risk in profit.
// Not implemented: Quasimodo (QM) entries, the "miss" concept, weekly/daily
// storylines stacked above the 4-hour, and the trader's own discretion.
// Test on a demo account first.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class RajaSnR : Robot
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

        [Parameter("Minimum reward : risk", DefaultValue = 1.5, MinValue = 0.5, Step = 0.1, Group = "Exits")]
        public double MinRewardRisk { get; set; }

        [Parameter("Reward : risk when no target level exists", DefaultValue = 2.0, MinValue = 0.5, Step = 0.1, Group = "Exits")]
        public double FallbackRewardRisk { get; set; }

        [Parameter("Move stop to break-even at 1x risk", DefaultValue = true, Group = "Exits")]
        public bool UseBreakEven { get; set; }

        private const string Label = "RajaSnR";

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
        private readonly HashSet<string> _usedLevels = new HashSet<string>();
        private string _lastStoryText = "";
        private DateTime _lastStatus = DateTime.MinValue;

        protected override void OnStart()
        {
            _story = MarketData.GetBars(StorylineTimeFrame);
            _atr = Indicators.AverageTrueRange(14, MovingAverageType.Simple);
            Print("RajaSnR started on {0} {1}, storyline {2}, account {3}", SymbolName, TimeFrame, StorylineTimeFrame, Account.IsLive ? "LIVE" : "demo");
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
            if (ahead == null)
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
            string comment = entry.Kind + "|" + (story > 0 ? "bull" : "bear");
            var result = ExecuteMarketOrder(type, SymbolName, volume, Label, slPips, tpPips, comment);
            if (result.IsSuccessful)
                Print("{0} at {1} level {2}: risk {3:0.00}, {4}", type, entry.Kind, entry.Price.ToString(CultureInfo.InvariantCulture), riskMoney, targetText);
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

        private double TodayClosedProfit()
        {
            var today = Server.Time.Date;
            return History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName && t.ClosingTime >= today)
                .Sum(t => t.NetProfit);
        }
    }
}
