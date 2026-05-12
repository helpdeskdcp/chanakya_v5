"""
pivot_backtest.py — Chanakya v5
Full historical backtest of pivot signal detection.
Usage: python3 scripts/pivot_backtest.py --symbol NIFTY --days 60
"""
import sys, os, argparse, json
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/root/chanakya_v5')

def prev_trading_day(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5: d -= timedelta(days=1)
    return d

def make_pivots(H, L, C):
    pp = (H + L + C) / 3
    return {
        'pp': round(pp,2), 'r1': round(2*pp-L,2), 'r2': round(pp+H-L,2),
        'r3': round(H+2*(pp-L),2), 's1': round(2*pp-H,2),
        's2': round(pp-H+L,2), 's3': round(L-2*(H-pp),2),
    }

def detect_signals(candles, pivots, threshold=0.0010):
    levels = {
        's3':(pivots['s3'],'SUPPORT',3), 's2':(pivots['s2'],'SUPPORT',2),
        's1':(pivots['s1'],'SUPPORT',1), 'pp':(pivots['pp'],'PIVOT',2),
        'r1':(pivots['r1'],'RESIST',1),  'r2':(pivots['r2'],'RESIST',2),
        'r3':(pivots['r3'],'RESIST',3),
    }
    signals = []
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i-1]
        bull = c['close'] > c['open']
        bear = c['close'] < c['open']
        for lname,(lval,ltype,strength) in levels.items():
            if ltype == 'SUPPORT':
                touched = c['low'] <= lval*(1+threshold) and c['low'] >= lval*(1-threshold)
                if touched and bull and prev['close'] < prev['open']:
                    signals.append({'idx':i,'time':c['time'],'type':'BUY','level':lname.upper(),
                        'level_val':lval,'price':c['close'],'strength':strength,
                        'sl':round(lval*(1-threshold*2),2),
                        'target':round(pivots.get('pp' if 'pp' not in lname else 'r1',lval*1.005),2)})
            elif ltype == 'RESIST':
                touched = c['high'] >= lval*(1-threshold) and c['high'] <= lval*(1+threshold)
                if touched and bear and prev['close'] > prev['open']:
                    signals.append({'idx':i,'time':c['time'],'type':'SELL','level':lname.upper(),
                        'level_val':lval,'price':c['close'],'strength':strength,
                        'sl':round(lval*(1+threshold*2),2),
                        'target':round(pivots.get('pp' if 'pp' not in lname else 's1',lval*0.995),2)})
            elif ltype == 'PIVOT':
                if prev['close'] < lval <= c['close'] and bull:
                    signals.append({'idx':i,'time':c['time'],'type':'BUY','level':'PP',
                        'level_val':lval,'price':c['close'],'strength':2,
                        'sl':round(lval*0.998,2),'target':round(pivots['r1'],2)})
                elif prev['close'] > lval >= c['close'] and bear:
                    signals.append({'idx':i,'time':c['time'],'type':'SELL','level':'PP',
                        'level_val':lval,'price':c['close'],'strength':2,
                        'sl':round(lval*1.002,2),'target':round(pivots['s1'],2)})

    # Cooldown filter
    from collections import defaultdict as dd
    last_fired, level_count, filtered = {}, dd(int), []
    for s in signals:
        lkey = s['level']+s['type']
        last = last_fired.get(lkey, -99)
        if (s['idx']-last) >= 8 and level_count[lkey] < 2:
            filtered.append(s); last_fired[lkey]=s['idx']; level_count[lkey]+=1
    return filtered

def evaluate_signal(signal, candles):
    """Check if target hit or SL hit after signal candle."""
    entry = signal['price']
    target = signal['target']
    sl     = signal['sl']
    sig_type = signal['type']

    for c in candles[signal['idx']+1:]:
        if sig_type == 'BUY':
            if c['high'] >= target: return 'WIN',  round(target - entry, 2), c['time']
            if c['low']  <= sl:     return 'LOSS', round(sl - entry, 2),     c['time']
        else:
            if c['low']  <= target: return 'WIN',  round(entry - target, 2), c['time']
            if c['high'] >= sl:     return 'LOSS', round(entry - sl, 2),     c['time']
    return 'OPEN', 0, candles[-1]['time']

def get_trading_days(start_date, days):
    result, d = [], start_date
    while len(result) < days:
        if d.weekday() < 5: result.append(d)
        d -= timedelta(days=1)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='NIFTY')
    parser.add_argument('--days',   type=int, default=30)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    print(f"\n{'='*60}")
    print(f"  CHANAKYA PIVOT BACKTEST — {symbol} — Last {args.days} trading days")
    print(f"{'='*60}\n")

    from broker.global_broker import get_broker
    broker = get_broker()
    if not broker:
        print("❌ Broker unavailable"); sys.exit(1)

    from api.routes.pivot import _resolve_token, _fetch_candles
    exchange, token = _resolve_token(symbol)
    if not token:
        print(f"❌ Token not found for {symbol}"); sys.exit(1)

    print(f"  Symbol  : {symbol}")
    print(f"  Exchange: {exchange}")
    print(f"  Token   : {token}\n")

    # Get all daily candles for date range
    import time
    raw_daily = broker.get_candles(token, exchange, 'ONE_DAY', days=args.days+10)
    if not raw_daily:
        print("❌ No daily data"); sys.exit(1)

    # Parse daily candles
    daily = []
    for row in raw_daily:
        try:
            ts = str(row[0])[:10]
            daily.append({'date':ts,'open':float(row[1]),'high':float(row[2]),
                         'low':float(row[3]),'close':float(row[4])})
        except: pass

    daily = sorted(daily, key=lambda x: x['date'])[-args.days:]
    print(f"  Trading days found: {len(daily)}\n")

    # Results
    all_signals = []
    day_results = []

    for i, day in enumerate(daily[1:], 1):  # skip first (no prev day)
        prev = daily[i-1]
        date_str = day['date']

        pivots = make_pivots(prev['high'], prev['low'], prev['close'])

        # Get intraday candles
        time.sleep(0.35)
        chart_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        days_back = max(2, (datetime.now().date() - chart_date).days + 2)
        candles = _fetch_candles(broker, token, exchange, 'FIVE_MINUTE',
                                 target_date=chart_date, days=days_back)
        if not candles:
            print(f"  {date_str}: ⚠️  No candle data (holiday/weekend)")
            continue

        signals = detect_signals(candles, pivots)
        day_wins = day_losses = 0

        for sig in signals:
            outcome, pnl, exit_time = evaluate_signal(sig, candles)
            sig.update({'date':date_str,'outcome':outcome,'pnl':pnl,'exit_time':exit_time})
            all_signals.append(sig)
            if outcome == 'WIN':  day_wins  += 1
            if outcome == 'LOSS': day_losses += 1

        day_results.append({
            'date':date_str, 'signals':len(signals),
            'wins':day_wins, 'losses':day_losses,
            'close':day['close'], 'pp':pivots['pp'],
        })
        status = f"✅ {day_wins}W/{day_losses}L" if signals else "  no signals"
        print(f"  {date_str}: {len(signals):2d} signals {status}")

    # ── Summary ──────────────────────────────────────────────────
    total  = len(all_signals)
    wins   = sum(1 for s in all_signals if s['outcome']=='WIN')
    losses = sum(1 for s in all_signals if s['outcome']=='LOSS')
    opens  = sum(1 for s in all_signals if s['outcome']=='OPEN')
    winrate = round(wins/(wins+losses)*100, 1) if (wins+losses) > 0 else 0

    win_pnls  = [s['pnl'] for s in all_signals if s['outcome']=='WIN']
    loss_pnls = [abs(s['pnl']) for s in all_signals if s['outcome']=='LOSS']
    avg_win   = round(sum(win_pnls)/len(win_pnls),2)   if win_pnls  else 0
    avg_loss  = round(sum(loss_pnls)/len(loss_pnls),2) if loss_pnls else 0
    rr        = round(avg_win/avg_loss, 2)              if avg_loss  else 0

    # By level
    by_level = defaultdict(lambda:{'w':0,'l':0,'o':0})
    for s in all_signals:
        by_level[s['level']][{'WIN':'w','LOSS':'l','OPEN':'o'}[s['outcome']]] += 1

    by_type = defaultdict(lambda:{'w':0,'l':0,'o':0})
    for s in all_signals:
        by_type[s['type']][{'WIN':'w','LOSS':'l','OPEN':'o'}[s['outcome']]] += 1

    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS — {symbol} — {len(day_results)} days")
    print(f"{'='*60}")
    print(f"  Total Signals : {total}")
    print(f"  Wins          : {wins}")
    print(f"  Losses        : {losses}")
    print(f"  Open (no exit): {opens}")
    print(f"  Win Rate      : {winrate}%")
    print(f"  Avg Win (pts) : {avg_win}")
    print(f"  Avg Loss(pts) : {avg_loss}")
    print(f"  Risk:Reward   : 1:{rr}")
    print(f"\n  — By Level —")
    for lvl, r in sorted(by_level.items()):
        total_l = r['w']+r['l']
        wr = round(r['w']/total_l*100,1) if total_l>0 else 0
        print(f"  {lvl:4}: {r['w']}W {r['l']}L {r['o']}O  WR:{wr}%")
    print(f"\n  — By Signal Type —")
    for typ, r in by_type.items():
        total_t = r['w']+r['l']
        wr = round(r['w']/total_t*100,1) if total_t>0 else 0
        print(f"  {typ:4}: {r['w']}W {r['l']}L {r['o']}O  WR:{wr}%")

    # Save JSON report
    report = {
        'symbol':symbol,'days':args.days,
        'summary':{'total':total,'wins':wins,'losses':losses,'opens':opens,
                   'winrate':winrate,'avg_win':avg_win,'avg_loss':avg_loss,'rr':rr},
        'by_level':dict(by_level), 'by_type':dict(by_type),
        'signals':all_signals,
    }
    out = f'/root/chanakya_v5/data/backtest_{symbol}_{args.days}d.json'
    with open(out,'w') as f: json.dump(report, f, indent=2)
    print(f"\n  📄 Report saved: {out}")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
