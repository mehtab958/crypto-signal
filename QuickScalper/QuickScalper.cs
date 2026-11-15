// QuickScalper for cTrader
// Scalper for the 1-minute chart: several small positions, each closed at a
// small money profit or a fixed money loss. Start it on an m1 chart.
// Test on a demo account first.
using System;
using System.Collections.Generic;
using System.Globalization;
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
        [Parameter("Smallest lot (1 strategy)", DefaultValue = 0.01, MinValue = 0.01, Step = 0.01)]
        public double MinLots { get; set; }

        [Parameter("Largest lot (3+ strategies agree)", DefaultValue = 0.03, MinValue = 0.01, Step = 0.01)]
        public double MaxLots { get; set; }

        [Parameter("Max open trades", DefaultValue = 6, MinValue = 1, MaxValue = 10)]
        public int MaxPositions { get; set; }

        [Parameter("Smallest profit target (money)", DefaultValue = 5.0, MinValue = 0.05)]
        public double ProfitTarget { get; set; }

        [Parameter("Largest profit target (money)", DefaultValue = 5.0, MinValue = 0.05)]
        public double MaxProfitTarget { get; set; }

        [Parameter("Profit target is at least this many times the spread cost", DefaultValue = 4.0, MinValue = 1.0, Step = 0.5)]
        public double SpreadMultiple { get; set; }

        [Parameter("Loss limit at smallest target (money, grows with target)", DefaultValue = 3.0, MinValue = 0.1)]
        public double StopLoss { get; set; }

        [Parameter("Daily loss limit (money, 0 = off)", DefaultValue = 20.0, MinValue = 0)]
        public double DailyLossLimit { get; set; }

        [Parameter("Seconds between new trades", DefaultValue = 10, MinValue = 0)]
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

        [Parameter("Basket mode (open a group, close together)", DefaultValue = true, Group = "Basket")]
        public bool BasketMode { get; set; }

        [Parameter("Trades opened together", DefaultValue = 5, MinValue = 1, MaxValue = 10, Group = "Basket")]
        public int BasketSize { get; set; }

        [Parameter("Max groups open at once", DefaultValue = 4, MinValue = 1, MaxValue = 10, Group = "Basket")]
        public int MaxBaskets { get; set; }

        [Parameter("Close all at total profit (money)", DefaultValue = 3.5, MinValue = 0.1, Group = "Basket")]
        public double BasketProfit { get; set; }

        [Parameter("Close all at total loss (money)", DefaultValue = 5.0, MinValue = 0.1, Group = "Basket")]
        public double BasketLoss { get; set; }

        [Parameter("Only trade with the 15-min and 1-hour trend", DefaultValue = true, Group = "Filters")]
        public bool UseHtfFilter { get; set; }

        [Parameter("Only trade in session hours", DefaultValue = false, Group = "Filters")]
        public bool UseSessionFilter { get; set; }

        [Parameter("Session start hour (UTC)", DefaultValue = 7, MinValue = 0, MaxValue = 23, Group = "Filters")]
        public int SessionStartUtc { get; set; }

        [Parameter("Session end hour (UTC)", DefaultValue = 16, MinValue = 0, MaxValue = 24, Group = "Filters")]
        public int SessionEndUtc { get; set; }

        [Parameter("Pause strategies that are losing", DefaultValue = true, Group = "Filters")]
        public bool UseSelfScoring { get; set; }

        [Parameter("Score over this many recent trades", DefaultValue = 30, MinValue = 10, MaxValue = 200, Group = "Filters")]
        public int ScoreTrades { get; set; }

        [Parameter("Paused strategy returns after (hours)", DefaultValue = 24, MinValue = 1, Group = "Filters")]
        public int PauseHours { get; set; }

        [Parameter("Open first trade(s) right at start (trend direction)", DefaultValue = true)]
        public bool OpenOnStart { get; set; }

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
        private int _signalVotes = 1;
        private bool _startPending;
        private Bars _m15;
        private Bars _h1;
        private ExponentialMovingAverage _m15Trend;
        private ExponentialMovingAverage _h1Trend;
        private HashSet<string> _paused = new HashSet<string>();
        private string _pausedText = "";
        private static readonly string[] StrategyNames = { "pullback", "sweep", "pinbar", "engulf", "bb", "cross", "snr", "fvg", "retest", "macd", "stoch", "volclimax", "volbreak" };
        private bool _immediate;
        private DateTime _lastStatus = DateTime.MinValue;
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
            _m15 = MarketData.GetBars(TimeFrame.Minute15);
            _h1 = MarketData.GetBars(TimeFrame.Hour);
            _m15Trend = Indicators.ExponentialMovingAverage(_m15.ClosePrices, 50);
            _h1Trend = Indicators.ExponentialMovingAverage(_h1.ClosePrices, 50);
            _startPending = OpenOnStart;
            Print("QuickScalper started on {0} {1}, {2} bars loaded, account {3}", SymbolName, TimeFrame, Bars.Count, Account.IsLive ? "LIVE" : "demo");
        }

        protected override void OnBar()
        {
            _signal = ReadSignal();
        }

        protected override void OnTick()
        {
            // Proof-of-life line in the log every 15 minutes
            if ((Server.Time - _lastStatus).TotalMinutes >= 15)
            {
                _lastStatus = Server.Time;
                Print("Running. Open trades: {0}. Spread: {1:0.0} pips.", Positions.FindAll(Label, SymbolName).Length, Symbol.Spread / Symbol.PipSize);
            }

            // Optional first entry right after start, in the direction of the trend EMA
            if (_startPending && Bars.Count >= TrendPeriod + 5)
            {
                _startPending = false;
                _signal = Bars.ClosePrices.Last(1) >= _trend.Result.Last(1) ? 1 : -1;
                _signalNames = "start";
                _signalVotes = 1;
                _immediate = true;
                Print("Start entry: {0}", _signal > 0 ? "BUY" : "SELL");
            }

            if (BasketMode)
            {
                BasketTick();
                return;
            }

            double floating = 0;
            int open = 0;

            // Close trades that reached the money target or the money stop
            foreach (var position in Positions.FindAll(Label, SymbolName))
            {
                if (position.NetProfit >= TargetOf(position) || position.NetProfit <= -StopOf(position))
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
            if (!_immediate && (Server.Time - Bars.OpenTimes.LastValue).TotalSeconds > 20)   // only act early in the bar
                return;
            _immediate = false;
            if (DailyLossLimit > 0 && TodayClosedProfit() + floating <= -DailyLossLimit)
            {
                Skip("daily loss limit reached");
                return;
            }

            // More agreeing strategies -> bigger lot, from the smallest to the largest setting
            double lots = Math.Min(Math.Max(MinLots, MaxLots), MinLots + 0.01 * (Math.Max(1, _signalVotes) - 1));
            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(lots), RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin)
                volume = Symbol.VolumeInUnitsMin;

            // Server-side stop and target, so trades stay protected if the bot stops
            double pipMoney = Symbol.PipValue * volume;
            if (pipMoney <= 0)
                return;

            // Flexible target: never skip for spread. The wider the spread, the larger
            // the profit target (and the loss limit, in the same proportion).
            double spreadCost = Symbol.Spread / Symbol.PipSize * pipMoney;
            double largest = Math.Max(ProfitTarget, MaxProfitTarget);
            double target = Math.Min(largest, Math.Max(ProfitTarget, SpreadMultiple * spreadCost));
            double stop = StopLoss * target / ProfitTarget;
            double slPips = Math.Max(1, Math.Round(stop / pipMoney, 1));
            double tpPips = Math.Max(1, Math.Round(target / pipMoney, 1));
            string comment = _signalNames + "|" + target.ToString("0.00", CultureInfo.InvariantCulture) + "|" + stop.ToString("0.00", CultureInfo.InvariantCulture);

            var tradeType = _signal > 0 ? TradeType.Buy : TradeType.Sell;
            var order = ExecuteMarketOrder(tradeType, SymbolName, volume, Label, slPips, tpPips, comment);
            if (order.IsSuccessful)
                _lastOpen = Server.Time;
            else
                Print("Order failed: {0}", order.Error);
        }

        // Basket mode: on a signal, open several trades together in the same direction,
        // then close them all when their total profit or total loss reaches the limit.
        private void BasketTick()
        {
            // Each group is managed on its own: closed when ITS total hits the profit or loss limit
            var groups = Positions.FindAll(Label, SymbolName).GroupBy(p => BasketId(p)).ToList();
            int openGroups = 0;
            double floating = 0;
            foreach (var group in groups)
            {
                double total = group.Sum(p => p.NetProfit);
                if (total >= BasketProfit || total <= -BasketLoss)
                {
                    Print("Group {0} closed at {1:0.00}", group.Key, total);
                    foreach (var position in group.ToList())
                    {
                        var closed = ClosePosition(position);
                        if (!closed.IsSuccessful)
                            Print("Close failed: {0}", closed.Error);
                    }
                    continue;
                }
                openGroups++;
                floating += total;
            }

            if (_signal == 0)
                return;
            if (openGroups >= MaxBaskets)
            {
                Skip("maximum number of groups already open");
                return;
            }
            if (!_immediate && (Server.Time - Bars.OpenTimes.LastValue).TotalSeconds > 20)
                return;
            _immediate = false;
            if (DailyLossLimit > 0 && TodayClosedProfit() + floating <= -DailyLossLimit)
            {
                Skip("daily loss limit reached");
                return;
            }

            double volume = Symbol.NormalizeVolumeInUnits(Symbol.QuantityToVolumeInUnits(MinLots), RoundingMode.Down);
            if (volume < Symbol.VolumeInUnitsMin)
                volume = Symbol.VolumeInUnitsMin;
            double pipMoney = Symbol.PipValue * volume;
            if (pipMoney <= 0)
                return;

            // Safety stop and target on the server for each trade, set wide (2x its share),
            // in case the bot is not running; the basket limits normally act first
            double slPips = Math.Max(1, Math.Round(2 * BasketLoss / BasketSize / pipMoney, 1));
            double tpPips = Math.Max(1, Math.Round(2 * BasketProfit / BasketSize / pipMoney, 1));

            var tradeType = _signal > 0 ? TradeType.Buy : TradeType.Sell;
            string comment = _signalNames + "|basket|" + Server.Time.ToString("ddHHmmss", CultureInfo.InvariantCulture);
            int opened = 0;
            for (int n = 0; n < BasketSize; n++)
            {
                var order = ExecuteMarketOrder(tradeType, SymbolName, volume, Label, slPips, tpPips, comment);
                if (order.IsSuccessful)
                    opened++;
                else
                    Print("Order failed: {0}", order.Error);
            }
            Print("Basket opened: {0} x {1} ({2})", opened, tradeType, _signalNames);
            _signal = 0;
        }

        // Group id is the last part of the comment, e.g. "sweep|basket|16024512"
        private static string BasketId(Position position)
        {
            string comment = position.Comment ?? "";
            int cut = comment.LastIndexOf('|');
            return cut >= 0 ? comment.Substring(cut + 1) : "old";
        }

        // Each trade carries its own profit target and loss limit at the end of
        // its comment, e.g. "sweep|0.70|1.00"
        private double CommentNumber(Position position, int fromEnd, double fallback)
        {
            string[] parts = (position.Comment ?? "").Split('|');
            double value;
            if (parts.Length >= 3 && double.TryParse(parts[parts.Length - fromEnd], NumberStyles.Float, CultureInfo.InvariantCulture, out value) && value > 0)
                return value;
            return fallback;
        }

        private double TargetOf(Position position) { return CommentNumber(position, 2, ProfitTarget); }
        private double StopOf(Position position) { return CommentNumber(position, 1, StopLoss); }

        // Log why a signal was not traded, once per bar
        private DateTime _lastSkipBar = DateTime.MinValue;
        private void Skip(string reason)
        {
            if (_lastSkipBar == Bars.OpenTimes.LastValue)
                return;
            _lastSkipBar = Bars.OpenTimes.LastValue;
            Print("Signal skipped: {0}", reason);
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

            if (UseSelfScoring)
                UpdateScores();

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
                        _signalVotes = 1;
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
            if (UseSessionFilter && !InSession())
            {
                Skip("outside session hours");
                return 0;
            }
            if (UseHtfFilter && HigherTrend() != direction)
            {
                Skip("against the 15-min / 1-hour trend (" + names + ")");
                return 0;
            }
            _signalNames = names;
            _signalVotes = votes;
            Print("Signal {0}: {1}", direction > 0 ? "BUY" : "SELL", names);
            return direction;
        }

        // Returns false when this vote conflicts with earlier ones
        private bool Vote(bool enabled, int vote, string name, ref int direction, ref int votes, ref string names)
        {
            if (!enabled || vote == 0 || _paused.Contains(name))
                return true;
            if (direction != 0 && vote != direction)
                return false;
            direction = vote;
            votes++;
            names = names.Length == 0 ? name : names + "+" + name;
            return true;
        }

        private bool InSession()
        {
            int hour = Server.Time.Hour;
            return SessionStartUtc <= SessionEndUtc
                ? hour >= SessionStartUtc && hour < SessionEndUtc
                : hour >= SessionStartUtc || hour < SessionEndUtc;
        }

        // +1 when both the 15-minute and 1-hour closes are above their EMA 50, -1 when both below, else 0
        private int HigherTrend()
        {
            if (_m15.Count < 60 || _h1.Count < 60)
                return 0;
            bool m15Up = _m15.ClosePrices.Last(1) > _m15Trend.Result.Last(1);
            bool h1Up = _h1.ClosePrices.Last(1) > _h1Trend.Result.Last(1);
            if (m15Up && h1Up) return 1;
            if (!m15Up && !h1Up) return -1;
            return 0;
        }

        // Self-scoring: a strategy whose recent trades add up to a loss is paused.
        // It returns once its last trade is older than the pause time.
        private void UpdateScores()
        {
            var recent = History
                .Where(t => t.Label == Label && t.SymbolName == SymbolName)
                .OrderByDescending(t => t.ClosingTime)
                .Take(600)
                .ToList();
            var cutoff = Server.Time.AddHours(-PauseHours);
            var paused = new HashSet<string>();
            foreach (var name in StrategyNames)
            {
                var mine = recent.Where(t => HasStrategy(t.Comment, name)).Take(ScoreTrades).ToList();
                if (mine.Count >= 10 && mine.Sum(t => t.NetProfit) < 0 && mine[0].ClosingTime > cutoff)
                    paused.Add(name);
            }
            _paused = paused;
            string text = string.Join(", ", paused.OrderBy(n => n));
            if (text != _pausedText)
            {
                _pausedText = text;
                Print("Paused strategies: {0}", text.Length == 0 ? "none" : text);
            }
        }

        private static bool HasStrategy(string comment, string name)
        {
            if (string.IsNullOrEmpty(comment))
                return false;
            return comment.Split('|')[0].Split('+').Contains(name);
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
