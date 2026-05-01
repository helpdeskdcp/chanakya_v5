import sqlite3, os, datetime
DB_PATH = os.getenv("DB_PATH", "data/chanakya_v5.db")

def init_db():
    try:
        os.makedirs("data", exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            symbol TEXT NOT NULL,
            exchange TEXT DEFAULT "NSE",
            trading_symbol TEXT,
            token TEXT DEFAULT "",
            direction TEXT DEFAULT "BUY",
            entry_price REAL DEFAULT 0,
            sl_price REAL DEFAULT 0,
            target_price REAL DEFAULT 0,
            qty INTEGER DEFAULT 1,
            lots INTEGER DEFAULT 1,
            lot_size INTEGER DEFAULT 1,
            status TEXT DEFAULT "OPEN",
            mode TEXT DEFAULT "PAPER",
            strategy TEXT DEFAULT "MANUAL",
            pnl REAL DEFAULT 0,
            exit_price REAL DEFAULT 0,
            exit_reason TEXT DEFAULT "",
            created_at TEXT,
            updated_at TEXT,
            closed_at TEXT
        )""")
        conn.commit(); conn.close()
    except Exception as e:
        print(f"trades init error: {e}")

def place_trade(username, symbol, exchange, direction, entry, sl, target,
                qty=1, token="", strategy="MANUAL", mode="PAPER"):
    try:
        conn = sqlite3.connect(DB_PATH)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tsym = symbol+("-EQ" if exchange=="NSE" else "")
        cur = conn.execute("""INSERT INTO trades
            (username,symbol,exchange,trading_symbol,token,direction,
             entry_price,sl_price,target_price,qty,status,mode,strategy,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (username,symbol,exchange,tsym,token,direction,
             entry,sl,target,qty,"OPEN",mode,strategy,now,now))
        trade_id = cur.lastrowid
        conn.commit(); conn.close()
        return trade_id
    except Exception as e:
        print(f"place_trade error: {e}"); return None

def get_open_trades(username):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE username=? AND status=? ORDER BY id DESC",
            (username,"OPEN")).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def get_all_trades(username, limit=50):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE username=? ORDER BY id DESC LIMIT ?",
            (username,limit)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def close_trade(trade_id, exit_price, reason="manual"):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        t = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not t: conn.close(); return False
        t = dict(t)
        qty = t["qty"] or 1
        if t["direction"] == "BUY":
            pnl = (exit_price - t["entry_price"]) * qty
        else:
            pnl = (t["entry_price"] - exit_price) * qty
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE trades SET status=?,exit_price=?,pnl=?,exit_reason=?,closed_at=?,updated_at=? WHERE id=?",
            ("CLOSED",exit_price,round(pnl,2),reason,now,now,trade_id))
        conn.commit(); conn.close()
        return True
    except Exception as e:
        print(f"close_trade error: {e}"); return False

def get_pnl_summary(username):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE username=? AND status=?",
            (username,"CLOSED")).fetchall()
        conn.close()
        if not rows: return {"total_pnl":0,"win_rate":0,"total_trades":0,"wins":0,"losses":0}
        trades = [dict(r) for r in rows]
        total = len(trades)
        wins = sum(1 for t in trades if t["pnl"]>0)
        total_pnl = sum(t["pnl"] for t in trades)
        return {"total_pnl":round(total_pnl,2),"win_rate":round(wins/total*100,1),
                "total_trades":total,"wins":wins,"losses":total-wins}
    except: return {"total_pnl":0,"win_rate":0,"total_trades":0}

init_db()
