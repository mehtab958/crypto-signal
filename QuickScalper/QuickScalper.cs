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
    public enum NewsMode
    {
        Off,
        PauseOnly,
        TradeSpike
    }

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

        [Parameter("Strategies that must agree", DefaultValue = 2, MinValue = 1, MaxValue = 5, Group = "Strategies")]
        public int MinAgree { get; set; }

        [Parameter("Fast scalping (1 strategy is enough)", DefaultValue = true, Group = "Strategies")]
        public bool FastScalping { get; set; }

        [Parameter("Volume climax reversal", DefaultValue = true, Group = "Strategies")]
        public bool UseVolumeClimax { get; set; }

        [Parameter("Volume breakout", DefaultValue = true, Group = "Strategies")]
        public bool UseVolumeBreakout { get; set; }

        [Parameter("Trend pullback", DefaultValue = true, Group = "Strategies")]
        public bool UsePullback { get; set; }

        [Parameter("Liquidity sweep", DefaultValue = true, Group = "Strategies")]
        public bool UseSweep { get; set; }

        [Parameter("Rejection wick (pin bar)", DefaultValue = true, Group = "Strategies")]
        public bool UsePinBar { get; set; }

        [Parameter("Engulfing candle", DefaultValue = true, Group = "Strategies")]
        public bool UseEngulfing { get; set; }

        [Parameter("Bollinger reversal", DefaultValue = true, Group = "Strategies")]
        public bool UseBollinger { get; set; }

        [Parameter("EMA 9/21 cross", DefaultValue = true, Group = "Strategies")]
        public bool UseEmaCross { get; set; }

        [Parameter("Raja Banks style SnR", DefaultValue = true, Group = "Strategies")]
        public bool UseSnr { get; set; }

        [Parameter("Fair value gap retest", DefaultValue = true, Group = "Strategies")]
        public bool UseFvg { get; set; }

        [Parameter("Break and retest", DefaultValue = true, Group = "Strategies")]
        public bool UseRetest { get; set; }

        [Parameter("MACD cross", DefaultValue = true, Group = "Strategies")]
        public bool UseMacd { get; set; }

        [Parameter("Stochastic turn", DefaultValue = true, Group = "Strategies")]
        public bool UseStochastic { get; set; }

        [Parameter("News mode", DefaultValue = NewsMode.TradeSpike, Group = "News")]
        public NewsMode News { get; set; }

        [Parameter("Spike size (x average candle)", DefaultValue = 3.0, MinValue = 1.5, Step = 0.5, Group = "News")]
        public double NewsSpikeMultiple { get; set; }

        [Parameter("Pause other strategies after spike (min)", DefaultValue = 10, MinValue = 0, Group = "News")]
        public int NewsPauseMinutes { get; set; }

        private const string Label = "QuickScalper";

        private ExponentialMovingAverage _fast;
        private ExponentialMovingAverage _slow;
        private ExponentialMovingAverage _trend;
        private RelativeStrengthIndex _rsi;
        private RelativeStrengthIndex _rsi14;
        private BollingerBands _bb;
        private MacdCrossOver _macd;
        private StochasticOscillator _stoch;
        private string _signalNames = "";
        private AverageTrueRange _atr;
        private DateTime _pauseUntil = DateTime.MinValue;
        private DateTime _lastOpen = DateTime.MinValue;
        private int _signal;   // +1 buy, -1 sell, 0 none; set once per closed bar

        protected override void OnStart()
        {
            _fast = Indicators.ExponentialMovingAverage(Bars.ClosePrices, FastPeriod);
            _slow = Indicators.ExponentialMovingAverage(Bars.ClosePrices, SlowPeriod);
            _trend = Indicators.ExponentialMovingAverage(Bars.ClosePrices, TrendPeriod);
            _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, RsiPeriod);
            _rsi14 = Indicators.RelativeStrengthIndex(Bars.ClosePrices, 14);
            _atr = Indicators.AverageTrueRange(14, MovingAverageType.Simple);
            _bb = Indicators.BollingerBands(Bars.ClosePrices, 20, 2, MovingAverageType.Simple);
            _macd = Indicators.MacdCrossOver(26, 12, 9);
            _stoch = Indicators.StochasticOscillator(14, 3, 3, MovingAverageType.Simple);
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
            var order = ExecuteMarketOrder(tradeType, SymbolName, volume, Label, slPips, tpPips, _signalNames);
            if (order.IsSuccessful)
                _lastOpen = Server.Time;
            else
                Print("Order failed: {0}", order.Error);
        }

        // Combined signal from the last closed bar. Each enabled strategy votes
        // buy (+1) or sell (-1); opposite votes cancel the signal, and at least
        // "Strategies that must agree" votes are needed.
        private int ReadSignal()
        {
            _signalNames = "";
            if (Bars.Count < 130)
                return 0;

            int i = Bars.Count - 2;   // last closed bar
            int direction = 0, votes = 0;
            string names = "";

            // News handling: a news release shows up as a candle several times
            // larger than normal. Trade with it and/or pause the other strategies.
            if (News != NewsMode.Off)
            {
                double normal = _atr.Result[i - 1];
                double size = H(i) - L(i);
                if (normal > 0 && size >= NewsSpikeMultiple * normal)
                {
                    _pauseUntil = Server.Time.AddMinutes(NewsPauseMinutes);
                    Print("News spike: candle is {0:0.0}x normal size", size / normal);
                    if (News == NewsMode.TradeSpike && Math.Abs(C(i) - O(i)) >= 0.6 * size)
                    {
                        _signalNames = "news";
                        return C(i) > O(i) ? 1 : -1;
                    }
                    return 0;
                }
                if (Server.Time < _pauseUntil)
                    return 0;
            }

            if (!Vote(UsePullback, Pullback(i), "pullback", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseSweep, Sweep(i), "sweep", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UsePinBar, PinBar(i), "pinbar", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseEngulfing, Engulfing(i), "engulf", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseBollinger, Bollinger(i), "bb", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseEmaCross, EmaCross(i), "cross", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseSnr, Snr(i), "snr", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseFvg, Fvg(i), "fvg", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseRetest, Retest(i), "retest", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseMacd, Macd(i), "macd", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseStochastic, Stochastic(i), "stoch", ref direction, ref votes, ref names)) return 0;

            if (!Vote(UseVolumeClimax, VolumeClimax(i), "volclimax", ref direction, ref votes, ref names)) return 0;
            if (!Vote(UseVolumeBreakout, VolumeBreakout(i), "volbreak", ref direction, ref votes, ref names)) return 0;

            if (direction == 0 || votes < (FastScalping ? 1 : MinAgree))
                return 0;
            _signalNames = names;
            Print("Signal {0}: {1}", direction > 0 ? "BUY" : "SELL", names);
            return direction;
        }

        // Returns false when this vote conflicts with earlier ones
        private static bool Vote(bool enabled, int vote, string name, ref int direction, ref int votes, ref string names)
        {
            if (!enabled || vote == 0)
                return true;
            if (direction != 0 && vote != direction)
                return false;
            direction = vote;
            votes++;
            names = names.Length == 0 ? name : names + "+" + name;
            return true;
        }

        private double O(int j) { return Bars.OpenPrices[j]; }
        private double H(int j) { return Bars.HighPrices[j]; }
        private double L(int j) { return Bars.LowPrices[j]; }
        private double C(int j) { return Bars.ClosePrices[j]; }

        private double HighestHigh(int end, int n)   // bars end-n .. end-1
        {
            double v = double.MinValue;
            for (int j = end - n; j < end; j++) v = Math.Max(v, H(j));
            return v;
        }

        private double LowestLow(int end, int n)
        {
            double v = double.MaxValue;
            for (int j = end - n; j < end; j++) v = Math.Min(v, L(j));
            return v;
        }

        // With the trend, after a short RSI dip, once price turns back
        private int Pullback(int i)
        {
            double rsiLow = Math.Min(_rsi.Result[i - 1], Math.Min(_rsi.Result[i - 2], _rsi.Result[i - 3]));
            double rsiHigh = Math.Max(_rsi.Result[i - 1], Math.Max(_rsi.Result[i - 2], _rsi.Result[i - 3]));
            bool up = C(i) > _trend.Result[i] && _slow.Result[i] > _trend.Result[i];
            bool down = C(i) < _trend.Result[i] && _slow.Result[i] < _trend.Result[i];
            if (up && rsiLow < RsiBuyBelow && C(i) > O(i) && C(i) > _fast.Result[i] && _rsi.Result[i] > _rsi.Result[i - 1]) return 1;
            if (down && rsiHigh > RsiSellAbove && C(i) < O(i) && C(i) < _fast.Result[i] && _rsi.Result[i] < _rsi.Result[i - 1]) return -1;
            return 0;
        }

        // Wick takes out the 20-bar high or low, then the bar closes back inside
        private int Sweep(int i)
        {
            double hi = HighestHigh(i, 20), lo = LowestLow(i, 20);
            if (L(i) < lo && C(i) > lo && C(i) > O(i)) return 1;
            if (H(i) > hi && C(i) < hi && C(i) < O(i)) return -1;
            return 0;
        }

        // Long rejection wick at the edge of the 20-bar range
        private int PinBar(int i)
        {
            double body = Math.Abs(C(i) - O(i)), full = H(i) - L(i);
            if (full <= 0) return 0;
            double lowWick = Math.Min(O(i), C(i)) - L(i), upWick = H(i) - Math.Max(O(i), C(i));
            double hi = HighestHigh(i, 20), lo = LowestLow(i, 20), near = (hi - lo) * 0.15;
            if (lowWick >= 2 * body && lowWick >= 0.6 * full && L(i) <= lo + near) return 1;
            if (upWick >= 2 * body && upWick >= 0.6 * full && H(i) >= hi - near) return -1;
            return 0;
        }

        // Engulfing bar in the direction of the trend EMA
        private int Engulfing(int i)
        {
            int p = i - 1;
            if (C(p) < O(p) && C(i) > O(i) && C(i) >= O(p) && O(i) <= C(p) && C(i) > _trend.Result[i]) return 1;
            if (C(p) > O(p) && C(i) < O(i) && C(i) <= O(p) && O(i) >= C(p) && C(i) < _trend.Result[i]) return -1;
            return 0;
        }

        // Closes back inside the Bollinger Bands with RSI stretched
        private int Bollinger(int i)
        {
            if (C(i - 1) < _bb.Bottom[i - 1] && C(i) > _bb.Bottom[i] && _rsi14.Result[i - 1] < 30) return 1;
            if (C(i - 1) > _bb.Top[i - 1] && C(i) < _bb.Top[i] && _rsi14.Result[i - 1] > 70) return -1;
            return 0;
        }

        private int EmaCross(int i)
        {
            double was = _fast.Result[i - 1] - _slow.Result[i - 1], now = _fast.Result[i] - _slow.Result[i];
            if (was <= 0 && now > 0 && C(i) > _trend.Result[i]) return 1;
            if (was >= 0 && now < 0 && C(i) < _trend.Result[i]) return -1;
            return 0;
        }

        // Raja Banks style SnR: levels drawn on closes (A / V shapes); a fresh level
        // is tapped by a wick and the bar closes back
        private int Snr(int i)
        {
            for (int j = i - 4; j >= i - 100; j--)
            {
                double level = C(j);
                bool fresh = true;
                if (level > C(j - 1) && level > C(j - 2) && level > C(j + 1) && level > C(j + 2))
                {
                    if (!(H(i) >= level && C(i) < level && C(i) < O(i))) continue;
                    for (int m = j + 2; m < i; m++) if (H(m) >= level) { fresh = false; break; }
                    if (fresh) return -1;
                }
                else if (level < C(j - 1) && level < C(j - 2) && level < C(j + 1) && level < C(j + 2))
                {
                    if (!(L(i) <= level && C(i) > level && C(i) > O(i))) continue;
                    for (int m = j + 2; m < i; m++) if (L(m) <= level) { fresh = false; break; }
                    if (fresh) return 1;
                }
            }
            return 0;
        }

        // Price returns into a recent unfilled 3-bar gap and holds
        private int Fvg(int i)
        {
            for (int a = i - 1; a >= i - 12; a--)
            {
                bool ok = true;
                if (L(a) > H(a - 2))
                {
                    double top = L(a), bottom = H(a - 2);
                    for (int m = a + 1; m < i; m++) if (L(m) <= top) { ok = false; break; }
                    if (ok && L(i) <= top && C(i) > bottom && C(i) > O(i)) return 1;
                }
                else if (H(a) < L(a - 2))
                {
                    double bottom = H(a), top = L(a - 2);
                    for (int m = a + 1; m < i; m++) if (H(m) >= bottom) { ok = false; break; }
                    if (ok && H(i) >= bottom && C(i) < top && C(i) < O(i)) return -1;
                }
            }
            return 0;
        }

        // Closes through the 20-bar range, comes back to the level and holds
        private int Retest(int i)
        {
            double hi = HighestHigh(i - 5, 20), lo = LowestLow(i - 5, 20);
            bool brokeUp = false, brokeDown = false;
            for (int j = i - 5; j < i; j++)
            {
                if (C(j) > hi) brokeUp = true;
                if (C(j) < lo) brokeDown = true;
            }
            if (brokeUp && !brokeDown && L(i) <= hi && C(i) > hi && C(i) > O(i)) return 1;
            if (brokeDown && !brokeUp && H(i) >= lo && C(i) < lo && C(i) < O(i)) return -1;
            return 0;
        }

        private int Macd(int i)
        {
            double was = _macd.MACD[i - 1] - _macd.Signal[i - 1], now = _macd.MACD[i] - _macd.Signal[i];
            if (was <= 0 && now > 0 && C(i) > _trend.Result[i]) return 1;
            if (was >= 0 && now < 0 && C(i) < _trend.Result[i]) return -1;
            return 0;
        }

        private double AverageVolume(int end, int n)   // bars end-n .. end-1
        {
            double sum = 0;
            for (int j = end - n; j < end; j++) sum += Bars.TickVolumes[j];
            return sum / n;
        }

        // Very high volume bar with a long rejection wick: the move is exhausted
        private int VolumeClimax(int i)
        {
            double avg = AverageVolume(i, 20), full = H(i) - L(i);
            if (avg <= 0 || full <= 0 || Bars.TickVolumes[i] < 2 * avg) return 0;
            double lowWick = Math.Min(O(i), C(i)) - L(i), upWick = H(i) - Math.Max(O(i), C(i));
            if (lowWick >= 0.5 * full && L(i) <= LowestLow(i, 10)) return 1;
            if (upWick >= 0.5 * full && H(i) >= HighestHigh(i, 10)) return -1;
            return 0;
        }

        // Close beyond the 20-bar range on clearly higher volume: follow the break
        private int VolumeBreakout(int i)
        {
            double avg = AverageVolume(i, 20);
            if (avg <= 0 || Bars.TickVolumes[i] < 1.5 * avg) return 0;
            if (C(i) > HighestHigh(i, 20) && C(i) > O(i)) return 1;
            if (C(i) < LowestLow(i, 20) && C(i) < O(i)) return -1;
            return 0;
        }

        private int Stochastic(int i)
        {
            double was = _stoch.PercentK[i - 1] - _stoch.PercentD[i - 1], now = _stoch.PercentK[i] - _stoch.PercentD[i];
            if (was <= 0 && now > 0 && _stoch.PercentK[i - 1] < 20) return 1;
            if (was >= 0 && now < 0 && _stoch.PercentK[i - 1] > 80) return -1;
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
