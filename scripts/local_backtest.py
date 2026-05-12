"""
local_backtest.py — Chanakya v5
Full 5-year backtest using local SQLite DB (no API calls needed).
Usage: python3 scripts/local_backtest.py --symbol NIFTY --days 500
       python3 scripts/local_backtest.py --all --days 200
"""
import sys, os, sqlite3, argparse, json, time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/root/chanakya_v5')

DB_PATH   = '/root/chanakya_v5/data/historical.db'

SYMBOLS = {
    "NIFTY":      {"exchange":"NSE","type":"index",    "lot":65,  "min_sl_pct":0.004},
    "BANKNIFTY":  {"exchange":"NSE","type":"index",    "lot":30,  "min_sl_pct":0.004},
    "NATURALGAS": {"exchange":"MCX","type":"commodity","lot":1250,"min_sl_pct":0.008},
    "CRUDEOIL":   {"exchange":"MCX","type":"commodity","lot":100, "min_sl_pct":0.006},
    "GOLD":       {"exchange":"MCX","type":"commodity","lot":1,   "min_sl_pct":0.005},
}

# Optimized rules (from backtest analysis)
RULES = {
    "NSE": {
        "min_score": 80, "max_score": 89,
        "min_smc":   35,
        "skip_days": [0, 3],          # Mon, Thu
        "trade_hours": (10, 13),      # 10:00-13:00 only (13+ WR 28%)
        "skip_rsi":  (60, 69),        # overbought trap
        "atr_target_mult": 3.0,
        "atr_sl_mult":     1.5,
    },
    "MCX": {
        "min_score": 60, "max_score": 89,
        "min_smc":   35,
        "skip_days": [0, 3],
        "trade_hours": (10, 22),
        "skip_rsi":  (60, 69),
        "atr_target_mult": 4.0,
        "atr_sl_mult":     1.5,
    },
}

# ─── DB helpers ──────────────────────────────────────────────────────────────
def get_conn():
    return sqlite3.connect(DB_PATH)

def get_5min_candles(conn, symbol, date_str):
    """Get 5-min candles for a specific date from local DB."""
    rows = conn.execute('''
        SELECT datetime,open,high,low,close,volume FROM candles_5min
        WHERE symbol=? AND datetime LIKE ? ORDER BY datetime
    ''', (symbol, f"{date_str}%")).fetchall()
    return [[r[0],r[1],r[2],r[3],r[4],r[5]] for r in rows]

def get_daily_candles(conn, symbol, upto_date, limit=250):
    """Get daily candles upto date (for EMA200 calc)."""
    rows = conn.execute('''
        SELECT date,open,high,low,close,volume FROM candles_daily
        WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT ?
    ''', (symbol, upto_date, limit)).fetchall()
    return list(reversed([[r[0],r[1],r[2],r[3],r[4],r[5]] for r in rows]))

def get_trading_days(conn, symbol, n_days):
    """Get last N trading days from DB."""
    rows = conn.execute('''
        SELECT DISTINCT substr(datetime,1,10) as d FROM candles_5min
        WHERE symbol=? ORDER BY d DESC LIMIT ?
    ''', (symbol, n_days)).fetchall()
    return list(reversed([r[0] for r in rows]))

# ─── Signal evaluation ────────────────────────────────────────────────────────
def evaluate_trade(signal, candles_after, rules):
    entry = signal['entry']
    atr   = signal.get('atr', entry*0.002)
    dirn  = signal['direction']
    exch  = signal.get('exchange','NSE')
    r     = rules['MCX'] if exch=='MCX' else rules['NSE']

    if dirn == 'BUY':
        target = round(entry + r['atr_target_mult'] * atr, 2)
        sl     = round(entry - r['atr_sl_mult']     * atr, 2)
    else:
        target = round(entry - r['atr_target_mult'] * atr, 2)
        sl     = round(entry + r['atr_sl_mult']     * atr, 2)

    for c in candles_after:
        h, l = float(c[2]), float(c[3])
        if dirn == 'BUY':
            if h >= target: return 'WIN',  round(target-entry,2), str(c[0])[11:16], target, sl
            if l <= sl:     return 'LOSS', round(sl-entry,2),     str(c[0])[11:16], target, sl
        else:
            if l <= target: return 'WIN',  round(entry-target,2), str(c[0])[11:16], target, sl
            if h >= sl:     return 'LOSS', round(entry-sl,2),     str(c[0])[11:16], target, sl
    return 'OPEN', 0, '—', target, sl

def passes_rules(sig, window, rules_cfg, is_index):
    """Apply optimized trading rules."""
    rconf = rules_cfg['NSE'] if is_index else rules_cfg['MCX']

    # Score filter
    if sig['score'] < rconf['min_score']: return False
    if sig['score'] > rconf['max_score']: return False
    if sig.get('smc_score',0) < rconf['min_smc']: return False

    # Fake breakout
    fake = sig.get('fake',[])
    if fake and sig['score'] < 55: return False

    # Time filter
    try:
        ts   = str(window[-1][0])[:16].replace('T',' ')
        _now = datetime.strptime(ts, '%Y-%m-%d %H:%M')
        h_start, h_end = rconf['trade_hours']
        if _now.weekday() in rconf['skip_days']: return False
        if not (h_start <= _now.hour < h_end):   return False
        # RSI filter
        rsi_lo, rsi_hi = rconf['skip_rsi']
        if rsi_lo <= sig.get('rsi',50) <= rsi_hi: return False
        # Regime filter — skip sideways for NSE
        if is_index and sig.get('regime') == 'SIDEWAYS': return False
        # Day filter — Tue+Wed only (Fri 33% WR skip)
        if is_index and _now.weekday() not in [1, 2]: return False
        # EMA200 COUNTER trend only (83% WR)
        if is_index and sig.get('trend_align') == 'WITH': return False
        # BUY only (75% WR vs SELL 50%)
        if is_index and sig.get('direction') == 'SELL': return False
        # Time: 11:30-13:00 only (12:00 slot 75% WR)
        if is_index and not (11 <= _now.hour < 13): return False
    except: pass

    return True

def add_ema200(sig, daily_candles):
    """EMA200 trend alignment + market regime filter."""
    from engine.indicators import ema as calc_ema
    try:
        closes = [float(c[4]) for c in daily_candles]
        e200 = calc_ema(closes[-200:] if len(closes)>=200 else closes, min(200,len(closes)))
        e20  = calc_ema(closes[-20:]  if len(closes)>=20  else closes, min(20, len(closes)))
        e50  = calc_ema(closes[-50:]  if len(closes)>=50  else closes, min(50, len(closes)))
        ltp  = sig['entry']
        dirn = sig['direction']

        # Market regime — trending vs sideways
        pct_from_e200 = abs(ltp - e200) / e200
        e20_slope = (closes[-1] - closes[-5]) / closes[-5] if len(closes)>=5 else 0
        trending  = abs(e20_slope) > 0.002  # 0.2% slope = trending

        sig['ema200']     = round(e200, 2)
        sig['regime']     = 'TRENDING' if trending else 'SIDEWAYS'
        sig['e20_slope']  = round(e20_slope*100, 3)

        with_t = (dirn=='BUY' and ltp>e200) or (dirn=='SELL' and ltp<e200)
        sig['trend_align'] = 'WITH' if with_t else 'COUNTER'

        if with_t:
            sig['score'] = min(100, sig['score']+15)
            if trending: sig['score'] = min(100, sig['score']+5)  # trending bonus
        else:
            sig['score'] = max(0, sig['score']-20)

        # Sideways penalty
        if not trending:
            sig['score'] = max(0, sig['score']-10)
    except:
        sig['trend_align'] = 'UNKNOWN'
        sig['regime']      = 'UNKNOWN'
    return sig

# ─── Main backtest ────────────────────────────────────────────────────────────
def backtest_symbol(symbol, n_days):
    stock    = SYMBOLS[symbol]
    is_index = stock['type'] == 'index'
    exch     = stock['exchange']
    rconf    = RULES['NSE'] if is_index else RULES['MCX']

    conn = get_conn()
    trading_days = get_trading_days(conn, symbol, n_days)

    if not trading_days:
        print(f"❌ No data for {symbol}"); return None

    print(f"\n{'─'*58}")
    print(f"  {symbol} [{exch}] — {len(trading_days)} days")
    print(f"  {trading_days[0]} → {trading_days[-1]}")
    print(f"  Rules: score {rconf['min_score']}-{rconf['max_score']} | "
          f"T:{rconf['atr_target_mult']}×ATR SL:{rconf['atr_sl_mult']}×ATR")
    print(f"{'─'*58}")

    from engine.scanner import _analyze

    all_trades    = []
    day_summaries = []
    score_stats   = defaultdict(lambda:{'w':0,'l':0,'o':0})
    time_stats    = defaultdict(lambda:{'w':0,'l':0,'o':0})
    dow_stats     = defaultdict(lambda:{'w':0,'l':0,'o':0})
    trend_stats   = defaultdict(lambda:{'w':0,'l':0,'o':0})
    dir_stats     = defaultdict(lambda:{'w':0,'l':0,'o':0})
    month_stats   = defaultdict(lambda:{'w':0,'l':0,'o':0,'pnl':0})

    DAYS = ['Mon','Tue','Wed','Thu','Fri']

    for day_str in trading_days:
        day_c = get_5min_candles(conn, symbol, day_str)
        if len(day_c) < 20:
            continue

        # Daily candles for EMA200
        daily_c = get_daily_candles(conn, symbol, day_str, limit=250)

        day_wins = day_losses = 0
        step   = 3 if is_index else 6
        warmup = 30 if is_index else 50

        for i in range(warmup, len(day_c), step):
            window = day_c[:i]
            if len(window) < 20: continue

            sig = _analyze(window, symbol, stock)
            if not sig: continue

            sig['exchange'] = exch
            sig = add_ema200(sig, daily_c)

            if not passes_rules(sig, window, RULES, is_index): continue

            remaining = day_c[i:]
            if not remaining: continue

            outcome, pnl, exit_t, tgt, sl_used = evaluate_trade(sig, remaining, RULES)

            ts  = str(window[-1][0])[:16].replace('T',' ')
            try: _dt = datetime.strptime(ts, '%Y-%m-%d %H:%M')
            except: continue

            trade = {
                'date': day_str, 'time': ts[11:16],
                'symbol': symbol, 'direction': sig['direction'],
                'entry': sig['entry'], 'target': tgt, 'sl': sl_used,
                'score': sig['score'], 'smc_score': sig.get('smc_score',0),
                'rsi': sig.get('rsi',0), 'atr': sig.get('atr',0),
                'ema200': sig.get('ema200',0),
                'trend_align': sig.get('trend_align','?'),
                'vwap_bias': sig.get('vwap_bias','?'),
                'structure': sig.get('structure','?'),
                'ema_cross': sig.get('ema_cross','?'),
                'outcome': outcome, 'pnl': pnl, 'exit_time': exit_t,
                'month': day_str[:7],
                'dow': DAYS[_dt.weekday()],
                'hour': _dt.hour,
            }
            all_trades.append(trade)

            ok = {'WIN':'w','LOSS':'l','OPEN':'o'}[outcome]
            score_stats[f"{(sig['score']//10)*10}-{(sig['score']//10)*10+9}"][ok] += 1
            time_stats[f"{_dt.hour:02d}:00"][ok] += 1
            dow_stats[DAYS[_dt.weekday()]][ok] += 1
            trend_stats[sig.get('trend_align','?')][ok] += 1
            dir_stats[sig['direction']][ok] += 1
            month_stats[day_str[:7]][ok] += 1
            if outcome != 'OPEN':
                month_stats[day_str[:7]]['pnl'] += pnl if outcome=='WIN' else -abs(pnl)

            if outcome=='WIN':  day_wins  += 1
            if outcome=='LOSS': day_losses += 1

        day_summaries.append({'date':day_str,'wins':day_wins,'losses':day_losses})
        sym_char = '✅' if day_wins > day_losses else ('❌' if day_losses > day_wins else '─')
        print(f"  {day_str}: {day_wins}W/{day_losses}L {sym_char}")

    # ── Results ───────────────────────────────────────────────────────────────
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
    exp_val   = round((wr/100*avg_win) - ((1-wr/100)*avg_loss), 2)

    # Monthly PnL
    lot = stock['lot']

    print(f"\n  ╔══ {symbol} — {len(trading_days)} DAYS RESULTS {'═'*20}╗")
    print(f"  ║ Signals : {total:<6} Wins: {wins:<5} Losses: {losses:<5} Open: {opens}")
    print(f"  ║ Win Rate: {wr}%    R:R: 1:{rr}")
    print(f"  ║ Avg Win : {avg_win:<8} Avg Loss: {avg_loss}")
    print(f"  ║ Exp Val : {exp_val:+.2f} pts/trade")
    print(f"  ║ Lot PnL : ₹{round(exp_val*lot):,}/trade (lot={lot})")

    print(f"  ║")
    print(f"  ║ ── Score Bucket ──────────────────────")
    for bkt in sorted(score_stats.keys()):
        r = score_stats[bkt]; t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        bar = '█'*r['w']+'░'*r['l']
        print(f"  ║   {bkt}: {r['w']}W/{r['l']}L WR:{w:5.1f}%  {bar[:20]}")

    print(f"  ║")
    print(f"  ║ ── Day of Week ───────────────────────")
    for d in DAYS:
        r = dow_stats[d]; t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        print(f"  ║   {d}: {r['w']}W/{r['l']}L WR:{w:5.1f}%")

    print(f"  ║")
    print(f"  ║ ── Time Slot ─────────────────────────")
    for slot in sorted(time_stats.keys()):
        r = time_stats[slot]; t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        print(f"  ║   {slot}: {r['w']}W/{r['l']}L WR:{w:5.1f}%")

    print(f"  ║")
    print(f"  ║ ── EMA200 Trend ──────────────────────")
    for align,r in trend_stats.items():
        t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        print(f"  ║   {align:8}: {r['w']}W/{r['l']}L WR:{w:5.1f}%")

    print(f"  ║")
    print(f"  ║ ── Direction ─────────────────────────")
    for d,r in dir_stats.items():
        t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        print(f"  ║   {d:4}: {r['w']}W/{r['l']}L WR:{w:5.1f}%")

    print(f"  ║")
    print(f"  ║ ── Monthly PnL (pts) ─────────────────")
    total_pts = 0
    for m in sorted(month_stats.keys()):
        r = month_stats[m]
        t = r['w']+r['l']
        w = round(r['w']/t*100,1) if t>0 else 0
        p = round(r['pnl'],1)
        total_pts += p
        sign = '📈' if p>0 else '📉'
        print(f"  ║   {m}: {r['w']}W/{r['l']}L WR:{w:4.1f}% PnL:{p:+.1f}pts {sign}")
    print(f"  ║   {'─'*40}")
    print(f"  ║   TOTAL: {total_pts:+.1f} pts = ₹{round(total_pts*lot):,}")
    print(f"  ╚{'═'*52}╝")

    conn.close()

    result = {
        'symbol':symbol, 'days':len(trading_days),
        'total':total,'wins':wins,'losses':losses,'opens':opens,
        'winrate':wr,'avg_win':avg_win,'avg_loss':avg_loss,'rr':rr,
        'exp_val':exp_val,'total_pts':total_pts,
        'lot':lot,'total_inr':round(total_pts*lot),
        'score_stats':dict(score_stats),
        'dow_stats':dict(dow_stats),
        'time_stats':dict(time_stats),
        'trend_stats':dict(trend_stats),
        'month_stats':{k:dict(v) for k,v in month_stats.items()},
        'trades':all_trades,
    }
    return result

# ─── Entry ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days',   type=int, default=60)
    parser.add_argument('--symbol', default='NIFTY')
    parser.add_argument('--all',    action='store_true')
    args = parser.parse_args()

    print(f"\n{'='*58}")
    print(f"  CHANAKYA v5 — LOCAL 5-YEAR BACKTEST (offline)")
    print(f"  DB: {DB_PATH}")
    print(f"  Days: {args.days}")
    print(f"{'='*58}")

    syms = list(SYMBOLS.keys()) if args.all else [args.symbol.upper()]
    results = []

    for sym in syms:
        if sym not in SYMBOLS:
            print(f"❌ Unknown symbol: {sym}"); continue
        r = backtest_symbol(sym, args.days)
        if r: results.append(r)
        time.sleep(0.5)

    # Master summary
    if len(results) > 1:
        print(f"\n{'='*58}")
        print(f"  MASTER SUMMARY")
        print(f"  {'Symbol':<12}{'Days':>6}{'Sigs':>6}{'WR%':>7}{'R:R':>7}{'ExpVal':>9}{'₹Total':>12}")
        print(f"  {'─'*56}")
        for r in results:
            print(f"  {r['symbol']:<12}{r['days']:>6}{r['total']:>6}"
                  f"{r['winrate']:>6.1f}%{r['rr']:>6.2f}"
                  f"{r['exp_val']:>+9.2f}{r['total_inr']:>12,}")

    # Save
    out = f"/root/chanakya_v5/data/local_backtest_{args.days}d.json"
    with open(out,'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  📄 Saved: {out}")
    print(f"{'='*58}\n")

if __name__ == '__main__':
    main()
