// HedgeGrid for cTrader
// Hedged grid with FIXED lots (no martingale) and a hard loss cap.
//  - Starts each cycle with one buy and one sell at the same time.
//  - Every position takes profit one "step" away.
//  - When a side takes profit, that side is opened again.
//  - When price moves a step against a side, one more position is added on
//    that side, up to a maximum number of levels.
//  - The whole basket is closed when the cycle is up by the cycle target,
//    or when the open loss reaches the basket loss limit.
// Earns in sideways markets; takes the capped loss in strong trends.
// Needs a hedging account. Test on a demo account first.
using System;
using System.Linq;
using cAlgo.API;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None)]
    public class HedgeGrid : Robot
    {
        [Parameter("Lots per position", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double Lots { get; set; }

        [Parameter("Step: profit per position (money)", DefaultValue = 2.0, MinValue = 0.1)]
        public double StepMoney { get; set; }

        [Parameter("Max positions per side", DefaultValue = 5, MinValue = 1, MaxValue = 10)]
        public int MaxLevels { get; set; }

        [Parameter("Close all at cycle profit (money)", DefaultValue = 3.0, MinValue = 0.1)]
        public double CycleTarget { get; set; }

        [Parameter("Close all at open loss (money)", DefaultValue = 15.0, MinValue = 1)]
        public double MaxBasketLoss { get; set; }

        [Parameter("Pause after a basket loss (minutes)", DefaultValue = 15, MinValue = 0)]
        public int PauseAfterLossMinutes { get; set; }

        [Parameter("Daily loss limit (money, 0 = off)", DefaultValue = 30.0, MinValue = 0)]
        public double DailyLossLimit { get; set; }

        private const string Label = "HedgeGrid";

        private DateTime _cycleStart;
        private DateTime _pauseUntil = DateTime.MinValue;
        private DateTime _lastOrder = DateTime.MinValue;
        private DateTime _lastNote = DateTime.MinValue;

        protected override void OnStart()
        {
            _cycleStart = Server.Time;
            Print("HedgeGrid started on {0}", SymbolName);
        }

        protected override void OnTick()
        {
            var positions = Positions.FindAll(Label, SymbolName);
            double floating = positions.Sum(p => p.NetProfit);
            double closed = ClosedSince(_cycleStart);

            // 1. Basket exits
            if (positions.Length > 0 && closed + floating >= CycleTarget)
            {
                Print("Cycle target reached: {0:0.00}. Closing all.", closed + floating);
                CloseAll(positions);
                _cycleStart = Server.Time;
                return;
            }
            if (positions.Length > 0 && floating <= -MaxBasketLoss)
            {
                Print("Basket loss limit reached: {0:0.00}. Closing all and pausing.", floating);
                CloseAll(positions);
                _cycleStart = Server.Time;
                _pauseUntil = Server.Time.AddMinutes(PauseAfterLossMinutes);
                return;
            }

            // 2. Gates for opening anything new
            if (Server.Time < _pauseUntil)
                return;
            if ((Server.Time - _lastOrder).TotalSeconds < 2)
                return;
            if (DailyLossLimit > 0 && ClosedSince(Server.Time.Date) + floating <= -DailyLossLimit)
            {
                Note("daily loss limit reached, no new positions today");
                return;
            }

            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(Lots), RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin)
                volume = Symbol.VolumeInUnitsMin;
            double pipMoney = Symbol.PipValue * volume;
            if (pipMoney <= 0)
                return;
            double stepPips = Math.Max(1, Math.Round(StepMoney / pipMoney, 1));
            double stepPrice = stepPips * Symbol.PipSize;
            // Safety stop on the server in case the bot is not running; the basket limit normally acts first
            double safetyPips = Math.Max(stepPips * 2, Math.Round(MaxBasketLoss / pipMoney, 1));

            var buys = positions.Where(p => p.TradeType == TradeType.Buy).ToArray();
            var sells = positions.Where(p => p.TradeType == TradeType.Sell).ToArray();

            // 3. Keep one position on each side (cycle start, or a side just took profit)
            if (buys.Length == 0)
            {
                Open(TradeType.Buy, volume, safetyPips, stepPips, "base");
                return;
            }
            if (sells.Length == 0)
            {
                Open(TradeType.Sell, volume, safetyPips, stepPips, "base");
                return;
            }

            // 4. Add a grid level when price has moved one step against a side
            if (buys.Length < MaxLevels && Symbol.Ask <= buys.Min(p => p.EntryPrice) - stepPrice)
            {
                Open(TradeType.Buy, volume, safetyPips, stepPips, "grid" + (buys.Length + 1));
                return;
            }
            if (sells.Length < MaxLevels && Symbol.Bid >= sells.Max(p => p.EntryPrice) + stepPrice)
            {
                Open(TradeType.Sell, volume, safetyPips, stepPips, "grid" + (sells.Length + 1));
                return;
            }
        }

        private void Open(TradeType type, double volume, double slPips, double tpPips, string comment)
        {
            _lastOrder = Server.Time;
            var result = ExecuteMarketOrder(type, SymbolName, volume, Label, slPips, tpPips, comment);
            if (!result.IsSuccessful)
                Print("Order failed: {0}", result.Error);
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

        private double ClosedSince(DateTime from)
        {
            return History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName && t.ClosingTime >= from)
                .Sum(t => t.NetProfit);
        }

        private void Note(string text)
        {
            if ((Server.Time - _lastNote).TotalMinutes < 30)
                return;
            _lastNote = Server.Time;
            Print("HedgeGrid: {0}", text);
        }
    }
}
