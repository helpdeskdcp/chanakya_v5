"""
Chanakya Scalping Engine — Self-Learning AI
Reinforcement: Adaptive scoring based on past performance
"""
import sqlite3, json, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'scalping_ai.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS scalping_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, symbol TEXT, signal TEXT,
        strategy TEXT, entry REAL, exit_price REAL,
        sl REAL, target REAL, pnl REAL, result TEXT,
        rsi REAL, ema9 REAL, ema21 REAL, vwap REAL,
        atr REAL, vol_regime TEXT, trend TEXT,
        score INTEGER, confidence REAL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS strategy_weights (
        strategy TEXT PRIMARY KEY,
        weight REAL DEFAULT 1.0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        total_pnl REAL DEFAULT 0,
        win_rate REAL DEFAULT 0.5
    )''')
    # Init weights
    for s in ['BREAKOUT','REVERSAL','RANGE_BOUND']:
        conn.execute('INSERT OR IGNORE INTO strategy_weights (strategy) VALUES (?)', (s,))
    conn.commit(); conn.close()

def log_trade(trade_data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''INSERT INTO scalping_trades
        (timestamp,symbol,signal,strategy,entry,exit_price,sl,target,pnl,result,
         rsi,ema9,ema21,vwap,atr,vol_regime,trend,score,confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (datetime.now().isoformat(),
         trade_data.get('symbol'),trade_data.get('signal'),
         trade_data.get('strategy'),trade_data.get('entry'),
         trade_data.get('exit'),trade_data.get('sl'),
         trade_data.get('target'),trade_data.get('pnl'),
         trade_data.get('result'),trade_data.get('rsi'),
         trade_data.get('ema9'),trade_data.get('ema21'),
         trade_data.get('vwap'),trade_data.get('atr'),
         trade_data.get('vol_regime'),trade_data.get('trend'),
         trade_data.get('score'),trade_data.get('confidence',0)))
    conn.commit(); conn.close()
    update_weights(trade_data.get('strategy'), trade_data.get('pnl',0))

def update_weights(strategy, pnl):
    """Self-learning: Adjust strategy weights based on PnL"""
    if not strategy: return
    conn = sqlite3.connect(DB_PATH)
    win = 1 if pnl > 0 else 0
    conn.execute('''UPDATE strategy_weights SET
        wins = wins + ?, losses = losses + ?,
        total_pnl = total_pnl + ?
        WHERE strategy = ?''', (win, 1-win, pnl, strategy))
    # Recalculate win_rate and weight
    row = conn.execute('SELECT wins, losses FROM strategy_weights WHERE strategy=?',
                       (strategy,)).fetchone()
    if row:
        total = row[0] + row[1]
        wr = row[0] / total if total > 0 else 0.5
        # Weight: good strategy gets boost
        weight = max(0.5, min(2.0, 0.5 + wr * 1.5))
        conn.execute('UPDATE strategy_weights SET win_rate=?, weight=? WHERE strategy=?',
                     (round(wr,4), round(weight,4), strategy))
    conn.commit(); conn.close()

def get_strategy_weights():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT strategy,weight,win_rate,wins,losses,total_pnl FROM strategy_weights').fetchall()
    conn.close()
    return {r[0]:{"weight":r[1],"win_rate":r[2],"wins":r[3],"losses":r[4],"total_pnl":r[5]} for r in rows}

def get_performance_stats():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('''SELECT result,COUNT(*),SUM(pnl),AVG(pnl) FROM scalping_trades
                           GROUP BY result''').fetchall()
    total = conn.execute('SELECT COUNT(*),SUM(pnl) FROM scalping_trades').fetchone()
    conn.close()
    stats = {"total_trades":total[0] or 0,"total_pnl":round(total[1] or 0,2)}
    for r in rows:
        stats[r[0]] = {"count":r[1],"total_pnl":round(r[2] or 0,2),"avg_pnl":round(r[3] or 0,2)}
    wins = stats.get("WIN",{}).get("count",0)
    total_t = stats["total_trades"]
    stats["win_rate"] = round(wins/total_t*100,1) if total_t > 0 else 0
    return stats

def adaptive_confidence(base_score, strategy, symbol):
    """Boost/reduce confidence based on historical performance"""
    weights = get_strategy_weights()
    w = weights.get(strategy,{}).get("weight",1.0)
    return min(100, int(base_score * w))

init_db()
