"""
download_historical.py — Chanakya v5
Downloads historical OHLCV data from Angel One and saves to local SQLite.
Usage: python3 scripts/download_historical.py
"""
import sys, os, sqlite3, time, logging
from datetime import datetime, timedelta

sys.path.insert(0, '/root/chanakya_v5')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = '/root/chanakya_v5/data/historical.db'

SYMBOLS = [
    {"symbol":"NIFTY",      "token":"99926000","exchange":"NSE"},
    {"symbol":"BANKNIFTY",  "token":"99926009","exchange":"NSE"},
    {"symbol":"NATURALGAS", "token":"488505",  "exchange":"MCX"},
    {"symbol":"CRUDEOIL",   "token":"488290",  "exchange":"MCX"},
    {"symbol":"GOLD",       "token":"459277",  "exchange":"MCX"},
    {"symbol":"SILVER",     "token":"464150",  "exchange":"MCX"},
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS candles_daily (
        symbol TEXT, date TEXT, open REAL, high REAL,
        low REAL, close REAL, volume INTEGER,
        PRIMARY KEY (symbol, date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS candles_5min (
        symbol TEXT, datetime TEXT, open REAL, high REAL,
        low REAL, close REAL, volume INTEGER,
        PRIMARY KEY (symbol, datetime))''')
    c.execute('''CREATE TABLE IF NOT EXISTS download_log (
        symbol TEXT, interval TEXT, last_updated TEXT,
        records INTEGER, PRIMARY KEY (symbol, interval))''')
    conn.commit()
    return conn

def save_candles(conn, table, symbol, rows):
    c = conn.cursor()
    inserted = 0
    for row in rows:
        try:
            ts = str(row[0])[:16].replace('T',' ')
            date_key = ts[:10] if table == 'candles_daily' else ts
            c.execute(f'''INSERT OR REPLACE INTO {table}
                (symbol,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)
            ''' if table == 'candles_daily' else f'''INSERT OR REPLACE INTO {table}
                (symbol,datetime,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)
            ''', (symbol, date_key,
                  float(row[1]), float(row[2]),
                  float(row[3]), float(row[4]),
                  int(float(row[5])) if len(row)>5 else 0))
            inserted += 1
        except Exception as e:
            pass
    conn.commit()
    return inserted

def update_log(conn, symbol, interval, records):
    conn.execute('''INSERT OR REPLACE INTO download_log
        VALUES (?,?,?,?)''', (symbol, interval,
        datetime.now().strftime('%Y-%m-%d %H:%M'), records))
    conn.commit()

def main():
    print(f"\n{'='*55}")
    print(f"  CHANAKYA v5 — HISTORICAL DATA DOWNLOADER")
    print(f"  DB: {DB_PATH}")
    print(f"{'='*55}\n")

    from broker.global_broker import get_broker
    broker = get_broker()
    if not broker:
        print("❌ Broker unavailable"); sys.exit(1)

    conn = init_db()
    total_saved = 0

    for stock in SYMBOLS:
        sym   = stock['symbol']
        token = stock['token']
        exch  = stock['exchange']

        print(f"\n  📥 {sym} [{exch}]")

        # ── Daily candles — 5 years ──────────────────────────
        print(f"     Downloading DAILY (5yr)...", end='', flush=True)
        time.sleep(0.4)
        raw_d = broker.get_candles(token, exch, 'ONE_DAY', days=2000)
        if raw_d:
            n = save_candles(conn, 'candles_daily', sym, raw_d)
            update_log(conn, sym, 'ONE_DAY', n)
            print(f" ✅ {n} candles ({raw_d[0][0][:10]} → {raw_d[-1][0][:10]})")
            total_saved += n
        else:
            print(f" ❌ No data")

        # ── 5-min candles — 100 days ─────────────────────────
        print(f"     Downloading 5MIN (100d)...", end='', flush=True)
        time.sleep(0.5)
        raw_5 = broker.get_candles(token, exch, 'FIVE_MINUTE', days=100)
        if raw_5:
            n = save_candles(conn, 'candles_5min', sym, raw_5)
            update_log(conn, sym, 'FIVE_MINUTE', n)
            print(f" ✅ {n} candles ({raw_5[0][0][:10]} → {raw_5[-1][0][:10]})")
            total_saved += n
        else:
            print(f" ❌ No data")

        time.sleep(0.5)

    # ── Summary ───────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  Total records saved: {total_saved}")

    c = conn.cursor()
    print(f"\n  {'Symbol':<12} {'Interval':<12} {'Records':>8} {'Updated'}")
    print(f"  {'─'*50}")
    for row in c.execute("SELECT symbol,interval,records,last_updated FROM download_log ORDER BY symbol,interval"):
        print(f"  {row[0]:<12} {row[1]:<12} {row[2]:>8} {row[3]}")

    # DB size
    size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"\n  DB size: {size_mb:.2f} MB")
    print(f"  Path: {DB_PATH}")
    print(f"{'='*55}\n")
    conn.close()

if __name__ == '__main__':
    main()
