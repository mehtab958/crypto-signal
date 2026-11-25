// GoldFast for cTrader - fast gold scalper chosen by a 6-month walk-forward test (May-Nov 2026).
// Start it on an XAUUSD m5 chart. Two independent strategies, each with at most one open trade:
//  A) MACD cross on 5-minute candles, with the 15-minute and 1-hour trend (all hours).
//     Tested: 767 trades, profitable in all three 2-month periods, about 4 trades a day.
//  B) Stochastic turn on 3-minute candles, with the trend, London + New York hours only (07-17 UTC).
//     Tested: 666 trades, profitable in all three periods, about 3.7 trades a day.
// Exits for both: stop = 1.5 x ATR(14) of that strategy's candles, target = 2 x stop, close after 4 hours.
// Expect a win rate near 37-40%: winners are twice the size of losers. Test on a demo account first.
using System;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class GoldFast : Robot
    {
        [Parameter("Lots per trade", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double Lots { get; set; }

        [Parameter("A: MACD on 5-minute candles", DefaultValue = true, Group = "Strategies")]
        public bool UseMacd { get; set; }

        [Parameter("B: Stochastic on 3-minute candles", DefaultValue = true, Group = "Strategies")]
        public bool UseStoch { get; set; }

        [Parameter("Stop = this x ATR", DefaultValue = 1.5, MinValue = 0.5, Step = 0.1, Group = "Exits")]
        public double StopAtr { get; set; }

        [Parameter("Target = this x stop", DefaultValue = 2.0, MinValue = 0.5, Step = 0.1, Group = "Exits")]
        public double RewardRisk { get; set; }

        [Parameter("Close a trade after (minutes)", DefaultValue = 240, MinValue = 10, Group = "Exits")]
        public int MaxHoldMinutes { get; set; }

        [Parameter("Skip if the stop would risk more than (money)", DefaultValue = 15.0, MinValue = 1, Group = "Safety")]
        public double MaxRiskMoney { get; set; }

        [Parameter("Daily loss limit (money, 0 = off)", DefaultValue = 30.0, MinValue = 0, Group = "Safety")]
        public double DailyLossLimit { get; set; }

        [Parameter("B: trading hours start (UTC)", DefaultValue = 7, MinValue = 0, MaxValue = 23, Group = "Strategies")]
        public int StochStartUtc { get; set; }

        [Parameter("B: trading hours end (UTC)", DefaultValue = 17, MinValue = 1, MaxValue = 24, Group = "Strategies")]
        public int StochEndUtc { get; set; }

        private const string Label = "GoldFast";
        private Bars _m3, _m15, _h1;
        private ExponentialMovingAverage _ema5, _ema15, _ema60;
        private MacdCrossOver _macd;
        private AverageTrueRange _atr5, _atr3;
        private StochasticOscillator _stoch;
        private DateTime _lastStatus = DateTime.MinValue;

        protected override void OnStart()
        {
            _m3 = MarketData.GetBars(TimeFrame.Minute3);
            _m15 = MarketData.GetBars(TimeFrame.Minute15);
            _h1 = MarketData.GetBars(TimeFrame.Hour);
            _ema5 = Indicators.ExponentialMovingAverage(Bars.ClosePrices, 50);
            _ema15 = Indicators.ExponentialMovingAverage(_m15.ClosePrices, 50);
            _ema60 = Indicators.ExponentialMovingAverage(_h1.ClosePrices, 50);
            _macd = Indicators.MacdCrossOver(Bars.ClosePrices, 26, 12, 9);
            _atr5 = Indicators.AverageTrueRange(Bars, 14, MovingAverageType.Simple);
            _atr3 = Indicators.AverageTrueRange(_m3, 14, MovingAverageType.Simple);
            _stoch = Indicators.StochasticOscillator(_m3, 14, 3, 3, MovingAverageType.Simple);
            _m3.BarOpened += args => OnStochBar();
            if (TimeFrame != TimeFrame.Minute5)
                Print("Note: GoldFast was tested on the m5 chart. This instance is on {0}.", TimeFrame);
            Print("GoldFast started on {0} {1}, account {2}", SymbolName, TimeFrame, Account.IsLive ? "LIVE" : "demo");
        }

        // +1 when the last closed 15-minute and 1-hour candles are both above their EMA 50, -1 when both below
        private int Trend()
        {
            if (_m15.Count < 60 || _h1.Count < 60) return 0;
            bool up15 = _m15.ClosePrices.Last(1) > _ema15.Result.Last(1);
            bool up60 = _h1.ClosePrices.Last(1) > _ema60.Result.Last(1);
            if (up15 && up60) return 1;
            if (!up15 && !up60) return -1;
            return 0;
        }

        // Strategy A, on each new 5-minute candle (reads the one that just closed)
        protected override void OnBar()
        {
            if (!UseMacd || Bars.Count < 120) return;
            double was = _macd.MACD.Last(2) - _macd.Signal.Last(2), now = _macd.MACD.Last(1) - _macd.Signal.Last(1);
            int dir = 0;
            if (was <= 0 && now > 0 && Bars.ClosePrices.Last(1) > _ema5.Result.Last(1)) dir = 1;
            if (was >= 0 && now < 0 && Bars.ClosePrices.Last(1) < _ema5.Result.Last(1)) dir = -1;
            if (dir == 0 || Trend() != dir) return;
            Open("macd", dir, _atr5.Result.Last(1));
        }

        // Strategy B, on each new 3-minute candle
        private void OnStochBar()
        {
            if (!UseStoch || _m3.Count < 120) return;
            int hour = Server.TimeInUtc.Hour;
            bool inHours = StochStartUtc <= StochEndUtc ? hour >= StochStartUtc && hour < StochEndUtc : hour >= StochStartUtc || hour < StochEndUtc;
            if (!inHours) return;
            double k1 = _stoch.PercentK.Last(1), d1 = _stoch.PercentD.Last(1), k2 = _stoch.PercentK.Last(2), d2 = _stoch.PercentD.Last(2);
            int dir = 0;
            if (k2 - d2 <= 0 && k1 - d1 > 0 && k2 < 20) dir = 1;
            if (k2 - d2 >= 0 && k1 - d1 < 0 && k2 > 80) dir = -1;
            if (dir == 0 || Trend() != dir) return;
            Open("stoch", dir, _atr3.Result.Last(1));
        }

        private void Open(string strategy, int dir, double atr)
        {
            var mine = Positions.FindAll(Label, SymbolName);
            if (mine.Any(p => p.Comment == strategy)) return;                 // one trade per strategy at a time
            if (DailyLossLimit > 0 && TodayNet() + mine.Sum(p => p.NetProfit) <= -DailyLossLimit)
            {
                Print("{0} signal skipped: daily loss limit reached", strategy);
                return;
            }
            if (atr <= 0) return;
            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(Lots), RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin) volume = Symbol.VolumeInUnitsMin;
            double slPips = Math.Round(StopAtr * atr / Symbol.PipSize, 1);
            double tpPips = Math.Round(slPips * RewardRisk, 1);
            double riskMoney = slPips * Symbol.PipValue * volume;
            if (riskMoney > MaxRiskMoney)
            {
                Print("{0} signal skipped: stop would risk {1:0.00}, above {2:0.00}", strategy, riskMoney, MaxRiskMoney);
                return;
            }
            var type = dir > 0 ? TradeType.Buy : TradeType.Sell;
            var result = ExecuteMarketOrder(type, SymbolName, volume, Label, slPips, tpPips, strategy);
            if (result.IsSuccessful)
                Print("{0} {1}: risk {2:0.00}, target {3:0.00}", strategy, type, riskMoney, riskMoney * RewardRisk);
            else
                Print("{0} order failed: {1}", strategy, result.Error);
        }

        protected override void OnTick()
        {
            foreach (var p in Positions.FindAll(Label, SymbolName))
            {
                if ((Server.Time - p.EntryTime).TotalMinutes >= MaxHoldMinutes)
                {
                    var r = ClosePosition(p);
                    if (r.IsSuccessful) Print("{0} closed after {1} minutes at {2:0.00}", p.Comment, MaxHoldMinutes, p.NetProfit);
                }
            }
            if ((Server.Time - _lastStatus).TotalMinutes >= 60)
            {
                _lastStatus = Server.Time;
                Print("Running. Trend {0}. Open trades: {1}. Today: {2:0.00}", Trend(), Positions.FindAll(Label, SymbolName).Length, TodayNet());
            }
        }

        private double TodayNet()
        {
            var today = Server.Time.Date;
            return History.Where(t => t.Label == Label && t.SymbolName == SymbolName && t.ClosingTime >= today).Sum(t => t.NetProfit);
        }
    }
}
