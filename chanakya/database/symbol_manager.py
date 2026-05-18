import sqlite3, datetime, os
DB_PATH = os.getenv("DB_PATH", "data/chanakya_v5.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_all_symbols(active_only=True):
    try:
        conn = get_db()
        q = "SELECT * FROM symbols" + (" WHERE is_active=1" if active_only else "") + " ORDER BY exchange,instrument_type,symbol"
        rows = conn.execute(q).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def get_user_symbols(username, role):
    """User ला access असलेले symbols return करा"""
    try:
        conn = get_db()
        # Role-based access
        rows = conn.execute("""
            SELECT s.*, sa.can_scan, sa.can_paper, sa.can_live, sa.can_signal
            FROM symbols s
            JOIN symbol_access sa ON s.id = sa.symbol_id
            WHERE s.is_active=1
            AND (
                (sa.access_type='role' AND sa.access_value=?)
                OR (sa.access_type='user' AND sa.access_value=?)
            )
            ORDER BY s.exchange, s.instrument_type, s.symbol
        """, (role, username)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def add_symbol(symbol, trading_symbol, token, exchange, instrument_type, lot_size, tick_size, created_by):
    try:
        conn = get_db()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute("""INSERT INTO symbols
            (symbol, trading_symbol, token, exchange, instrument_type, lot_size, tick_size, created_at, created_by)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (symbol.upper(), trading_symbol, token, exchange.upper(), instrument_type.upper(), lot_size, tick_size, now, created_by))
        sid = cur.lastrowid
        conn.commit()
        conn.close()
        return sid
    except Exception as e:
        print(f"add_symbol error: {e}"); return None

def delete_symbol(symbol_id):
    try:
        conn = get_db()
        conn.execute("UPDATE symbols SET is_active=0 WHERE id=?", (symbol_id,))
        conn.commit(); conn.close(); return True
    except: return False

def set_symbol_access(symbol_id, access_type, access_value, can_scan=1, can_paper=1, can_live=0, can_signal=1):
    try:
        conn = get_db()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Upsert
        existing = conn.execute("""SELECT id FROM symbol_access
            WHERE symbol_id=? AND access_type=? AND access_value=?""",
            (symbol_id, access_type, access_value)).fetchone()
        if existing:
            conn.execute("""UPDATE symbol_access SET can_scan=?,can_paper=?,can_live=?,can_signal=?
                WHERE id=?""", (can_scan, can_paper, can_live, can_signal, existing['id']))
        else:
            conn.execute("""INSERT INTO symbol_access
                (symbol_id, access_type, access_value, can_scan, can_paper, can_live, can_signal, created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (symbol_id, access_type, access_value, can_scan, can_paper, can_live, can_signal, now))
        conn.commit(); conn.close(); return True
    except Exception as e:
        print(f"set_access error: {e}"); return False

def get_app_setting(key, default=None):
    try:
        conn = get_db()
        r = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return r['value'] if r else default
    except: return default

def get_all_settings():
    try:
        conn = get_db()
        rows = conn.execute("SELECT * FROM app_settings ORDER BY key").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def update_setting(key, value, updated_by):
    try:
        conn = get_db()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""INSERT INTO app_settings (key, value, updated_at, updated_by)
            VALUES (?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?, updated_by=?""",
            (key, value, now, updated_by, value, now, updated_by))
        conn.commit(); conn.close(); return True
    except Exception as e:
        print(f"update_setting error: {e}"); return False

def search_angel_symbol(query, exchange="NSE"):
    """Angel One scrip master मधून search"""
    try:
        import json
        # v3 मधून scrip master use करूया
        scrip_path = "/root/chanakya_v3/data/scrip_master.json"
        if not os.path.exists(scrip_path):
            return []
        with open(scrip_path) as f:
            data = json.load(f)
        query = query.upper()
        results = []
        for item in data:
            if (item.get('exch_seg','').upper() == exchange.upper() and
                query in item.get('symbol','').upper()):
                results.append({
                    'symbol': item.get('symbol',''),
                    'token': item.get('token',''),
                    'exchange': item.get('exch_seg',''),
                    'instrument_type': item.get('instrumenttype','EQ'),
                    'lot_size': int(item.get('lotsize',1) or 1),
                    'tick_size': float(item.get('tick_size',0.05) or 0.05),
                })
                if len(results) >= 20: break
        return results
    except Exception as e:
        print(f"search error: {e}"); return []
