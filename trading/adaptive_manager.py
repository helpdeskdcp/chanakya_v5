"""
Chanakya AI v5 — Adaptive Trade Manager
हर 5 seconds: LTP check, SL/Target adapt, Telegram alerts
"""
import threading, time, logging, datetime, sqlite3
logger = logging.getLogger(__name__)
DB_PATH = "data/chanakya_v5.db"

# Adaptive settings
MONITOR_INTERVAL  = 5    # seconds
ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TG = 3.0
ALERT_COOLDOWN    = 60   # seconds between same alerts

_state = {"running": False, "alerts_sent": {}, "adaptations": []}
_lock  = threading.Lock()

def _log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    logger.info(entry)
    with _lock:
        _state["adaptations"].append(entry)
        if len(_state["adaptations"]) > 50:
            _state["adaptations"].pop(0)

def _can_alert(key):
    """Same alert हर 60s पेक्षा जास्त नाही"""
    with _lock:
        last = _state["alerts_sent"].get(key, 0)
        if time.time() - last > ALERT_COOLDOWN:
            _state["alerts_sent"][key] = time.time()
            return True
    return False

def _send_alert(msg):
    try:
        from notifications.telegram import send_message
        send_message(msg)
    except:
        try:
            from notifications.telegram import _send
            _send(msg)
        except: pass

def _get_open_trades():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def _update_trade(tid, sl=None, target=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if sl and target:
            conn.execute(
                "UPDATE trades SET sl_price=?, target_price=?, updated_at=? WHERE id=?",
                (sl, target, now, tid))
        elif sl:
            conn.execute(
                "UPDATE trades SET sl_price=?, updated_at=? WHERE id=?",
                (sl, now, tid))
        elif target:
            conn.execute(
                "UPDATE trades SET target_price=?, updated_at=? WHERE id=?",
                (target, now, tid))
        conn.commit(); conn.close()
    except Exception as e:
        logger.error("update_trade: %s", e)

def _close_trade(tid, ltp, reason):
    try:
        from trading.paper_engine import close_trade
        return close_trade(tid, ltp, reason)
    except: return False

def _adaptive_monitor():
    """Core loop: हर 5 seconds सगळे open trades check"""
    _log("🔱 Adaptive Manager started")
    while True:
        try:
            with _lock:
                if not _state["running"]: break

            trades = _get_open_trades()
            if not trades:
                time.sleep(MONITOR_INTERVAL); continue

            from broker.global_broker import get_broker
            from engine.indicators import atr
            from engine.smart_money import market_structure, detect_bos
            from data_stream.cache import get as cget

            broker = get_broker()
            if not broker or not broker.is_connected():
                time.sleep(MONITOR_INTERVAL); continue

            for t in trades:
                try:
                    sym   = t["symbol"]
                    tid   = t["id"]
                    dirn  = t["direction"]
                    entry = float(t["entry_price"])
                    # Always fresh read from DB
                    import sqlite3 as _sq
                    _c2 = _sq.connect(DB_PATH)
                    _tr = _c2.execute(
                        "SELECT sl_price, target_price FROM trades WHERE id=?",
                        (tid,)).fetchone()
                    _c2.close()
                    sl  = float(_tr[0]) if _tr else float(t["sl_price"])
                    tgt = float(_tr[1]) if _tr else float(t["target_price"])
                    exch  = t.get("exchange", "NSE")
                    token = t.get("token", "")
                    user  = t.get("username", "avinash")

                    # Live LTP
                    ltp = broker.get_ltp(exch, sym, token)
                    if not ltp or ltp <= 0: continue
                    ltp = float(ltp)
                    if ltp <= 0: continue

                    # ── 1. SL/Target hit check ─────────────
                    hit_sl  = (dirn=="BUY" and ltp<=sl) or (dirn=="SELL" and ltp>=sl)
                    hit_tgt = (dirn=="BUY" and ltp>=tgt) or (dirn=="SELL" and ltp<=tgt)

                    lot_size   = int(t.get("lot_size") or t.get("qty") or 1)
                    lots       = int(t.get("lots") or 1)
                    multiplier = lot_size * lots

                    if hit_tgt:
                        pnl = round(((ltp-entry) if dirn=="BUY" else (entry-ltp)) * multiplier, 2)
                        _close_trade(tid, ltp, "TARGET")
                        # Capital update
                        try:
                            from trading.capital_manager import update_paper_capital
                            new_bal = update_paper_capital(t.get("username","avinash"), pnl, tid)
                            bal_str = f"Balance: ₹{new_bal:,.0f}" if new_bal else ""
                        except: bal_str = ""
                        msg = f"🎯 TARGET HIT!\n{sym} {dirn}\nEntry: ₹{entry} → Exit: ₹{ltp}\nP&L: +₹{pnl:,.0f}\n{bal_str}"
                        _log(f"🎯 TARGET: {sym} PnL=+₹{pnl} {bal_str}")
                        if _can_alert(f"close_{tid}"): _send_alert(msg)
                        continue

                    if hit_sl:
                        pnl = round(((ltp-entry) if dirn=="BUY" else (entry-ltp)) * multiplier, 2)
                        _close_trade(tid, ltp, "STOPLOSS")
                        # Capital update
                        try:
                            from trading.capital_manager import update_paper_capital
                            new_bal = update_paper_capital(t.get("username","avinash"), pnl, tid)
                            bal_str = f"Balance: ₹{new_bal:,.0f}" if new_bal else ""
                        except: bal_str = ""
                        msg = f"🛑 STOPLOSS HIT!\n{sym} {dirn}\nEntry: ₹{entry} → Exit: ₹{ltp}\nP&L: ₹{pnl:,.0f}\n{bal_str}"
                        _log(f"🛑 STOPLOSS: {sym} PnL=₹{pnl} {bal_str}")
                        if _can_alert(f"close_{tid}"): _send_alert(msg)
                        continue

                    # ── 2. Adaptive SL/Target using live ATR ──
                    candles = cget(f"candles_{sym}_5m")
                    if candles and len(candles) >= 14:
                        live_atr = atr(candles[-20:])
                        if live_atr > 0:
                            profit = (ltp-entry) if dirn=="BUY" else (entry-ltp)
                            risk   = abs(entry - sl)

                            # Trailing SL levels
                            if profit >= risk * 2.0:
                                new_sl = round(entry + risk*1.0, 2) if dirn=="BUY" else round(entry - risk*1.0, 2)
                                if (dirn=="BUY" and new_sl > sl) or (dirn=="SELL" and new_sl < sl):
                                    _update_trade(tid, sl=new_sl)
                                    msg = f"📈 TRAIL SL +2R\n{sym} {dirn}\nSL: ₹{sl} → ₹{new_sl}\nLTP: ₹{ltp} | Profit locked: ₹{round(profit,1)}"
                                    _log(f"📈 TRAIL SL@2R: {sym} {sl}→{new_sl}")
                                    if _can_alert(f"trail2r_{tid}"): _send_alert(msg)
                                    sl = new_sl

                            elif profit >= risk * 1.0:
                                new_sl = round(entry, 2)
                                if (dirn=="BUY" and new_sl > sl) or (dirn=="SELL" and new_sl < sl):
                                    _update_trade(tid, sl=new_sl)
                                    msg = f"⚖️ BREAKEVEN SL\n{sym} {dirn}\nSL → Breakeven ₹{new_sl}\nLTP: ₹{ltp}"
                                    _log(f"⚖️ BREAKEVEN: {sym} SL→{new_sl}")
                                    if _can_alert(f"be_{tid}"): _send_alert(msg)
                                    sl = new_sl

                            # ── Hybrid Adaptive Target (backtest +29%) ──
                            sym_mult  = TARGET_MULT.get(sym, TARGET_MULT["DEFAULT"])
                            tgt_3atr  = round(entry + 3*live_atr, 1) if dirn=="BUY" else round(entry - 3*live_atr, 1)
                            tgt_final = round(entry + sym_mult*live_atr, 1) if dirn=="BUY" else round(entry - sym_mult*live_atr, 1)

                            def _mom_ok():
                                try:
                                    from engine.indicators import ema as _em, rsi as _rs
                                    _cl=[float(c[4]) for c in candles[-20:]]
                                    _e9=_em(_cl,9); _e21=_em(_cl,21); _rv=_rs(_cl)
                                    return (_e9>_e21 and _rv>45) if dirn=="BUY" else (_e9<_e21 and _rv<55)
                                except: return True

                            hit_3atr = (dirn=="BUY" and ltp>=tgt_3atr) or (dirn=="SELL" and ltp<=tgt_3atr)

                            if hit_3atr and sym_mult > 3.0 and profit > 0:
                                if _mom_ok():
                                    if (dirn=="BUY" and tgt_final>tgt) or (dirn=="SELL" and tgt_final<tgt):
                                        _update_trade(tid, target=tgt_final)
                                        msg = f"🚀 TARGET EXTENDED {sym_mult}x!\n{sym} {dirn}\n3×={tgt_3atr} → {sym_mult}×={tgt_final}\nLTP: ₹{ltp}"
                                        _log(f"🚀 EXTENDED {sym_mult}x: {sym} {tgt}→{tgt_final}")
                                        if _can_alert(f"tgt_{tid}"): _send_alert(msg)
                            elif profit > 0 and sym not in MOMENTUM_EXIT_SYMS:
                                new_tgt = round(ltp + live_atr*ATR_MULTIPLIER_TG, 1) if dirn=="BUY" else round(ltp - live_atr*ATR_MULTIPLIER_TG, 1)
                                if dirn=="BUY" and new_tgt > tgt:
                                    _update_trade(tid, target=new_tgt)
                                    _log(f"🚀 TGT UPGRADED: {sym} {tgt}→{new_tgt}")
                                elif dirn=="SELL" and new_tgt < tgt:
                                    _update_trade(tid, target=new_tgt)
                                    _log(f"🚀 TGT UPGRADED: {sym} {tgt}→{new_tgt}")

                            if sym in MOMENTUM_EXIT_SYMS and profit >= risk*0.8 and not _mom_ok():
                                pnl_m = round(profit * (int(t.get("lot_size") or 1)), 2)
                                _close_trade(tid, ltp, "MOMENTUM_EXIT")
                                try:
                                    from trading.capital_manager import update_paper_capital
                                    update_paper_capital(t.get("username","avinash"), pnl_m, tid)
                                except: pass
                                msg = f"📊 MOMENTUM EXIT\n{sym} {dirn} LTP: ₹{ltp}\nP&L: ₹{pnl_m:+,.0f}"
                                _log(f"📊 MOM_EXIT: {sym} P&L=₹{pnl_m}")
                                if _can_alert(f"close_{tid}"): _send_alert(msg)
                                continue

                    # ── 3. Market Structure Change alert ──────
                    if candles and len(candles) >= 20:
                        struct = market_structure(candles)
                        bos    = detect_bos(candles)
                        if dirn=="BUY" and bos=="BOS_BEAR":
                            msg = f"⚠️ STRUCTURE CHANGE!\n{sym} BUY trade\nBOS_BEAR detected!\nLTP: ₹{ltp} | Consider exit"
                            _log(f"⚠️ BOS_BEAR on BUY {sym}")
                            if _can_alert(f"bos_{tid}"): _send_alert(msg)
                        elif dirn=="SELL" and bos=="BOS_BULL":
                            msg = f"⚠️ STRUCTURE CHANGE!\n{sym} SELL trade\nBOS_BULL detected!\nLTP: ₹{ltp} | Consider exit"
                            _log(f"⚠️ BOS_BULL on SELL {sym}")
                            if _can_alert(f"bos_{tid}"): _send_alert(msg)

                    # ── 4. Live P&L log (lot_size aware) ──
                    lot_size   = int(t.get("lot_size") or t.get("qty") or 1)
                    lots       = int(t.get("lots") or 1)
                    multiplier = lot_size * lots
                    unrealized = round(((ltp-entry) if dirn=="BUY" else (entry-ltp)) * multiplier, 2)
                    per_unit   = round((ltp-entry) if dirn=="BUY" else (entry-ltp), 2)
                    _log(f"📊 {sym} {dirn} LTP=₹{ltp} | P&L=₹{unrealized:+.0f} ({per_unit:+.2f}×{multiplier}) | SL=₹{sl} | T=₹{tgt}")

                except Exception as e:
                    logger.debug("adaptive %s: %s", t.get("symbol"), e)

        except Exception as e:
            logger.error("adaptive_loop: %s", e)

        time.sleep(MONITOR_INTERVAL)

    _log("⛔ Adaptive Manager stopped")

def start():
    with _lock:
        if _state["running"]: return
        _state["running"] = True
    threading.Thread(target=_adaptive_monitor, daemon=True, name="AdaptiveManager").start()
    _log("✅ Adaptive Manager launched")

def stop():
    with _lock:
        _state["running"] = False

def get_log():
    with _lock:
        return list(_state["adaptations"])
