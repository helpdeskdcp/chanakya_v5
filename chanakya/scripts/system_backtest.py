"""
system_backtest.py — Chanakya v5
Full system backtest using actual _analyze() + EMA200 + MTF logic.
Usage: python3 scripts/system_backtest.py --days 30 --symbol NIFTY
       python3 scripts/system_backtest.py --days 30 --all
"""
import sys, os, argparse, json, time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/app/chanakya')

# ─── Config ──────────────────────────────────────────────────────────────────
WATCHLIST = [
    {"symbol":"NIFTY",      "token":"99926000","exchange":"NSE","type":"index",   "lot":65,   "min_sl_pct":0.004},
    {"symbol":"BANKNIFTY",  "token":"99926009","exchange":"NSE","type":"index",   "lot":30,   "min_sl_pct":0.004},
    {"symbol":"CRUDEOIL",   "token":"488290",  "exchange":"MCX","type":"commodity","lot":100,  "min_sl_pct":0.006},
    {"symbol":"NATURALGAS", "token":"488505",  "exchange":"MCX","type":"commodity","lot":1250, "min_sl_pct":0.008},
]

# Score thresholds (from auto_trader.py)
MIN_SCORE_INDEX = 75   # auto_trader INDEX threshold
MAX_SCORE_INDEX = 89   # Score 70-89 only (best WR band)
MIN_SCORE_MCX   = 60   # MCX — tighter (was 50)
MAX_SCORE_MCX   = 89   # MCX Score 90+ unreliable
MIN_SMC         = 35   # tighter SMC

# ─── Helpers ─────────────────────────────────────────────────────────────────
def get_trading_days(n):
    days, d = [], datetime.now().date() - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5: days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))

def parse_candles(raw):
    result = []
    for row in raw:
        try:
            result.append([
                str(row[0])[:16],
                float(row[1]), float(row[2]),
                float(row[3]), float(row[4]),
                float(row[5]) if len(row)>5 else 0,
            ])
        except: pass
    return result

def evaluate_trade(signal, candles_after):
    """Check if target or SL hit after signal candle.
    Uses 2× extended target for better R:R testing.
    """
    entry  = signal['entry']
    sl     = signal['sl']
    dirn   = signal['direction']
    atr    = signal.get('atr', abs(signal['target']-signal['entry']))

    # Extended target: 3×ATR (instead of system default ~1-2×ATR)
    if dirn == 'BUY':
        target = round(entry + 3.0 * atr, 2)
        sl_use = round(entry - 1.5 * atr, 2)
    else:
        target = round(entry - 3.0 * atr, 2)
        sl_use = round(entry + 1.5 * atr, 2)

    for c in candles_after:
        h, l = float(c[2]), float(c[3])
        if dirn == 'BUY':
            if h >= target:  return 'WIN',  round(target-entry, 2), str(c[0])[11:16]
            if l <= sl_use:  return 'LOSS', round(sl_use-entry, 2), str(c[0])[11:16]
        else:
            if l <= target:  return 'WIN',  round(entry-target, 2), str(c[0])[11:16]
            if h >= sl_use:  return 'LOSS', round(entry-sl_use, 2), str(c[0])[11:16]
    return 'OPEN', 0, '—'

def add_ema200(sig, closes):
    """Add EMA200 trend filter — same logic as scanner.py lines 231-248."""
    from engine.indicators import ema as calc_ema
    try:
        e200 = calc_ema(closes[-200:] if len(closes)>=200 else closes, min(200, len(closes)))
        ltp  = closes[-1]
        dirn = sig['direction']
        with_trend = (dirn=='BUY' and ltp>e200) or (dirn=='SELL' and ltp<e200)
        sig['ema200']      = round(e200, 2)
        sig['trend_align'] = 'WITH' if with_trend else 'COUNTER'
        if with_trend:
            sig['score'] = min(100, sig['score'] + 15)
        else:
            sig['score'] = max(0, sig['score'] - 20)
    except Exception as e:
        sig['trend_align'] = 'UNKNOWN'
        sig['ema200']      = 0
    return sig

# ─── Main backtest ────────────────────────────────────────────────────────────
def backtest_symbol(broker, stock, trading_days):
    symbol   = stock['symbol']
    token    = stock['token']
    exchange = stock['exchange']
    is_index = stock['type'] == 'index'
    min_score = MIN_SCORE_INDEX if is_index else MIN_SCORE_MCX

    print(f"\n{'─'*55}")
    print(f"  {symbol} [{exchange}] — {len(trading_days)} days | min_score={min_score}")
    print(f"{'─'*55}")

    from engine.scanner import _analyze

    all_trades   = []
    daily_stats  = []
    score_buckets = defaultdict(lambda:{'w':0,'l':0,'o':0,'cnt':0})
    trend_stats  = defaultdict(lambda:{'w':0,'l':0,'o':0})

    for day in trading_days:
        time.sleep(0.4)  # rate limiter

        days_back = max(5, (datetime.now().date() - day).days + 3)
        raw = broker.get_candles(token, exchange, 'FIVE_MINUTE', days=days_back)
        if not raw:
            print(f"  {day}: ⚠️  No data")
            continue

        # Filter to this day only
        day_str  = str(day)
        all_c    = parse_candles(raw)
        day_c    = [c for c in all_c if str(c[0])[:10] == day_str]

        if len(day_c) < 20:
            print(f"  {day}: ⚠️  Only {len(day_c)} candles")
            continue

        day_signals = []
        day_wins = day_losses = 0

        # Slide through candles — simulate live scanning every 15 min
        step = 3 if is_index else 6  # NSE:15min, MCX:30min
        warmup = 30 if is_index else 50  # MCX needs more warmup for EMA200
        for i in range(warmup, len(day_c), step):
            window = day_c[:i]
            if len(window) < 20: continue

            closes = [float(c[4]) for c in window]

            sig = _analyze(window, symbol, stock)
            if not sig: continue

            # EMA200 filter
            sig = add_ema200(sig, closes)

            # SMC threshold
            smc = sig.get('smc_score', 0)
            if smc < MIN_SMC: continue

            # Fake breakout filter
            fake = sig.get('fake', [])
            if fake and sig['score'] < 55: continue

            # Score threshold — min and max
            max_score = MAX_SCORE_INDEX if is_index else MAX_SCORE_MCX
            if sig['score'] < min_score: continue
            if sig['score'] > max_score: continue  # over-fitted signals skip

            # ── RULE FILTERS (from backtest analysis) ──────────────────
            from datetime import datetime as _dt
            _now = _dt.strptime(window[-1][0][:16].replace('T',' '), '%Y-%m-%d %H:%M')
            _dow = _now.weekday()  # 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri

            # Rule 1: Skip Monday + Thursday (40% WR)
            if is_index and _dow in [0, 3]: continue

            # Rule 2: No trades after 14:00 (0% WR)
            if is_index and _now.hour >= 14: continue

            # Rule 3: Skip RSI 60-69 zone (25% WR — overbought trap)
            _rsi = sig.get('rsi', 50)
            if is_index and 60 <= _rsi <= 69: continue

            # Rule 4: Best window 11:00-14:00
            if is_index and _now.hour < 10: continue

            # Evaluate on remaining candles
            remaining = day_c[i:]
            if not remaining: continue

            outcome, pnl, exit_time = evaluate_trade(sig, [[
                c[0], c[1], c[2], c[3], c[4], c[5]
            ] for c in remaining])

            trade = {
                'date':      day_str,
                'time':      str(window[-1][0])[11:16],
                'symbol':    symbol,
                'direction': sig['direction'],
                'entry':     sig['entry'],
                'sl':        sig['sl'],
                'target':    sig['target'],
                'score':     sig['score'],
                'smc_score': smc,
                'rsi':       sig.get('rsi', 0),
                'ema_cross': sig.get('ema_cross', '?'),
                'ema200':    sig.get('ema200', 0),
                'trend_align': sig.get('trend_align', '?'),
                'vwap_bias': sig.get('vwap_bias', '?'),
                'structure': sig.get('structure', '?'),
                'atr':       sig.get('atr', 0),
                'rr':        sig.get('rr', 0),
                'fake':      fake,
                'outcome':   outcome,
                'pnl':       pnl,
                'exit_time': exit_time,
            }
            day_signals.append(trade)
            all_trades.append(trade)

            # Score buckets
            bucket = f"{(sig['score']//10)*10}-{(sig['score']//10)*10+9}"
            score_buckets[bucket]['cnt'] += 1
            score_buckets[bucket][{'WIN':'w','LOSS':'l','OPEN':'o'}[outcome]] += 1

            # Trend alignment stats
            trend_stats[sig['trend_align']][{'WIN':'w','LOSS':'l','OPEN':'o'}[outcome]] += 1

            if outcome == 'WIN':  day_wins += 1
            if outcome == 'LOSS': day_losses += 1

        daily_stats.append({'date':day_str,'signals':len(day_signals),'wins':day_wins,'losses':day_losses})
        if day_signals:
            print(f"  {day}: {len(day_signals):2d} signals  ✅{day_wins}W / ❌{day_losses}L")
        else:
            print(f"  {day}: no qualifying signals")

    # ── Summary ───────────────────────────────────────────────────────────────
    total  = len(all_trades)
    wins   = sum(1 for t in all_trades if t['outcome']=='WIN')
    losses = sum(1 for t in all_trades if t['outcome']=='LOSS')
    opens  = sum(1 for t in all_trades if t['outcome']=='OPEN')
    wr     = round(wins/(wins+losses)*100, 1) if (wins+losses)>0 else 0

    win_pnls  = [t['pnl'] for t in all_trades if t['outcome']=='WIN']
    loss_pnls = [abs(t['pnl']) for t in all_trades if t['outcome']=='LOSS']
    avg_win   = round(sum(win_pnls)/len(win_pnls),   2) if win_pnls  else 0
    avg_loss  = round(sum(loss_pnls)/len(loss_pnls), 2) if loss_pnls else 0
    rr        = round(avg_win/avg_loss, 2)                if avg_loss  else 0

    print(f"\n  ┌─ {symbol} RESULTS {'─'*30}┐")
    print(f"  │ Total Signals : {total:<5}  Win Rate : {wr}%")
    print(f"  │ Wins : {wins:<5}  Losses : {losses:<5}  Open : {opens}")
    print(f"  │ Avg Win : {avg_win:<8}  Avg Loss : {avg_loss}")
    print(f"  │ Risk:Reward   : 1:{rr}")
    print(f"  │")
    print(f"  │ ── By Score Bucket ──")
    for bkt in sorted(score_buckets.keys()):
        r = score_buckets[bkt]
        t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        print(f"  │   Score {bkt}: {r['cnt']} signals  {r['w']}W/{r['l']}L  WR:{w}%")
    print(f"  │")
    print(f"  │ ── EMA200 Trend Alignment ──")
    for align, r in trend_stats.items():
        t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        print(f"  │   {align:8}: {r['w']}W/{r['l']}L/{r['o']}O  WR:{w}%")
    print(f"  └{'─'*45}┘")

    return {
        'symbol': symbol,
        'total': total, 'wins': wins, 'losses': losses, 'opens': opens,
        'winrate': wr, 'avg_win': avg_win, 'avg_loss': avg_loss, 'rr': rr,
        'score_buckets': dict(score_buckets),
        'trend_alignment': dict(trend_stats),
        'trades': all_trades,
    }

# ─── Entry point ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',   type=int, default=20)
    parser.add_argument('--symbol', default='')
    parser.add_argument('--all',    action='store_true')
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  CHANAKYA v5 — SYSTEM BACKTEST")
    print(f"  EMA9/21/200 + RSI + MACD + VWAP + SMC + Supertrend")
    print(f"  Days: {args.days}")
    print(f"{'='*55}")

    from broker.global_broker import get_broker
    broker = get_broker()
    if not broker:
        print("❌ Broker unavailable"); sys.exit(1)

    trading_days = get_trading_days(args.days)
    print(f"\n  Trading days: {trading_days[0]} → {trading_days[-1]}")

    # Select symbols
    if args.all:
        symbols = WATCHLIST
    elif args.symbol:
        symbols = [s for s in WATCHLIST if s['symbol'] == args.symbol.upper()]
        if not symbols:
            print(f"❌ Symbol not found: {args.symbol}"); sys.exit(1)
    else:
        symbols = WATCHLIST[:2]  # default NIFTY + BANKNIFTY

    all_results = []
    for stock in symbols:
        result = backtest_symbol(broker, stock, trading_days)
        all_results.append(result)
        time.sleep(1)

    # ── Master Summary ────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  MASTER SUMMARY — ALL SYMBOLS")
    print(f"{'='*55}")
    print(f"  {'Symbol':<12} {'Signals':>8} {'WR%':>6} {'AvgW':>8} {'AvgL':>8} {'R:R':>6}")
    print(f"  {'─'*50}")
    for r in all_results:
        print(f"  {r['symbol']:<12} {r['total']:>8} {r['winrate']:>5}% {r['avg_win']:>8} {r['avg_loss']:>8} 1:{r['rr']:>4}")

    # Save report
    out = f"/app/chanakya/data/system_backtest_{args.days}d.json"
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  📄 Report saved: {out}")
    print(f"{'='*55}\n")

if __name__ == '__main__':
    main()
