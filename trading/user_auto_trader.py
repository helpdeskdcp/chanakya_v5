"""
Chanakya AI v5 — Multi-User Auto Trader
Per-user trades, login trigger, 11:40 auto-off
"""
import threading, time, logging, datetime, sqlite3
logger = logging.getLogger(__name__)
DB = "data/chanakya_v5.db"

def set_user_auto_trade(username, role, auto_on=True):
    try:
        conn = sqlite3.connect(DB)
        now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""INSERT OR REPLACE INTO user_trading_state
            (username,auto_trade,mode,login_at,trades_today,pnl_today,updated_at)
            VALUES (?,?,\'PAPER\',?,0,0.0,?)""", (username, 1 if auto_on else 0, now, now))
        conn.commit(); conn.close()
        logger.info("User %s auto_trade=%s", username, auto_on)
    except Exception as e:
        logger.error("set_user_auto_trade: %s", e)

def get_active_traders():
    try:
        conn = sqlite3.connect(DB)
        rows = conn.execute("""
            SELECT uts.username, u.role, uts.mode
            FROM user_trading_state uts
            JOIN users u ON uts.username=u.username
            WHERE uts.auto_trade=1 AND u.is_active=1
        """).fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error("get_active_traders: %s", e); return []

def get_daily_pnl_user(username):
    try:
        conn = sqlite3.connect(DB)
        today = datetime.date.today().strftime("%Y-%m-%d")
        r = conn.execute("""
            SELECT COUNT(*),
            ROUND(SUM(CASE WHEN status='CLOSED'
                THEN pnl*COALESCE(NULLIF(lot_size,0),1) ELSE 0 END),2)
            FROM trades WHERE username=? AND created_at>=?
        """, (username, today+" 00:00:00")).fetchone()
        conn.close()
        return {"trades": r[0] or 0, "total_pnl": r[1] or 0}
    except: return {"trades":0,"total_pnl":0}

def check_user_can_trade(username, capital):
    d = get_daily_pnl_user(username)
    if d["trades"] >= 5: return False, "MAX_TRADES(5)"
    if d["total_pnl"] <= -(capital*0.05): return False, "DAILY_LOSS_5%"
    return True, "OK"

def place_user_trade(username, sig, capital):
    try:
        from trading.capital_manager import calculate_position_size
        from trading.paper_engine import place_trade
        sym=sig["symbol"]; exch=sig["exchange"]; dirn=sig["direction"]
        entry=sig["entry"]; sl=sig["sl"]; target=sig["target"]
        token=sig.get("token","")
        # Duplicate check
        conn = sqlite3.connect(DB)
        open_syms = [r[0] for r in conn.execute(
            "SELECT symbol FROM trades WHERE username=? AND status='OPEN'",
            (username,)).fetchall()]
        conn.close()
        if sym in open_syms: return None, f"Already open"
        qty, info = calculate_position_size(sym, exch, entry, sl, capital)
        # Ensure correct lot_size always
        from trading.capital_manager import get_lot_size as _gls
        correct_lot = _gls(sym, exch)
        actual_lot  = info.get("lot_size", correct_lot) or correct_lot
        actual_lots = info.get("lots", 1) or 1
        actual_qty  = actual_lots * actual_lot
        tid = place_trade(username, sym, exch, dirn, entry, sl, target,
                         qty=actual_qty, token=token, strategy="AUTO_AI", mode="PAPER",
                         lot_size=actual_lot, lots=actual_lots)
        return tid, f"qty={actual_qty} lots={actual_lots} lot={actual_lot}"
    except Exception as e:
        logger.error("place_user_trade %s: %s", username, e)
        return None, str(e)

def auto_off_1140():
    """11:40 AM ला non-admin users चे auto trade OFF"""
    try:
        conn = sqlite3.connect(DB)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""UPDATE user_trading_state
            SET auto_trade=0, auto_off_at=?, updated_at=?
            WHERE username NOT IN (
                SELECT username FROM users
                WHERE role IN ('administrator','developer')
            )""", (now, now))
        n = conn.total_changes; conn.commit(); conn.close()
        logger.info("11:40 auto-OFF: %d users", n)
        return n
    except Exception as e:
        logger.error("auto_off_1140: %s", e); return 0

def process_signal_for_all_users(sig):
    """एक signal सर्व active users साठी process करतो"""
    from trading.capital_manager import get_capital
    traders = get_active_traders()
    results = []
    for username, role, mode in traders:
        try:
            cap = get_capital(mode, username)["available"]
            can, reason = check_user_can_trade(username, cap)
            if not can:
                logger.debug("Skip %s: %s", username, reason)
                continue
            tid, msg = place_user_trade(username, sig, cap)
            if tid:
                logger.info("AUTO %s→%s %s %s @%s #%d",
                    username, sig['symbol'], sig['direction'],
                    mode, sig['entry'], tid)
                # Telegram alert
                try:
                    from notifications.telegram import alert_trade_open
                    alert_trade_open(username, sig['symbol'], sig['direction'],
                        sig['entry'], sig['sl'], sig['target'], 1, mode)
                except: pass
                results.append({"username":username,"tid":tid})
        except Exception as e:
            logger.error("process_signal %s: %s", username, e)
    return results

def run_1140_scheduler():
    """Daily 11:40 AM auto-off scheduler"""
    logger.info("11:40 scheduler started")
    while True:
        try:
            import pytz
            now = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
            # 11:40 AM check
            if now.hour == 11 and now.minute == 40:
                n = auto_off_1140()
                logger.info("11:40 AM: auto-OFF %d users", n)
                time.sleep(61)  # 1 min wait (next check 11:41)
            time.sleep(30)
        except Exception as e:
            logger.error("1140_scheduler: %s", e)
            time.sleep(60)
