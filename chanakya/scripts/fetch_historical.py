"""
Chanakya AI v5 — Historical Data Fetcher
Usage: python3 scripts/fetch_historical.py
Fetches maximum available data from Angel One API
"""
import sys, time, sqlite3
sys.path.insert(0, '/app/chanakya')

SYMBOLS = [
    ("NIFTY","99926000","NSE"),("BANKNIFTY","99926009","NSE"),
    ("FINNIFTY","99926037","NSE"),("RELIANCE","2885","NSE"),
    ("TCS","11536","NSE"),("HDFCBANK","1333","NSE"),
    ("ICICIBANK","4963","NSE"),("SBIN","3045","NSE"),
    ("WIPRO","3787","NSE"),("INFY","1594","NSE"),
    ("TATASTEEL","3499","NSE"),("SUZLON","12018","NSE"),
    ("CRUDEOIL","488290","MCX"),("NATURALGAS","488505","MCX"),
]
TIMEFRAMES = [("ONE_DAY","1D",2000),("FIVE_MINUTE","5m",200)]

from broker.global_broker import get_broker
b = get_broker()
conn = sqlite3.connect("data/chanakya_v5.db")
conn.execute("""CREATE TABLE IF NOT EXISTS historical_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, exchange TEXT, timeframe TEXT,
    ts TEXT, open REAL, high REAL, low REAL,
    close REAL, volume INTEGER,
    UNIQUE(symbol, timeframe, ts))""")
conn.commit()

total = 0
for sym,token,exch in SYMBOLS:
    for interval,tf,days in TIMEFRAMES:
        time.sleep(0.8)
        try:
            candles = b.get_candles(token, exch, interval, days=days)
            if not candles: continue
            ins = 0
            for c in candles:
                conn.execute("""INSERT OR IGNORE INTO historical_candles
                    (symbol,exchange,timeframe,ts,open,high,low,close,volume)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sym,exch,tf,str(c[0]),float(c[1]),float(c[2]),
                     float(c[3]),float(c[4]),int(float(c[5]))))
                ins += conn.total_changes > 0 and 1 or 0
            conn.commit(); total += ins
            print(f"✅ {sym:12} {tf}: {len(candles)} candles +{ins} new")
        except Exception as e:
            print(f"❌ {sym} {tf}: {e}")

print(f"\nTotal: {total:,} candles inserted")
conn.close()
