from werkzeug.middleware.proxy_fix import ProxyFix
import os, sys, logging
sys.path.insert(0,'/root/chanakya_v5')
from flask import Flask, jsonify, request, render_template, session
from flask_socketio import SocketIO, emit as sio_emit
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler("data/app.log")])
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="frontend/templates")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)
app.config["APPLICATION_ROOT"] = "/v5"
app.secret_key = os.getenv("SECRET_KEY","chanakya_v5_secret")
app.wsgi_app = ProxyFix(app.wsgi_app)

# ── Auth decorator ─────────────────────────────────────
def require_auth(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args,**kwargs):
        token = (request.headers.get("X-Auth-Token") or
                 request.args.get("t") or
                 request.cookies.get("token",""))
        if not token:
            return jsonify({"success":False,"error":"Unauthorized"}),401
        from auth.user_manager import verify_session, get_user
        username = verify_session(token)
        if not username:
            return jsonify({"success":False,"error":"Session expired"}),401
        request.username = username
        request.user = get_user(username) or {}
        return f(*args,**kwargs)
    return wrapper

def require_role(*roles):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def wrapper(*args,**kwargs):
            token = request.headers.get("X-Auth-Token","")
            from auth.user_manager import verify_session, get_user
            username = verify_session(token)
            if not username: return jsonify({"success":False,"error":"Unauthorized"}),401
            user = get_user(username) or {}
            if user.get("role") not in roles:
                return jsonify({"success":False,"error":"Access denied"}),403
            request.username = username
            request.user = user
            return f(*args,**kwargs)
        return wrapper
    return decorator

# ── Health ─────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status":"ok","version":"5.0","service":"Chanakya AI"})

@app.route("/api/calculator_data")
def calculator_data():
    """Live indicator data for Signal Calculator - no auth needed"""
    try:
        sym = request.args.get("symbol","NIFTY")
        exch= request.args.get("exchange","NSE")
        from data_stream.cache import get as cget
        from engine.indicators import ema, rsi as rsi_fn, macd, vwap, atr
        candles = cget(f"candles_{sym}_5m")
        if not candles or len(candles)<20:
            from broker.global_broker import get_broker
            tokens={"NIFTY":"99926000","BANKNIFTY":"99926009","FINNIFTY":"99926037",
                    "NATURALGAS":"488505","GOLDM":"67694","CRUDEOIL":"488290"}
            tok = tokens.get(sym,"99926000")
            try:
                b = get_broker()
                candles = b.get_candles(tok, exch, "FIVE_MINUTE", days=2)
            except: candles = None
        # Fallback: historical DB
        if not candles or len(candles)<20:
            import sqlite3 as _sq
            _db = "data/chanakya_v5.db"
            _rows = _sq.connect(_db).execute(
                "SELECT ts,open,high,low,close,volume FROM historical_candles "
                "WHERE symbol=? AND timeframe='5m' ORDER BY ts DESC LIMIT 300",(sym,)
            ).fetchall()
            if _rows: candles=[[r[0],r[1],r[2],r[3],r[4],r[5]] for r in reversed(_rows)]
        if not candles or len(candles)<10: return jsonify({"error":"no data","symbol":sym}),200
        closes=[float(c[4]) for c in candles]
        vols  =[float(c[5]) for c in candles]
        ltp   = closes[-1]
        e9    = ema(closes,9); e21=ema(closes,21)
        e200  = ema(closes[-200:] if len(closes)>=200 else closes,min(200,len(closes)))
        r     = rsi_fn(closes)
        m,mh  = macd(closes)
        vw    = vwap(candles[-75:] if len(candles)>=75 else candles)
        at    = atr(candles)
        vol_avg=sum(vols)/max(len(vols),1)
        vol_r  =round(vols[-1]/vol_avg,2) if vol_avg>0 else 1
        from engine.indicators import supertrend
        st = supertrend(candles)
        direction = "BUY" if e9>e21 else "SELL"
        return jsonify({"success":True,"symbol":sym,"ltp":ltp,
            "ema9":e9,"ema21":e21,"ema200":e200,
            "rsi":r,"macd_hist":round(mh,4),"vwap":vw,
            "atr":round(at,2),"vol_ratio":vol_r,
            "supertrend":st,"direction":direction})
    except Exception as e:
        return jsonify({"error":str(e),"success":False}),200

@app.route("/dataflow")
def dataflow():
    return render_template("dataflow.html")

@app.route("/v5/pivot")
def pivot_chart():
    return render_template("pivot_chart.html")

@app.route("/api/ws/status")
def ws_status():
    try:
        from broker.websocket_mgr import status as ws_st, get_all_ltp
        return jsonify({"success":True,"ws":ws_st(),"ltp":get_all_ltp()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Auth routes ────────────────────────────────────────
@app.route("/v5/login")
@app.route("/v5/logintest")
@app.route("/login")
@app.route("/")
def login_page():
    from flask import redirect
    return redirect("/v5")

@app.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.json or {}
        username = data.get("username","").strip().lower()
        password = data.get("password","").strip()
        from auth.user_manager import verify_password, create_session, get_user
        if not verify_password(username, password):
            return jsonify({"success":False,"error":"Invalid credentials"})
        token = create_session(username)
        user  = get_user(username) or {}
        # Auto trade ON on login
        try:
            from trading.user_auto_trader import set_user_auto_trade
            set_user_auto_trade(username, user.get("role","demo"))
            logger.info("Auto trade ON: %s (%s)", username, user.get("role","demo"))
        except Exception as _e:
            logger.error("Auto trade trigger failed: %s", _e)
        return jsonify({"success":True,"token":token,"role":user.get("role"),"username":username})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/logout", methods=["POST"])
def logout():
    try:
        token = request.headers.get("X-Auth-Token","")
        from auth.user_manager import delete_session
        delete_session(token)
        return jsonify({"success":True})
    except: return jsonify({"success":True})

@app.route("/api/status")
@require_auth
def status():
    try:
        from broker.global_broker import is_connected
        from config.subscriptions import days_remaining, get_tier_info
        user = request.user
        days = days_remaining(user.get("created_at",""), user.get("role","demo"))
        tier = get_tier_info(user.get("role","demo"))
        return jsonify({"success":True,
            "username":request.username,
            "role":user.get("role"),
            "days_remaining":days,
            "tier":tier,
            "broker_connected":is_connected(),
        })
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Market routes ──────────────────────────────────────
@app.route("/api/market")
@require_auth
def market():
    try:
        from broker.websocket_mgr import get_all_ltp_named, is_connected
        from data_stream.data_manager import get_data_manager
        if is_connected():
            data = get_all_ltp_named()
            source = "websocket"
        else:
            dm = get_data_manager()
            data = dm.get_market_snapshot()
            source = "rest"
        return jsonify({"success":True,"data":data,"source":source})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"data":{}})

@app.route("/api/signals")
@require_auth
def signals():
    try:
        from data_stream.cache import get as cget, set as cset
        sigs = cget("signals")
        if not sigs:
            from engine.scanner import scan_all
            sigs = scan_all()
            if sigs: cset("signals", sigs, ttl=60)
        return jsonify({"success":True,"signals":sigs or [],"total":len(sigs or [])})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"signals":[]})

# ── AI Chat ────────────────────────────────────────────
@app.route("/api/ai/chat", methods=["POST"])
@require_auth
def ai_chat():
    try:
        data = request.json or {}
        msg = data.get("message","")
        if not msg: return jsonify({"success":False,"error":"No message"})
        from engine.scanner import get_live_ltps
        from ai.chanakya_brain import chanakya_chat
        from broker.global_broker import get_broker
        reply = chanakya_chat(msg, get_broker(), username=request.username, role=request.user.get("role","demo"))
        return jsonify({"success":True,"reply":reply})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Trade routes ───────────────────────────────────────
@app.route("/api/trades")
@require_auth
def get_trades():
    try:
        from trading.paper_engine import get_open_trades, get_all_trades
        from broker.global_broker import get_broker
        mode = request.args.get("mode","open")
        role = request.user.get("role","demo")
        view_user = request.args.get("user", request.username)
        # Admin can see all or specific user trades
        if role in ["developer","administrator"]:
            target = view_user
        else:
            target = request.username
        if mode == "open":
            trades = get_open_trades(target)
        else:
            trades = get_all_trades(target)
        # Add live LTP to each trade (REST fallback if WS down)
        try:
            broker = get_broker()
            for t in trades:
                try:
                    ltp = broker.get_ltp(t.get("exchange","NSE"),
                                         t.get("symbol",""), t.get("token",""))
                    if not ltp or ltp<=0:
                        # Cache fallback
                        from data_stream.cache import get as _cg
                        _c = _cg(f"candles_{t.get('symbol','')}_5m")
                        if _c: ltp = float(_c[-1][4])
                    if ltp and ltp>0:
                        t["ltp"] = round(float(ltp),2)
                        qty = t.get("qty",1) or 1
                        entry = float(t.get("entry_price",0) or 0)
                        if t.get("direction") == "BUY":
                            t["live_pnl"] = round((float(ltp)-entry)*qty, 2)
                        else:
                            t["live_pnl"] = round((entry-float(ltp))*qty, 2)
                except: pass
        except: pass
        return jsonify({"success":True,"trades":trades,"total":len(trades)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"trades":[]})

@app.route("/api/trades", methods=["POST"])
@require_auth
def place_trade():
    try:
        data = request.json or {}
        symbol   = data.get("symbol","")
        exchange = data.get("exchange","NSE")
        direction= data.get("direction","BUY")
        entry    = float(data.get("entry",0))
        sl       = float(data.get("sl",0))
        target   = float(data.get("target",0))
        qty      = int(data.get("qty",1))
        token    = data.get("token","")
        mode     = data.get("mode","PAPER")
        if not symbol or entry<=0:
            return jsonify({"success":False,"error":"Invalid params"})
        from config.subscriptions import check_feature_access
        user_role = request.user.get("role","demo")
        if mode=="LIVE" and not check_feature_access(user_role,"live_trading"):
            return jsonify({"success":False,"error":"Live trading requires Gold+ subscription"})
        if mode=="LIVE":
            from trading.live_engine import place_intraday
            order_id = place_intraday(request.username,symbol,exchange,token,direction,qty)
            return jsonify({"success":bool(order_id),"order_id":order_id,"mode":"LIVE"})
        else:
            from trading.paper_engine import place_trade as pt
            tid = pt(request.username,symbol,exchange,direction,entry,sl,target,qty=qty,token=token)
            if tid:
                try:
                    from notifications.telegram import alert_trade_open
                    alert_trade_open(request.username,symbol,direction,entry,sl,target,qty,'PAPER')
                except: pass
            return jsonify({"success":bool(tid),"trade_id":tid,"mode":"PAPER"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/trades/<int:tid>/close", methods=["POST"])
@require_auth
def close_trade(tid):
    try:
        data = request.json or {}
        exit_price = float(data.get("exit_price",0))
        from trading.paper_engine import close_trade as ct, get_trade_by_id
        trade = get_trade_by_id(tid) or {}
        ok = ct(tid, exit_price, "manual")
        if ok:
            try:
                from notifications.telegram import alert_trade_close
                entry = trade.get("entry_price", 0)
                direction = trade.get("direction", "BUY")
                symbol = trade.get("symbol", "")
                qty = trade.get("qty", 1)
                pnl = (exit_price - entry) * qty if direction == "BUY" else (entry - exit_price) * qty
                alert_trade_close(request.username, symbol, direction, entry, exit_price, pnl, "PAPER")
            except: pass
        return jsonify({"success":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Admin routes ───────────────────────────────────────
@app.route("/api/admin/users")
@require_role("developer","administrator")
def admin_users():
    try:
        from auth.user_manager import get_all_users
        users = get_all_users()
        # Remove sensitive fields
        for u in users:
            u.pop("password_hash",None)
            u.pop("broker_totp",None)
        return jsonify({"success":True,"users":users,"total":len(users)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/users/<username>/role", methods=["POST"])
@require_role("developer","administrator")
def update_user_role(username):
    try:
        data = request.json or {}
        role = data.get("role","demo")
        from auth.user_manager import update_role
        ok = update_role(username, role)
        return jsonify({"success":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/users", methods=["POST"])
@require_role("developer","administrator")
def create_user_admin():
    try:
        data = request.json or {}
        from auth.user_manager import create_user
        ok = create_user(data.get("username",""), data.get("email",""),
                         data.get("password",""), data.get("role","demo"))
        return jsonify({"success":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── PnL ────────────────────────────────────────────────

@app.route("/api/predictions")
@require_auth
def predictions():
    try:
        from data_stream.cache import get as cget, set as cset
        from broker.global_broker import get_broker
        force = request.args.get("force","0")=="1"
        sigs = cget("predictions")
        if force or not sigs:
            import threading
            from ai.predictor import run_scan
            def _bg():
                r = run_scan(get_broker())
                if r: cset("predictions", r, ttl=300)
            threading.Thread(target=_bg, daemon=True).start()
            if not sigs:
                return jsonify({"success":True,"signals":[],"total":0,
                                "message":"Scan started — retry in 60s"})
        return jsonify({"success":True,"signals":sigs or [],"total":len(sigs or [])})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"signals":[]})

@app.route("/api/predictions/scan", methods=["POST"])
@require_auth
def predictions_scan():
    try:
        import threading
        from ai.predictor import run_scan
        from broker.global_broker import get_broker
        from data_stream.cache import set as cset
        def _scan():
            sigs = run_scan(get_broker())
            if sigs: cset("predictions", sigs, ttl=300)
        threading.Thread(target=_scan, daemon=True).start()
        return jsonify({"success":True,"message":"Scan started"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/api/options/chain")
@require_auth
def options_chain():
    """NSE + MCX Options Chain with OI, LTP, Greeks"""
    try:
        symbol  = request.args.get("symbol","NIFTY").upper()
        expiry  = request.args.get("expiry","nearest")
        import json as jj
        with open("data/scrip_master.json") as f: scrips=jj.load(f)

        # Determine exchange
        mcx_syms = ["CRUDEOIL","NATURALGAS","GOLD","SILVER","COPPER"]
        is_mcx   = symbol in mcx_syms
        exch_seg = "MCX" if is_mcx else "NFO"

        # Get spot LTP
        from broker.websocket_mgr import get_ltp_by_symbol
        spot = get_ltp_by_symbol(symbol) or 0

        # Filter options for this symbol
        opts = [s for s in scrips
                if s.get("name","").upper()==symbol
                and s.get("exch_seg","").upper()==exch_seg
                and s.get("instrumenttype","") in ("OPTFUT","OPTIDX","CE","PE","OPTSTK")
                or (s.get("symbol","").startswith(symbol) and
                    s.get("exch_seg","").upper()==exch_seg and
                    ("CE" in s.get("symbol","") or "PE" in s.get("symbol","")))]

        # Get all expiries
        expiries = sorted(set(s.get("expiry","") for s in opts if s.get("expiry")))
        if not expiries:
            return jsonify({"success":False,"error":f"No options found for {symbol}"})

        # Pick expiry
        if expiry=="nearest":
            sel_expiry = expiries[0]
        else:
            sel_expiry = expiry if expiry in expiries else expiries[0]

        # Filter by expiry
        chain_opts = [s for s in opts if s.get("expiry","")==sel_expiry]

        # Build strike map
        from broker.global_broker import get_broker
        broker = get_broker()
        strikes = {}
        for s in chain_opts:
            sym = s.get("symbol","")
            strike = s.get("strike","")
            try: strike = float(strike)/100 if float(strike)>10000 else float(strike)
            except: continue
            tok = str(s.get("token",""))
            is_ce = sym.endswith("CE")
            is_pe = sym.endswith("PE")
            if strike not in strikes:
                strikes[strike] = {"strike":strike,"ce_ltp":0,"pe_ltp":0,
                                   "ce_oi":0,"pe_oi":0,"ce_sym":"","pe_sym":"","ce_tok":"","pe_tok":""}
            try:
                ltp = broker.get_ltp(exch_seg, sym, tok) or 0
            except: ltp=0
            if is_ce:
                strikes[strike]["ce_ltp"] = ltp
                strikes[strike]["ce_sym"] = sym
                strikes[strike]["ce_tok"] = tok
            elif is_pe:
                strikes[strike]["pe_ltp"] = ltp
                strikes[strike]["pe_sym"] = sym
                strikes[strike]["pe_tok"] = tok

        # Sort strikes, find ATM
        chain = sorted(strikes.values(), key=lambda x:x["strike"])
        atm = min(chain, key=lambda x: abs(x["strike"]-spot))["strike"] if chain and spot else 0

        # PCR
        total_ce_oi = sum(c["ce_oi"] for c in chain)
        total_pe_oi = sum(c["pe_oi"] for c in chain)
        pcr = round(total_pe_oi/total_ce_oi,2) if total_ce_oi else 0

        return jsonify({
            "success":True,"symbol":symbol,"expiry":sel_expiry,
            "all_expiries":expiries,"spot":spot,"atm":atm,"pcr":pcr,
            "max_pain":atm,"is_mcx":is_mcx,"chain":chain,
            "total":len(chain)
        })
    except Exception as e:
        import traceback
        return jsonify({"success":False,"error":str(e),"trace":traceback.format_exc()[-200:]})
