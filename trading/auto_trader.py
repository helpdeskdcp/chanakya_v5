"""
Chanakya AI v5.0 — Auto Trader
"""
import threading, time, logging, datetime, sqlite3
logger = logging.getLogger(__name__)

MIN_SCORE        = 65
MONITOR_INTERVAL = 10
SCAN_INTERVAL    = 300
MAX_OPEN_TRADES  = 3
AUTO_USERNAME    = "system"
DB_PATH          = "data/chanakya_v5.db"

_state = {
    "running":False,"mode":"PAPER","auto_trade":False,
    "last_scan":None,"last_monitor":None,"open_count":0,
    "today_pnl":0.0,"signals_seen":set(),"log":[],
}
_lock = threading.Lock()

def _log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    logger.info(entry)
    with _lock:
        _state["log"].append(entry)
        if len(_state["log"]) > 20:
            _state["log"].pop(0)

def _get_all_open_trades():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_open_trades error: {e}"); return []

def _monitor_positions():
    try:
        from broker.global_broker import get_broker
        from notifications.telegram import alert_trade_close
        from trading.paper_engine import close_trade
        broker = get_broker()
        if not broker or not broker.is_connected(): return
        trades = _get_all_open_trades()
        with _lock:
            _state["open_count"] = len(trades)
            _state["last_monitor"] = datetime.datetime.now().strftime("%H:%M:%S")
        for t in trades:
            try:
                ltp = broker.get_ltp(t.get("exchange","NSE"), t.get("symbol",""), t.get("token",""))
                if not ltp or ltp <= 0: continue
                entry=float(t["entry_price"]); sl=float(t["sl_price"]); target=float(t["target_price"])
                qty=int(t.get("qty",1)); sym=t["symbol"]; dirn=t["direction"]
                tid=t["id"]; mode=t.get("mode","PAPER"); user=t.get("username","system")
                hit_sl     = (dirn=="BUY" and ltp<=sl)     or (dirn=="SELL" and ltp>=sl)
                hit_target = (dirn=="BUY" and ltp>=target)  or (dirn=="SELL" and ltp<=target)
                if hit_target or hit_sl:
                    reason = "TARGET" if hit_target else "STOPLOSS"
                    pnl = round((ltp-entry)*qty if dirn=="BUY" else (entry-ltp)*qty, 2)
                    ok = close_trade(tid, ltp, reason)
                    if ok:
                        with _lock: _state["today_pnl"] += pnl
                        emoji = "🎯" if hit_target else "🛑"
                        _log(f"{emoji} {reason}: {sym} {dirn} LTP={ltp} P&L=₹{pnl:+.0f}")
                        alert_trade_close(user, sym, dirn, entry, ltp, pnl, mode)
            except Exception as e: tid2=t.get("id"); logger.debug(f"Monitor {tid2}: {e}")
    except Exception as e: logger.error(f"Monitor error: {e}")

def _scan_and_trade():
    try:
        from engine.scanner import scan_all
        from broker.global_broker import get_broker
        from trading.paper_engine import place_trade
        from notifications.telegram import alert_signal, alert_trade_open
        broker = get_broker()
        if not broker or not broker.is_connected():
            _log("⚠️ Broker not connected"); return
        with _lock:
            _state["last_scan"] = datetime.datetime.now().strftime("%H:%M:%S")
            auto=_state["auto_trade"]; mode=_state["mode"]; open_count=_state["open_count"]
        signals = scan_all(broker)
        good = [s for s in (signals or []) if (s.get("score") or 0) >= MIN_SCORE]
        _log(f"🔍 Scan: {len(signals or [])} signals, {len(good)} qualify")
        for sig in good:
            sym=sig["symbol"]; score=sig.get("score",0); dirn=sig["direction"]
            entry=sig["entry"]; sl=sig["sl"]; target=sig["target"]
            exch=sig.get("exchange","NSE"); token=sig.get("token","")
            alert_signal(sym, dirn, entry, sl, target, score)
            if not auto: continue
            if open_count >= MAX_OPEN_TRADES:
                _log(f"⚠️ Max trades reached, skip {sym}"); continue
            sig_key = f"{sym}_{dirn}_{int(entry)}"
            with _lock:
                if sig_key in _state["signals_seen"]: continue
                _state["signals_seen"].add(sig_key)
            tid = place_trade(AUTO_USERNAME, sym, exch, dirn, entry, sl, target,
                              qty=1, token=token, strategy="AUTO_AI", mode=mode)
            if tid:
                open_count += 1
                with _lock: _state["open_count"] = open_count
                _log(f"✅ AUTO {mode}: {dirn} {sym} @₹{entry} #{tid}")
                alert_trade_open(AUTO_USERNAME, sym, dirn, entry, sl, target, 1, mode)
            else:
                _log(f"❌ Auto place failed: {sym}")
        with _lock: _state["signals_seen"].clear()
    except Exception as e: logger.error(f"Scan error: {e}")

def _run_loop():
    _log("🚀 Auto Trader started")
    last_scan_time = 0
    while True:
        try:
            with _lock:
                if not _state["running"]: break
            _monitor_positions()
            if time.time() - last_scan_time >= SCAN_INTERVAL:
                _scan_and_trade()
                last_scan_time = time.time()
            time.sleep(MONITOR_INTERVAL)
        except Exception as e:
            logger.error(f"Loop error: {e}"); time.sleep(30)
    _log("⛔ Auto Trader stopped")

def start(mode="PAPER", auto_trade=False):
    with _lock:
        if _state["running"]: return {"success":False,"error":"Already running"}
        _state.update({"running":True,"mode":mode,"auto_trade":auto_trade,"today_pnl":0.0,"log":[]})
    threading.Thread(target=_run_loop, daemon=True, name="AutoTrader").start()
    _log(f"✅ Mode={mode} AutoTrade={'ON' if auto_trade else 'OFF'}")
    return {"success":True,"mode":mode,"auto_trade":auto_trade}

def stop():
    with _lock: _state["running"] = False
    _log("⛔ Stop requested")
    return {"success":True}

def set_auto_trade(enabled, mode=None):
    with _lock:
        _state["auto_trade"] = enabled
        if mode: _state["mode"] = mode
    _log(f"🔄 AutoTrade={'ON' if enabled else 'OFF'}")
    return {"success":True}

def get_status():
    with _lock:
        return {
            "running":_state["running"],"auto_trade":_state["auto_trade"],
            "mode":_state["mode"],"open_count":_state["open_count"],
            "today_pnl":round(_state["today_pnl"],2),
            "last_scan":_state["last_scan"],"last_monitor":_state["last_monitor"],
            "min_score":MIN_SCORE,"max_trades":MAX_OPEN_TRADES,
            "log":list(_state["log"]),
        }
