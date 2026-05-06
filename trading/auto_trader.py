"""
Chanakya AI v5.0 — Auto Trader
"""
import threading, time, logging, datetime, sqlite3
logger = logging.getLogger(__name__)

MIN_SCORE        = 65
MONITOR_INTERVAL = 10
SCAN_INTERVAL    = 300
MAX_OPEN_TRADES  = 3
AUTO_USERNAME    = "avinash"
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
                tid=t["id"]; mode=t.get("mode","PAPER"); user=t.get("username","avinash")
                hit_sl     = (dirn=="BUY" and ltp<=sl)     or (dirn=="SELL" and ltp>=sl)
                hit_target = (dirn=="BUY" and ltp>=target)  or (dirn=="SELL" and ltp<=target)

                # ── Trailing SL logic ──────────────────────────
                if not hit_sl and not hit_target:
                    risk = abs(entry - sl)  # initial risk per unit
                    profit = (ltp - entry) if dirn=="BUY" else (entry - ltp)
                    if risk > 0:
                        if profit >= risk * 2.0:
                            # Profit > 2R → trail SL to +1R (lock profit)
                            new_sl = round(entry + risk * 1.0, 2) if dirn=="BUY" else round(entry - risk * 1.0, 2)
                            if (dirn=="BUY" and new_sl > sl) or (dirn=="SELL" and new_sl < sl):
                                conn2 = sqlite3.connect(DB_PATH)
                                conn2.execute("UPDATE trades SET sl_price=?,updated_at=? WHERE id=?",
                                    (new_sl, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tid))
                                conn2.commit(); conn2.close()
                                _log(f"📈 TRAIL SL: {sym} {dirn} SL {sl}→{new_sl} (profit={profit:+.1f})")
                        elif profit >= risk * 1.0:
                            # Profit > 1R → trail SL to breakeven
                            new_sl = round(entry, 2)
                            if (dirn=="BUY" and new_sl > sl) or (dirn=="SELL" and new_sl < sl):
                                conn2 = sqlite3.connect(DB_PATH)
                                conn2.execute("UPDATE trades SET sl_price=?,updated_at=? WHERE id=?",
                                    (new_sl, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tid))
                                conn2.commit(); conn2.close()
                                _log(f"⚖️ BREAKEVEN SL: {sym} {dirn} SL→{new_sl}")

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
        # MTF predictor signals पण merge करतो
        try:
            from data_stream.cache import get as cget
            pred = cget("predictions") or []
            for p in pred:
                if p.get("confidence",0) >= MIN_SCORE and p.get("rr",0) >= 1.8:
                    # scanner format मध्ये convert
                    signals.append({
                        "symbol": p["symbol"], "direction": p["direction"],
                        "entry": p["entry"], "sl": p["sl"], "target": p["target"],
                        "score": p["confidence"], "exchange": p.get("exchange","NSE"),
                        "token": "", "type": "prediction", "fake": p.get("fake",[]),
                        "rr": p.get("rr",2.0)
                    })
        except: pass
        # Deduplicate by symbol
        seen_syms = set()
        deduped = []
        for s in signals:
            k = s["symbol"]+s["direction"]
            if k not in seen_syms:
                seen_syms.add(k); deduped.append(s)
        signals = deduped
        # ── Quality Filters ──────────────────────────
        import pytz as _pytz, datetime as _dt
        now_ist = _dt.datetime.now(_pytz.timezone("Asia/Kolkata"))
        h, mn = now_ist.hour, now_ist.minute

        # Filter 1: पहिले 15 मिनिट skip (volatile open)
        skip_open = (h == 9 and mn < 30)

        # Filter 2: Options symbols skip
        def is_option(sym):
            return any(c.isdigit() for c in str(sym)) or                    any(x in str(sym) for x in ["CE","PE","FUT"])

        # Filter 3: Index साठी careful
        INDEX_SYMS = {"NIFTY","BANKNIFTY","FINNIFTY","SENSEX"}

        # Filter 4: Gap Down/Up detect
        def detect_gap(sig):
            """Gap 0.5%+ असेल तर direction विरुद्ध trade skip"""
            try:
                ltp   = sig.get("ltp", 0)
                entry = sig.get("entry", 0)
                # candle open vs prev close gap
                return False  # placeholder
            except: return False

        # Filter 5: NIFTY overall market bias
        nifty_bias = "NEUTRAL"
        try:
            from data_stream.cache import get as cget
            nifty_candles = cget("candles_NIFTY_5m")
            if nifty_candles and len(nifty_candles) >= 5:
                from engine.indicators import ema
                closes = [float(c[4]) for c in nifty_candles]
                e9  = ema(closes, 9)
                e21 = ema(closes, 21)
                # Today open vs current
                today_open  = float(nifty_candles[0][1]) if nifty_candles else closes[0]
                today_close = closes[-1]
                gap_pct = (today_open - float(nifty_candles[-max(len(nifty_candles)//2,1)][4])) / float(nifty_candles[-max(len(nifty_candles)//2,1)][4]) * 100
                if e9 > e21 and today_close > today_open: nifty_bias = "BULL"
                elif e9 < e21 and today_close < today_open: nifty_bias = "BEAR"
        except: pass

        good = []
        for s in (signals or []):
            sym   = s.get("symbol","")
            score = s.get("score",0)
            dirn  = s.get("direction","")
            if score < MIN_SCORE: continue
            if s.get("fake"): continue
            if is_option(sym): continue
            if skip_open:
                _log(f"⏳ Skip {sym} — first 15min rule")
                continue
            if sym in INDEX_SYMS and score < 75: continue
            # Market bias filter: BEAR market मध्ये BUY skip
            if nifty_bias == "BEAR" and dirn == "BUY" and sym not in ["CRUDEOIL","NATURALGAS","GOLD"]:
                _log(f"🐻 Skip BUY {sym} — Market BEARISH")
                continue
            if nifty_bias == "BULL" and dirn == "SELL" and sym not in ["CRUDEOIL","NATURALGAS","GOLD"]:
                _log(f"🐂 Skip SELL {sym} — Market BULLISH")
                continue
            good.append(s)

        _log(f"🔍 Scan: {len(signals or [])} signals, {len(good)} qualify")
        for sig in good:
            sym=sig["symbol"]; score=sig.get("score",0); dirn=sig["direction"]
            entry=sig["entry"]; sl=sig["sl"]; target=sig["target"]
            exch=sig.get("exchange","NSE"); token=sig.get("token","")
            alert_signal(sym, dirn, entry, sl, target, score)
            if not auto: continue
            if open_count >= MAX_OPEN_TRADES:
                _log(f"⚠️ Max trades reached, skip {sym}"); continue
            # Duplicate check: same symbol already open?
            open_trades = _get_all_open_trades()
            open_syms = [t["symbol"] for t in open_trades]
            if sym in open_syms:
                _log(f"⚠️ Skip {sym} — already open")
                continue
            sig_key = f"{sym}_{dirn}_{int(entry)}"
            with _lock:
                if sig_key in _state["signals_seen"]: continue
                _state["signals_seen"].add(sig_key)
            # Capital-aware position sizing
            try:
                from trading.capital_manager import calculate_position_size, get_capital, check_daily_limit
                cap_data = get_capital(mode)
                capital  = cap_data["available"]
                # Daily limit check
                limit = check_daily_limit(capital)
                if not limit["can_trade"]:
                    _log(f"🚫 Daily limit: {limit['reason']} PnL={limit['daily_pnl']}")
                    break
                smart_qty, size_info = calculate_position_size(sym, exch, entry, sl, capital)
                if not size_info.get("can_trade", True) and mode == "LIVE":
                    _log(f"⚠️ Insufficient margin for {sym} - need Rs{size_info.get('margin_est',0):,.0f}")
                    continue
                lot_size = size_info.get("lot_size", 1)
                lots     = size_info.get("lots", 1)
                _log(f"💰 {sym} qty={smart_qty} lots={lots} risk=Rs{size_info.get('risk_amount',0)}")
            except Exception as ce:
                smart_qty = 1; lot_size = 1; lots = 1
                logger.debug("capital_manager: %s", ce)

            tid = place_trade(AUTO_USERNAME, sym, exch, dirn, entry, sl, target,
                              qty=smart_qty, token=token, strategy="AUTO_AI", mode=mode,
                              lot_size=lot_size, lots=lots)
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
