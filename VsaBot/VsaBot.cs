// VsaBot for cTrader - Volume Spread Analysis on several symbols from one instance
//
// Reads volume (tick volume), spread (candle range) and where the candle closed.
// Signals of strength (buy): stopping volume, spring, no supply, effort without result after a fall.
// Signals of weakness (sell): buying climax, upthrust, no demand, effort without result after a rise.
// A signal is traded only after the next candle confirms it (optional).
// Stop beyond the signal candle, target a multiple of the risk, all sized in money
// so the same rules work on forex, gold and crypto.
// Start ONE instance on any chart; the timeframe of that chart is used for every symbol.
// Test on a demo account first.
using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class VsaBot : Robot
    {
        [Parameter("Symbols (comma separated)", DefaultValue = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,XAUUSD,BTCUSD")]
        public string SymbolList { get; set; }

        [Parameter("Lots per trade", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double Lots { get; set; }

        [Parameter("Max open trades in total", DefaultValue = 5, MinValue = 1, MaxValue = 20)]
        public int MaxPositions { get; set; }

        [Parameter("Max risk per trade (money)", DefaultValue = 5.0, MinValue = 0.5)]
        public double MaxRiskMoney { get; set; }

        [Parameter("Reward : risk", DefaultValue = 2.0, MinValue = 0.5, Step = 0.5)]
        public double RewardRisk { get; set; }

        [Parameter("Daily loss limit (money, 0 = off)", DefaultValue = 20.0, MinValue = 0)]
        public double DailyLossLimit { get; set; }

        [Parameter("Wait for a confirming candle", DefaultValue = true)]
        public bool NeedConfirmation { get; set; }

        [Parameter("Move stop to break-even at 1x risk", DefaultValue = true)]
        public bool UseBreakEven { get; set; }

        [Parameter("High volume = this x average", DefaultValue = 2.0, MinValue = 1.2, Step = 0.1, Group = "VSA")]
        public double HighVolume { get; set; }

        [Parameter("Low volume = this x average", DefaultValue = 0.8, MinValue = 0.3, MaxValue = 1.0, Step = 0.1, Group = "VSA")]
        public double LowVolume { get; set; }

        [Parameter("Wide candle = this x average", DefaultValue = 1.3, MinValue = 1.0, Step = 0.1, Group = "VSA")]
        public double WideSpread { get; set; }

        [Parameter("Narrow candle = this x average", DefaultValue = 0.7, MinValue = 0.3, MaxValue = 1.0, Step = 0.1, Group = "VSA")]
        public double NarrowSpread { get; set; }

        private const string Label = "VsaBot";

        private class Market
        {
            public string Name;
            public Symbol Sym;
            public Bars Bars;
            public AverageTrueRange Atr;
            public ExponentialMovingAverage Trend;
        }

        private readonly List<Market> _markets = new List<Market>();

        protected override void OnStart()
        {
            foreach (var raw in SymbolList.Split(','))
            {
                string name = raw.Trim();
                if (name.Length == 0)
                    continue;
                if (!Symbols.Exists(name))
                {
                    Print("Symbol not found at this broker, skipped: {0}", name);
                    continue;
                }
                var market = new Market { Name = name, Sym = Symbols.GetSymbol(name), Bars = MarketData.GetBars(TimeFrame, name) };
                market.Atr = Indicators.AverageTrueRange(market.Bars, 14, MovingAverageType.Simple);
                market.Trend = Indicators.ExponentialMovingAverage(market.Bars.ClosePrices, 50);
                market.Bars.BarOpened += args => OnMarketBar(market);
                _markets.Add(market);
            }
            Timer.Start(5);
            Print("VsaBot started on {0}: {1}. Account {2}.", TimeFrame, string.Join(", ", _markets.Select(m => m.Name)), Account.IsLive ? "LIVE" : "demo");
        }

        // VSA reading of candle i. Returns +1 (strength), -1 (weakness) or 0, and the signal's name.
        private int Read(Market m, int i, out string name)
        {
            name = "";
            var b = m.Bars;
            double avgVolume = 0, avgSpread = 0, highest = double.MinValue, lowest = double.MaxValue;
            for (int j = i - 20; j < i; j++)
            {
                avgVolume += b.TickVolumes[j];
                avgSpread += b.HighPrices[j] - b.LowPrices[j];
                highest = Math.Max(highest, b.HighPrices[j]);
                lowest = Math.Min(lowest, b.LowPrices[j]);
            }
            avgVolume /= 20;
            avgSpread /= 20;

            double high = b.HighPrices[i], low = b.LowPrices[i], close = b.ClosePrices[i];
            double spread = high - low, volume = b.TickVolumes[i];
            if (spread <= 0 || avgVolume <= 0 || avgSpread <= 0)
                return 0;
            double closePosition = (close - low) / spread;      // 0 = closed on the low, 1 = on the high
            bool up = close > b.ClosePrices[i - 1], down = close < b.ClosePrices[i - 1];
            bool highVol = volume >= HighVolume * avgVolume, lowVol = volume <= LowVolume * avgVolume;
            bool wide = spread >= WideSpread * avgSpread, narrow = spread <= NarrowSpread * avgSpread;

            // Strength
            if (down && highVol && wide && closePosition >= 0.5 && low <= lowest) { name = "stopping volume"; return 1; }
            if (low < lowest && close > lowest && closePosition >= 0.6 && volume >= 1.2 * avgVolume) { name = "spring"; return 1; }
            // Weakness
            if (up && highVol && wide && closePosition <= 0.5 && high >= highest) { name = "buying climax"; return -1; }
            if (high > highest && close < highest && closePosition <= 0.4 && volume >= 1.2 * avgVolume) { name = "upthrust"; return -1; }
            // Effort without result: heavy volume, small candle
            if (highVol && narrow)
            {
                if (up && close > b.ClosePrices[i - 5]) { name = "effort no result (up)"; return -1; }
                if (down && close < b.ClosePrices[i - 5]) { name = "effort no result (down)"; return 1; }
            }
            // No supply / no demand: quiet narrow candle against the trend's pullback
            bool quieter = volume < b.TickVolumes[i - 1] && volume < b.TickVolumes[i - 2];
            if (down && narrow && lowVol && quieter && close > m.Trend.Result[i]) { name = "no supply"; return 1; }
            if (up && narrow && lowVol && quieter && close < m.Trend.Result[i]) { name = "no demand"; return -1; }
            return 0;
        }

        private void OnMarketBar(Market m)
        {
            var b = m.Bars;
            if (b.Count < 80)
                return;
            int last = b.Count - 2;                       // last closed candle
            int signalBar = NeedConfirmation ? last - 1 : last;

            string name;
            int direction = Read(m, signalBar, out name);
            if (direction == 0)
                return;
            if (NeedConfirmation)
            {
                bool confirmed = direction > 0 ? b.ClosePrices[last] > b.ClosePrices[signalBar] : b.ClosePrices[last] < b.ClosePrices[signalBar];
                if (!confirmed)
                    return;
            }

            var mine = Positions.FindAll(Label);
            if (mine.Any(p => p.SymbolName == m.Name))
                return;                                   // one trade per symbol
            if (mine.Length >= MaxPositions)
            {
                Print("{0}: {1} skipped, maximum trades already open", m.Name, name);
                return;
            }
            if (DailyLossLimit > 0 && TodayClosedProfit() + mine.Sum(p => p.NetProfit) <= -DailyLossLimit)
            {
                Print("{0}: {1} skipped, daily loss limit reached", m.Name, name);
                return;
            }

            var sym = m.Sym;
            double buffer = m.Atr.Result[last] * 0.25;
            double extremeLow = Math.Min(b.LowPrices[signalBar], b.LowPrices[last]);
            double extremeHigh = Math.Max(b.HighPrices[signalBar], b.HighPrices[last]);
            double price = direction > 0 ? sym.Ask : sym.Bid;
            double stop = direction > 0 ? extremeLow - buffer : extremeHigh + buffer + sym.Spread;
            double risk = Math.Abs(price - stop);
            if (risk <= 0)
                return;
            if (sym.Spread > 0.3 * risk)
            {
                Print("{0}: {1} skipped, spread too large for this stop", m.Name, name);
                return;
            }

            double volume = sym.NormalizeVolumeInUnits(sym.QuantityToVolumeInUnits(Lots), RoundingMode.Down);
            if (volume < sym.VolumeInUnitsMin)
                volume = sym.VolumeInUnitsMin;
            double slPips = Math.Round(risk / sym.PipSize, 1);
            double tpPips = Math.Round(slPips * RewardRisk, 1);
            double riskMoney = slPips * sym.PipValue * volume;
            if (riskMoney > MaxRiskMoney)
            {
                Print("{0}: {1} skipped, stop would risk {2:0.00} (limit {3:0.00})", m.Name, name, riskMoney, MaxRiskMoney);
                return;
            }

            var type = direction > 0 ? TradeType.Buy : TradeType.Sell;
            var result = ExecuteMarketOrder(type, m.Name, volume, Label, slPips, tpPips, name);
            if (result.IsSuccessful)
                Print("{0}: {1} on '{2}', risk {3:0.00}, target {4:0.00}", m.Name, type, name, riskMoney, riskMoney * RewardRisk);
            else
                Print("{0}: order failed, {1}", m.Name, result.Error);
        }

        protected override void OnTimer()
        {
            if (!UseBreakEven)
                return;
            foreach (var position in Positions.FindAll(Label))
            {
                if (!position.StopLoss.HasValue)
                    continue;
                double stop = position.StopLoss.Value;
                bool buy = position.TradeType == TradeType.Buy;
                if (buy ? stop >= position.EntryPrice : stop <= position.EntryPrice)
                    continue;
                var sym = Symbols.GetSymbol(position.SymbolName);
                double riskPips = Math.Abs(position.EntryPrice - stop) / sym.PipSize;
                if (position.Pips >= riskPips)
                {
                    var result = ModifyPosition(position, position.EntryPrice, position.TakeProfit);
                    if (result.IsSuccessful)
                        Print("{0}: stop moved to break-even", position.SymbolName);
                }
            }
        }

        private double TodayClosedProfit()
        {
            var today = Server.Time.Date;
            return History.Where(t => t.Label == Label && t.ClosingTime >= today).Sum(t => t.NetProfit);
        }
    }
}
