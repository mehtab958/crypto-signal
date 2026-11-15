// HedgeRecovery for cTrader
// "Zone recovery" hedging: when the first trade goes wrong, a bigger trade is
// opened the other way so the whole basket can still close in profit.
//  - Step 1: one trade in the direction of the trend (EMA).
//  - If price crosses to the other side of the zone, a larger opposite trade
//    is opened. This repeats, alternating sides, up to a maximum number of steps.
//  - The whole basket closes as soon as its total is in profit by the target.
//  - HARD CAPS: if the steps run out and price turns again, or the open loss
//    reaches the limit, everything is closed at a loss and the bot pauses.
// Most cycles end green. The capped losing cycle is large compared with one win.
// Needs a hedging account. Test on a demo account first.
using System;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Indicators;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class HedgeRecovery : Robot
    {
        [Parameter("First trade lots", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double StartLots { get; set; }

        [Parameter("Lot multiplier per step", DefaultValue = 2.0, MinValue = 1.0, MaxValue = 3.0, Step = 0.1)]
        public double Multiplier { get; set; }

        [Parameter("Max steps (trades per cycle)", DefaultValue = 4, MinValue = 1, MaxValue = 6)]
        public int MaxSteps { get; set; }

        [Parameter("Zone size (money on first-trade lots)", DefaultValue = 3.0, MinValue = 0.2)]
        public double ZoneMoney { get; set; }

        [Parameter("Close all at basket profit (money)", DefaultValue = 1.0, MinValue = 0.1)]
        public double CycleTarget { get; set; }

        [Parameter("Close all at basket loss (money)", DefaultValue = 30.0, MinValue = 1)]
        public double MaxBasketLoss { get; set; }

        [Parameter("Pause after a losing cycle (minutes)", DefaultValue = 30, MinValue = 0)]
        public int PauseAfterLossMinutes { get; set; }

        [Parameter("Daily loss limit (money, 0 = off)", DefaultValue = 60.0, MinValue = 0)]
        public double DailyLossLimit { get; set; }

        [Parameter("Trend EMA for first trade", DefaultValue = 50, MinValue = 5)]
        public int TrendPeriod { get; set; }

        private const string Label = "HedgeRecovery";

        private ExponentialMovingAverage _trend;
        private DateTime _pauseUntil = DateTime.MinValue;
        private DateTime _lastOrder = DateTime.MinValue;
        private DateTime _lastNote = DateTime.MinValue;

        protected override void OnStart()
        {
            _trend = Indicators.ExponentialMovingAverage(Bars.ClosePrices, TrendPeriod);
            Print("HedgeRecovery started on {0}", SymbolName);
        }

        protected override void OnTick()
        {
            var positions = Positions.FindAll(Label, SymbolName).OrderBy(p => p.EntryTime).ToArray();
            double net = positions.Sum(p => p.NetProfit);

            // 1. Basket exits
            if (positions.Length > 0 && net >= CycleTarget)
            {
                Print("Cycle closed in profit: {0:0.00} after {1} step(s)", net, positions.Length);
                CloseAll(positions);
                return;
            }
            if (positions.Length > 0 && net <= -MaxBasketLoss)
            {
                EndInLoss(positions, net, "basket loss limit reached");
                return;
            }

            // 2. Gates for opening anything new
            if (Server.Time < _pauseUntil)
                return;
            if ((Server.Time - _lastOrder).TotalSeconds < 2)
                return;

            double baseVolume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(StartLots), RoundingMode.Down);
            if (baseVolume < Symbol.VolumeInUnitsMin)
                baseVolume = Symbol.VolumeInUnitsMin;
            double pipMoney = Symbol.PipValue * baseVolume;
            if (pipMoney <= 0)
                return;
            double zonePips = Math.Max(2, Math.Round(ZoneMoney / pipMoney, 1));
            double zonePrice = zonePips * Symbol.PipSize;
            double safetyPips = zonePips * 4;   // server-side stop in case the bot is not running

            // 3. Start a new cycle
            if (positions.Length == 0)
            {
                if (DailyLossLimit > 0 && ClosedToday() <= -DailyLossLimit)
                {
                    Note("daily loss limit reached, no new cycles today");
                    return;
                }
                if (Bars.Count < TrendPeriod + 5)
                    return;
                var direction = Bars.ClosePrices.Last(1) >= _trend.Result.Last(1) ? TradeType.Buy : TradeType.Sell;
                Open(direction, baseVolume, safetyPips, "step1");
                return;
            }

            // 4. Recovery steps: the zone is fixed by the first trade of the cycle
            var first = positions[0];
            var last = positions[positions.Length - 1];
            double upper = first.TradeType == TradeType.Buy ? first.EntryPrice : first.EntryPrice + zonePrice;
            double lower = upper - zonePrice;

            bool crossedDown = last.TradeType == TradeType.Buy && Symbol.Bid <= lower;
            bool crossedUp = last.TradeType == TradeType.Sell && Symbol.Ask >= upper;
            if (!crossedDown && !crossedUp)
                return;

            if (positions.Length >= MaxSteps)
            {
                EndInLoss(positions, net, "out of recovery steps");
                return;
            }

            int step = positions.Length + 1;
            double lots = StartLots * Math.Pow(Multiplier, step - 1);
            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(lots), RoundingMode.ToNearest);
            if (volume < Symbol.VolumeInUnitsMin)
                volume = Symbol.VolumeInUnitsMin;
            Open(crossedDown ? TradeType.Sell : TradeType.Buy, volume, safetyPips, "step" + step);
        }

        private void Open(TradeType type, double volume, double slPips, string comment)
        {
            _lastOrder = Server.Time;
            var result = ExecuteMarketOrder(type, SymbolName, volume, Label, slPips, null, comment);
            if (!result.IsSuccessful)
                Print("Order failed: {0}", result.Error);
        }

        private void EndInLoss(Position[] positions, double net, string reason)
        {
            Print("Cycle closed at a loss: {0:0.00} ({1}). Pausing {2} min.", net, reason, PauseAfterLossMinutes);
            CloseAll(positions);
            _pauseUntil = Server.Time.AddMinutes(PauseAfterLossMinutes);
        }

        private void CloseAll(Position[] positions)
        {
            foreach (var position in positions)
            {
                var result = ClosePosition(position);
                if (!result.IsSuccessful)
                    Print("Close failed: {0}", result.Error);
            }
        }

        private double ClosedToday()
        {
            var today = Server.Time.Date;
            return History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName && t.ClosingTime >= today)
                .Sum(t => t.NetProfit);
        }

        private void Note(string text)
        {
            if ((Server.Time - _lastNote).TotalMinutes < 30)
                return;
            _lastNote = Server.Time;
            Print("HedgeRecovery: {0}", text);
        }
    }
}
