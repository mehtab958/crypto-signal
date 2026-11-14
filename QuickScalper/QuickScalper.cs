// QuickScalper for cTrader
// Scalper for the 1-minute chart: several small positions, each closed at a
// small money profit or a fixed money loss. Start it on an m1 chart.
// Test on a demo account first.
using System;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class QuickScalper : Robot
    {
        [Parameter("Lots per trade", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double Lots { get; set; }

        [Parameter("Max open trades", DefaultValue = 3, MinValue = 1, MaxValue = 10)]
        public int MaxPositions { get; set; }

        [Parameter("Close at profit (money)", DefaultValue = 1.0, MinValue = 0.1)]
        public double ProfitTarget { get; set; }

        [Parameter("Close at loss (money)", DefaultValue = 2.0, MinValue = 0.1)]
        public double StopLoss { get; set; }

        [Parameter("Daily loss limit (money)", DefaultValue = 10.0, MinValue = 1)]
        public double DailyLossLimit { get; set; }

        [Parameter("Max spread (pips)", DefaultValue = 2.0, MinValue = 0.1)]
        public double MaxSpreadPips { get; set; }

        [Parameter("Seconds between new trades", DefaultValue = 30, MinValue = 0)]
        public int SecondsBetweenOpen { get; set; }

        [Parameter("Fast EMA", DefaultValue = 9, MinValue = 2)]
        public int FastPeriod { get; set; }

        [Parameter("Slow EMA", DefaultValue = 21, MinValue = 3)]
        public int SlowPeriod { get; set; }

        [Parameter("Trend EMA", DefaultValue = 50, MinValue = 5)]
        public int TrendPeriod { get; set; }

        [Parameter("RSI period", DefaultValue = 7, MinValue = 2)]
        public int RsiPeriod { get; set; }

        [Parameter("RSI buy below", DefaultValue = 35, MinValue = 1, MaxValue = 99)]
        public double RsiBuyBelow { get; set; }

        [Parameter("RSI sell above", DefaultValue = 65, MinValue = 1, MaxValue = 99)]
        public double RsiSellAbove { get; set; }

        private const string Label = "QuickScalper";

        private ExponentialMovingAverage _fast;
        private ExponentialMovingAverage _slow;
        private ExponentialMovingAverage _trend;
        private RelativeStrengthIndex _rsi;
        private DateTime _lastOpen = DateTime.MinValue;
        private int _signal;   // +1 buy, -1 sell, 0 none; set once per closed bar

        protected override void OnStart()
        {
            _fast = Indicators.ExponentialMovingAverage(Bars.ClosePrices, FastPeriod);
            _slow = Indicators.ExponentialMovingAverage(Bars.ClosePrices, SlowPeriod);
            _trend = Indicators.ExponentialMovingAverage(Bars.ClosePrices, TrendPeriod);
            _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, RsiPeriod);
            Print("QuickScalper started on {0} {1}", SymbolName, TimeFrame);
        }

        protected override void OnBar()
        {
            _signal = ReadSignal();
        }

        protected override void OnTick()
        {
            double floating = 0;
            int open = 0;

            // Close trades that reached the money target or the money stop
            foreach (var position in Positions.FindAll(Label, SymbolName))
            {
                if (position.NetProfit >= ProfitTarget || position.NetProfit <= -StopLoss)
                {
                    var result = ClosePosition(position);
                    if (result.IsSuccessful)
                        continue;
                    Print("Close failed: {0}", result.Error);
                }
                floating += position.NetProfit;
                open++;
            }

            if (_signal == 0 || open >= MaxPositions)
                return;
            if ((Server.Time - _lastOpen).TotalSeconds < SecondsBetweenOpen)
                return;
            if ((Server.Time - Bars.OpenTimes.LastValue).TotalSeconds > 20)   // only act early in the bar
                return;
            if (Symbol.Spread / Symbol.PipSize > MaxSpreadPips)
                return;
            if (TodayClosedProfit() + floating <= -DailyLossLimit)
                return;

            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(Lots), RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin)
                volume = Symbol.VolumeInUnitsMin;

            // Server-side stop and target, so trades stay protected if the bot stops
            double pipMoney = Symbol.PipValue * volume;
            if (pipMoney <= 0)
                return;
            double slPips = Math.Max(1, Math.Round(StopLoss / pipMoney, 1));
            double tpPips = Math.Max(1, Math.Round(ProfitTarget / pipMoney, 1));

            var tradeType = _signal > 0 ? TradeType.Buy : TradeType.Sell;
            var order = ExecuteMarketOrder(tradeType, SymbolName, volume, Label, slPips, tpPips);
            if (order.IsSuccessful)
                _lastOpen = Server.Time;
            else
                Print("Order failed: {0}", order.Error);
        }

        // Signal from the last closed bar: trend + RSI pullback + turn back with the trend
        private int ReadSignal()
        {
            if (Bars.Count < TrendPeriod + 10)
                return 0;

            double close = Bars.ClosePrices.Last(1);
            double open = Bars.OpenPrices.Last(1);
            double rsiNow = _rsi.Result.Last(1);
            double rsiPrev = _rsi.Result.Last(2);
            double rsiLow = Math.Min(_rsi.Result.Last(2), Math.Min(_rsi.Result.Last(3), _rsi.Result.Last(4)));
            double rsiHigh = Math.Max(_rsi.Result.Last(2), Math.Max(_rsi.Result.Last(3), _rsi.Result.Last(4)));

            bool up = close > _trend.Result.Last(1) && _slow.Result.Last(1) > _trend.Result.Last(1);
            bool down = close < _trend.Result.Last(1) && _slow.Result.Last(1) < _trend.Result.Last(1);

            if (up && rsiLow < RsiBuyBelow && close > open && close > _fast.Result.Last(1) && rsiNow > rsiPrev)
                return 1;
            if (down && rsiHigh > RsiSellAbove && close < open && close < _fast.Result.Last(1) && rsiNow < rsiPrev)
                return -1;
            return 0;
        }

        // Closed profit/loss of this bot on this symbol since the start of today (server time)
        private double TodayClosedProfit()
        {
            var today = Server.Time.Date;
            return History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName && t.ClosingTime.Date == today)
                .Sum(t => t.NetProfit);
        }
    }
}
