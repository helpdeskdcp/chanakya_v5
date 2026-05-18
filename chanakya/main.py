from werkzeug.middleware.proxy_fix import ProxyFix
import os, sys, logging
from core.recovery_engine import recover_open_trades, detect_stale_trades
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flask import Flask, jsonify, request, render_template, session
from flask_socketio import SocketIO, emit as sio_emit
from dotenv import load_dotenv
try:
    from config.subscription_enforce import require_feature, has_feature, get_daily_limit
except: require_feature=lambda x: (lambda f: f); has_feature=lambda x: True; get_daily_limit=lambda x: 999
load_dotenv()

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler("data/app.log")])
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="frontend/templates")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)
# APPLICATION_ROOT removed for Emergent deployment — Kubernetes ingress routes /api/* to this backend.
app.secret_key = os.getenv("SECRET_KEY","chanakya_v5_secret")
app.wsgi_app = ProxyFix(app.wsgi_app)

# ── Emergent-environment UI route: serve full Chanakya UI under /api/ui ───
@app.route("/api/ui")
@app.route("/api/ui/")
def emergent_ui():
    try:
        return render_template("index.html")
    except Exception as e:
        return f"<h1>Chanakya AI v5.0</h1><p>Template error: {e}</p>", 500

@app.route("/api/static/<path:filename>")
def emergent_static(filename):
    import os as _os
    from flask import send_from_directory
    static_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "frontend", "static")
    return send_from_directory(static_dir, filename)

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
@app.route("/api/health")
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
    return redirect("/v5/")

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
            # Include OI for index tokens
            try:
                from broker.websocket_mgr import get_all_oi
                oi_data = get_all_oi()
                if oi_data:
                    return jsonify({"success":True,"data":data,"oi":oi_data,"source":source})
            except: pass
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


@app.route("/api/settings/broker", methods=["GET","POST"])
@require_auth
def broker_settings():
    try:
        from auth.user_manager import update_broker, get_user
        if request.method == "GET":
            user = get_user(request.username) or {}
            return jsonify({"success":True,"broker":{
                "api_key":    user.get("broker_api_key",""),
                "client_id":  user.get("broker_client_id",""),
                "password":   "●●●●" if user.get("broker_password") else "",
                "totp":       "●●●●" if user.get("broker_totp") else "",
            }})
        data = request.json or {}
        ok = update_broker(request.username,
            data.get("api_key",""),
            data.get("client_id",""),
            data.get("password",""),
            data.get("totp",""))
        return jsonify({"success":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


# ── Symbol Manager Routes ──────────────────────────────
@app.route("/api/admin/settings")
@require_role("developer","administrator")
def admin_get_settings():
    try:
        from database.symbol_manager import get_all_settings
        return jsonify({"success":True,"settings":get_all_settings()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/settings", methods=["POST"])
@require_role("developer","administrator")
def admin_update_settings():
    try:
        data = request.json or {}
        from database.symbol_manager import update_setting
        updated = 0
        for key, value in data.items():
            if update_setting(key, str(value), request.username):
                updated += 1
        return jsonify({"success":True,"updated":updated})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/api/news/sentiment")
@require_auth
def news_sentiment():
    try:
        from data_stream.cache import get as cget, set as cset
        symbol = request.args.get("symbol", None)
        force  = request.args.get("force", "0")=="1"
        ckey = "news_sentiment_"+(symbol or "market")
        data = None if force else cget(ckey)
        if not data:
            from ai.news_sentiment import get_market_sentiment
            syms = [symbol] if symbol else ["NIFTY","BANKNIFTY","CRUDEOIL"]
            data = get_market_sentiment(syms)
            if data: cset(ckey, data, ttl=300)
        return jsonify({"success":True, "data":data})
    except Exception as e:
        return jsonify({"success":False, "error":str(e)})

@app.route("/api/news/headlines")
@require_auth
def news_headlines():
    try:
        from data_stream.cache import get as cget, set as cset
        data = cget("news_headlines")
        if not data:
            from ai.news_sentiment import get_live_news
            news = get_live_news()
            data = news[:15]
            if data: cset("news_headlines", data, ttl=300)
        return jsonify({"success":True, "news":data or [], "total":len(data or [])})
    except Exception as e:
        return jsonify({"success":False, "error":str(e)})

@app.route("/api/pnl")
@require_auth
def pnl():
    try:
        from trading.paper_engine import get_pnl_summary
        return jsonify({"success":True,"pnl":get_pnl_summary(request.username)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Frontend ───────────────────────────────────────────

@app.route("/v5/static/<path:filename>")
def static_files(filename):
    import os
    from flask import send_from_directory
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "static")
    return send_from_directory(static_dir, filename)

@app.route("/v5/manifest.json")
def manifest():
    import os
    from flask import send_from_directory
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "static")
    return send_from_directory(static_dir, "manifest.json")

@app.route("/v5/sw.js")
def service_worker():
    import os
    from flask import Response
    sw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "static", "sw.js")
    content = open(sw_path).read()
    return Response(content, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/"})

@app.route("/")
@app.route("/v5")
@app.route("/v5/")
def index():
    try:
        return render_template("index.html")
    except:
        return "<h1>Chanakya AI v5.0</h1><p>Frontend loading...</p>"


PORT = int(os.getenv("PORT",5002))

@app.route("/api/chart")
@require_auth
def get_chart():
    try:
        symbol   = request.args.get("symbol","NIFTY")
        token    = request.args.get("token","99926000")
        exchange = request.args.get("exchange","NSE")
        interval = request.args.get("interval","FIVE_MINUTE")
        days     = int(request.args.get("days","2"))
        from broker.global_broker import get_broker
        from engine.indicators import ema, rsi, vwap, atr
        broker = get_broker()
        if not broker or not broker.is_connected():
            broker.connect()  # try reconnect
        candles = broker.get_candles(token, exchange, interval, days)
        if not candles:
            return jsonify({"success":False,"error":"No candle data"})
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        times  = [c[0] for c in candles]
        # Indicators
        ema9_vals  = [ema(closes[:i+1],9)  for i in range(len(closes))]
        ema21_vals = [ema(closes[:i+1],21) for i in range(len(closes))]
        vwap_val   = vwap(candles)
        atr_val    = atr(candles)
        rsi_val    = rsi(closes)
        return jsonify({
            "success": True,
            "symbol": symbol,
            "candles": [{"t":c[0],"o":float(c[1]),"h":float(c[2]),"l":float(c[3]),"c":float(c[4]),"v":float(c[5])} for c in candles[-100:]],
            "indicators": {
                "ema9":  ema9_vals[-100:],
                "ema21": ema21_vals[-100:],
                "vwap":  vwap_val,
                "atr":   atr_val,
                "rsi":   rsi_val,
            },
            "ltp": closes[-1],
        })
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/ml/train", methods=["POST"])
@require_auth
def ml_train():
    try:
        from broker.global_broker import get_broker
        from ai.ml_engine import train_model
        import threading
        def _train():
            train_model(get_broker())
        threading.Thread(target=_train, daemon=True).start()
        return jsonify({"success":True,"message":"Training started"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/ml/status")
@require_auth
def ml_status():
    try:
        from ai.ml_engine import get_status
        return jsonify({"success":True,"status":get_status()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


# ── Auto Trader routes ─────────────────────────────────
@app.route("/api/autotrader/status")
@require_auth
def autotrader_status():
    try:
        from trading.auto_trader import get_status
        return jsonify({"success":True,"status":get_status()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/autotrader/start", methods=["POST"])
@require_auth
def autotrader_start():
    try:
        data = request.json or {}
        mode = data.get("mode","PAPER")
        auto = data.get("auto_trade", False)
        from trading.auto_trader import start
        result = start(mode=mode, auto_trade=auto)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/autotrader/stop", methods=["POST"])
@require_auth
def autotrader_stop():
    try:
        from trading.auto_trader import stop
        return jsonify(stop())
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/autotrader/toggle", methods=["POST"])
@require_auth
def autotrader_toggle():
    try:
        data = request.json or {}
        from trading.auto_trader import get_status
        current = get_status().get("auto_trade", False)
        enabled = not current  # Toggle
        mode = data.get("mode", None)
        from trading.auto_trader import set_auto_trade
        return jsonify(set_auto_trade(enabled, mode))
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/api/capital/topup", methods=["POST"])
@require_role("administrator","developer")
def capital_topup():
    try:
        data     = request.json or {}
        username = data.get("username","")
        amount   = float(data.get("amount", 0))
        note     = data.get("note", "Admin adjustment")
        if not username or amount == 0:
            return jsonify({"success":False,"error":"username and amount required"})
        from trading.capital_manager import admin_topup
        result = admin_topup(username, amount, done_by=request.username, note=note)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/capital/ledger")
@require_auth
def capital_ledger():
    try:
        import sqlite3
        conn = sqlite3.connect("data/chanakya_v5.db")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM capital_ledger WHERE username=? ORDER BY id DESC LIMIT 20",
            (request.username,)).fetchall()
        conn.close()
        return jsonify({"success":True,"ledger":[dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/capital")
@require_auth
def capital_info():
    try:
        from trading.capital_manager import get_full_analysis, get_capital
        mode = request.args.get("mode", "PAPER")
        analysis = get_full_analysis()
        analysis["capital"] = get_capital(mode)
        return jsonify({"success":True, **analysis})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/adaptive/log")
@require_auth
def adaptive_log():
    try:
        from trading.adaptive_manager import get_log
        return jsonify({"success":True,"log":get_log()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"log":[]})

# ── Auto start position monitor on boot ───────────────
try:
    from trading.auto_trader import start as at_start
    at_start(mode="PAPER", auto_trade=True)
    # Adaptive Manager - हर 5 seconds monitoring
    from trading.adaptive_manager import start as am_start
    am_start()
    # Multi-user: DB table init + 11:40 scheduler
    try:
        import sqlite3 as _sq
        _c = _sq.connect("data/chanakya_v5.db")
        _c.execute("""CREATE TABLE IF NOT EXISTS user_trading_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            auto_trade INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'PAPER',
            login_at TEXT, auto_off_at TEXT,
            trades_today INTEGER DEFAULT 0,
            pnl_today REAL DEFAULT 0.0,
            updated_at TEXT
        )""")
        _c.commit(); _c.close()
        import threading
        from trading.user_auto_trader import run_1140_scheduler
        threading.Thread(target=run_1140_scheduler, daemon=True, name="1140Scheduler").start()
        logger.info("Multi-user auto trader initialized")
    except Exception as _e:
        logger.error("Multi-user init: %s", _e)
    logger.info("Auto Trader monitor started")
except Exception as e:
    logger.warning(f"Auto trader start failed: {e}")



# ── PDF Report Routes ──────────────────────────────────
@app.route("/api/report/pdf")
@require_auth
def download_pdf_report():
    try:
        from flask import send_file
        from trading.pdf_report import generate_pdf
        from datetime import date
        import io as _io

        rtype    = request.args.get("type", "daily")
        date_val = request.args.get("date", str(date.today()))
        dfrom    = request.args.get("from")
        dto      = request.args.get("to")
        month    = request.args.get("month")
        tid      = request.args.get("trade_id")

        if rtype == "daily" and not dfrom:
            dfrom = dto = date_val

        pdf_bytes = generate_pdf(
            report_type = rtype,
            username    = request.username,
            date_from   = dfrom,
            date_to     = dto,
            trade_id    = int(tid) if tid else None,
            month       = month,
            all_users   = False,
        )
        filename = f"chanakya_{rtype}_{date.today()}.pdf"
        return send_file(
            _io.BytesIO(pdf_bytes),
            mimetype      = "application/pdf",
            as_attachment = True,
            download_name = filename,
        )
    except Exception as e:
        logger.error(f"PDF report error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/admin/report/pdf")
@require_role("developer", "administrator")
def admin_download_pdf_report():
    try:
        from flask import send_file
        from trading.pdf_report import generate_pdf
        from datetime import date
        import io as _io

        rtype  = request.args.get("type", "monthly")
        dfrom  = request.args.get("from")
        dto    = request.args.get("to")
        month  = request.args.get("month")
        tid    = request.args.get("trade_id")
        user   = request.args.get("username")

        if rtype == "daily" and not dfrom:
            dfrom = dto = str(date.today())

        pdf_bytes = generate_pdf(
            report_type = rtype,
            username    = user,
            date_from   = dfrom,
            date_to     = dto,
            trade_id    = int(tid) if tid else None,
            month       = month,
            all_users   = not bool(user),
        )
        filename = f"chanakya_admin_{rtype}_{date.today()}.pdf"
        return send_file(
            _io.BytesIO(pdf_bytes),
            mimetype      = "application/pdf",
            as_attachment = True,
            download_name = filename,
        )
    except Exception as e:
        logger.error(f"Admin PDF report error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/auth/google", methods=["POST"])
def google_auth():
    try:
        data = request.json or {}
        email = data.get("email","").lower().strip()
        name  = data.get("name","")
        id_token = data.get("id_token","")
        device_fp = data.get("device_fp","")
        if not email:
            return jsonify({"success":False,"error":"No email"})
        # Verify Firebase token (basic check)
        import requests as req
        r = req.get(f"https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={id_token}", timeout=5)
        if r.status_code != 200:
            return jsonify({"success":False,"error":"Invalid token"})
        token_info = r.json()
        if token_info.get("email","").lower() != email:
            return jsonify({"success":False,"error":"Email mismatch"})
        # Get or create user
        from auth.user_manager import get_user, create_user, create_session
        import re
        username = re.sub(r'[^a-z0-9]','', email.split('@')[0])[:20]
        user = get_user(username)
        if not user:
            # New user → demo role
            create_user(username, email, "gmail_"+username[:8], "demo")
            user = get_user(username) or {}
        # Create session
        token = create_session(username)
        role  = user.get("role","demo")
        return jsonify({"success":True,"token":token,"role":role,"username":username,"email":email})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})
def _prediction_scheduler():
    """हर 10 min predictions background मध्ये refresh"""
    import time, logging
    log = logging.getLogger("scheduler")
    time.sleep(60)  # startup नंतर 1 min wait
    while True:
        try:
            from broker.global_broker import get_broker
            from ai.predictor import run_scan
            from data_stream.cache import set as cset
            broker = get_broker()
            if broker and broker.is_connected():
                sigs = run_scan(broker)
                if sigs:
                    cset("predictions", sigs, ttl=600)
                    log.info("Auto predictions: %d signals", len(sigs))
        except Exception as e:
            log.error("Prediction scheduler: %s", e)
        time.sleep(600)  # 10 min

def _startup_train():
    """Auto-train ML model in background at startup"""
    import time, logging
    log = logging.getLogger("startup")
    time.sleep(15)  # Wait for broker to connect
    try:
        from broker.global_broker import get_broker
        from ai.ml_engine import train_model
        broker = get_broker()
        if broker and broker.is_connected():
            ok = train_model(broker)
            log.info("ML auto-train: %s", "✅ done" if ok else "❌ failed")
        else:
            log.warning("ML auto-train skipped: broker not connected")
    except Exception as e:
        log.error("ML auto-train error: %s", e)

@app.route("/api/option/ltp")
@require_auth
def get_option_ltp():
    try:
        symbol   = request.args.get("symbol","NIFTY")
        strike   = request.args.get("strike","24000")
        opt_type = request.args.get("type","CE")
        expiry   = request.args.get("expiry","")
        from broker.global_broker import get_broker
        broker = get_broker()
        if not broker or not broker.is_connected():
            return jsonify({"success":False,"error":"Broker not connected"})
        # Search scrip master for option token
        import json, os
        scrip_path = "data/scrip_master.json"
        if not os.path.exists(scrip_path):
            return jsonify({"success":False,"error":"Scrip master not found"})
        with open(scrip_path) as f:
            scrips = json.load(f)
        # Find matching option — format: NIFTY29MAY2424000CE
        strike_int = str(int(float(strike)))
        sym_up = symbol.upper()
        otype  = opt_type.upper()
        # Correct exchange per symbol
        EXCH_MAP = {
            "NIFTY":"NFO", "BANKNIFTY":"NFO", "FINNIFTY":"NFO",
            "MIDCPNIFTY":"NFO", "SENSEX":"BFO",
            "CRUDEOIL":"MCX", "NATURALGAS":"MCX",
            "GOLD":"MCX", "SILVER":"MCX", "COPPER":"MCX",
        }
        preferred_exch = EXCH_MAP.get(sym_up, "")
        matches = []
        for s in scrips:
            ssym = s.get("symbol","").upper()
            exch = s.get("exch_seg","").upper()
            # Filter by correct exchange
            if preferred_exch and exch != preferred_exch: continue
            if ssym.startswith(sym_up) and ssym.endswith(strike_int+otype):
                matches.append(s)
        if not matches:
            # Fallback without exchange filter
            for s in scrips:
                ssym = s.get("symbol","").upper()
                if sym_up in ssym and strike_int in ssym and otype in ssym:
                    matches.append(s)
        if not matches:
            return jsonify({"success":False,"error":"Option not found: "+symbol+" "+strike+" "+opt_type})
        # Sort by nearest expiry using expiry date field
        import datetime
        today = datetime.date.today()
        def expiry_key(s):
            exp = s.get("expiry","")
            try:
                return datetime.datetime.strptime(exp, "%d%b%Y").date()
            except:
                try:
                    return datetime.datetime.strptime(exp, "%Y-%m-%d").date()
                except:
                    return datetime.date(2099,1,1)
        # Filter only future expiries with valid parseable dates (not old format)
        future = [s for s in matches if expiry_key(s) >= today and expiry_key(s).year < 2090]
        if future: matches = future
        matches.sort(key=expiry_key)
        best = matches[0]
        token = str(best.get("token") or best.get("symboltoken",""))
        exch  = best.get("exch_seg","NFO")
        ltp = broker.get_ltp(exch, best.get("symbol",""), token)
        return jsonify({"success":True,"ltp":ltp,"token":token,
                       "name":best.get("symbol",""),"strike":strike,"type":opt_type})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/mythos/scan")
@require_auth
def mythos_scan():
    """Chanakya Mythos Engine — 3-layer AI signal"""
    try:
        from ai.feature_engine import compute_features
        from ai.decision_engine import get_engine
        from broker.global_broker import get_broker
        import time, datetime, pytz

        broker = get_broker()
        engine = get_engine()
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.datetime.now(IST)
        now_h = now.hour

        nse_open = (now_h==9 and now.minute>=15) or (10<=now_h<=15)
        mcx_open = 9<=now_h<=23

        SYMS = [
            {"name":"NIFTY",   "token":"99926000","exchange":"NSE","lot":65},
            {"name":"BANKNIFTY","token":"99926009","exchange":"NSE","lot":30},
            {"name":"CRUDEOIL","token":"488290",  "exchange":"MCX","lot":100},
            {"name":"NATURALGAS","token":"488505","exchange":"MCX","lot":1250},
        ]

        results = []
        for sym in SYMS:
            if sym["exchange"]=="NSE" and not nse_open: continue
            if sym["exchange"]=="MCX" and not mcx_open: continue
            try:
                time.sleep(0.5)
                # Reconnect + retry
                if not broker.is_connected(): broker.connect()
                raw = None
                for _att in range(3):
                    try:
                        raw = broker.get_candles(sym["token"],sym["exchange"],"FIVE_MINUTE",2)
                        if raw and len(raw)>=30: break
                    except: pass
                    broker.connect(); import time; time.sleep(2)
                if not raw or len(raw)<30: continue
                candles=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),
                          "c":float(x[4]),"v":float(x[5]) if len(x)>5 else 0} for x in raw]
                features = compute_features(candles, sym["name"])
                if not features: continue
                fusion = engine.fuse(features, candles)
                if fusion["signal"]=="NO_TRADE" or fusion["score"]<58: continue
                # Option selection
                opt_type = "CE" if fusion["signal"]=="BUY_CE" else "PE"
                interval = 100 if sym["name"]=="BANKNIFTY" else 50 if sym["name"] in ["NIFTY","CRUDEOIL"] else 10
                atm = round(features["price"]/interval)*interval
                opt_ltp=None; opt_sym=None; opt_tok=None
                try:
                    import json as jj, datetime as dt2
                    today = dt2.date.today()
                    with open("data/scrip_master.json") as f: scrips=jj.load(f)
                    EXCH={"NIFTY":"NFO","BANKNIFTY":"NFO","FINNIFTY":"NFO",
                          "CRUDEOIL":"MCX","NATURALGAS":"MCX"}
                    pexch=EXCH.get(sym["name"],"NFO")
                    strike_s=str(int(atm))
                    matches=[s for s in scrips
                             if s.get("exch_seg","").upper()==pexch
                             and s.get("symbol","").upper().startswith(sym["name"].upper())
                             and s.get("symbol","").upper().endswith(strike_s+opt_type)]
                    def ekey(s):
                        try: return dt2.datetime.strptime(s.get("expiry",""),"%d%b%Y").date()
                        except: return dt2.date(2099,1,1)
                    future=[s for s in matches if ekey(s)>=today and ekey(s).year<2090]
                    if future:
                        future.sort(key=ekey)
                        best=future[0]
                        opt_ltp=broker.get_ltp(pexch,best.get("symbol",""),str(best.get("token","")))
                        opt_sym=best.get("symbol"); opt_tok=str(best.get("token"))
                except: pass

                opt_entry = opt_ltp or 0
                opt_sl     = round(opt_entry*0.80,2) if opt_entry else 0
                opt_target = round(opt_entry*1.40,2) if opt_entry else 0
                opt_trail  = round(opt_entry*0.90,2) if opt_entry else 0
                opt_exchange_final = EXCH.get(sym["name"],"NFO")
                if not opt_tok or opt_tok=="None": opt_tok=None
                results.append({
                    "symbol":sym["name"],
                    "signal":fusion["signal"],
                    "score": fusion["score"],
                    "risk":  fusion.get("risk","MEDIUM"),
                    "price": features["price"],
                    "rsi":   features["rsi14"],
                    "ema_trend": "BULL" if features["ema_trend"]==1 else "BEAR",
                    "vwap_dist": features["vwap_dist_pct"],
                    "vol_ratio": features["vol_ratio"],
                    "structure": features["structure"],
                    "reasons":fusion.get("reasons",[]),
                    # 3-layer details
                    "layer1_rule":  {"signal":fusion["rule"]["signal"],"score":fusion["rule"]["score"]},
                    "layer2_ml":    {"signal":fusion["ml"]["signal"],"confidence":fusion["ml"]["confidence"],"available":fusion["ml"].get("ml_available",False)},
                    "layer3_llm":   {"approved":fusion["llm"]["approved"],"reason":fusion["llm"].get("reason",""),"risk":fusion["llm"].get("risk","MEDIUM")},
                    # Option
                    "opt_symbol":opt_sym,"opt_token":opt_tok,
                    "opt_ltp":opt_ltp,"opt_strike":atm,
                    "opt_type":opt_type,"opt_lot":sym["lot"],
                    "opt_entry":opt_entry,
                    "opt_sl":   round(opt_entry*0.80,2) if opt_entry else 0,
                    "opt_target":round(opt_entry*1.40,2) if opt_entry else 0,
                    "opt_trail": round(opt_entry*0.85,2) if opt_entry else 0,
                    "opt_exchange":opt_exchange_final,
                })
            except Exception as e:
                logger.warning("Mythos %s: %s", sym["name"], e)
        return jsonify({"success":True,"signals":results,"count":len(results),
                       "safety":{"consecutive_losses":engine.consecutive_losses,
                                  "daily_trades":engine.daily_trades}})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/mythos/retrain", methods=["POST"])
@require_role("developer","administrator")
def mythos_retrain():
    try:
        from ai.auto_trainer import retrain_from_trades
        result = retrain_from_trades()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})
@app.route("/api/scalping/scan")
@require_auth
def scalping_scan():
    """Scalping scan using Mythos 3-layer AI engine"""
    try:
        from ai.feature_engine import compute_features
        from ai.decision_engine import ChanakyaDecisionEngine
        from data_stream.data_manager import get_data_manager
        import json as jj, datetime as dt2

        dm = get_data_manager()
        broker = dm._get_broker()
        engine = ChanakyaDecisionEngine()
        today = dt2.date.today()

        results = []
        logger.info("Scalping scan: %d symbols, NSE=%s MCX=%s",
                    len(dm.SYMBOLS), dm.is_market_open('NSE'), dm.is_market_open('MCX'))
        for sym_name, info in dm.SYMBOLS.items():
            if info["type"] == "equity": continue
            if info["exchange"] == "NSE" and not dm.is_market_open("NSE"): continue
            if info["exchange"] == "MCX" and not dm.is_market_open("MCX"): continue

            candles = dm.get_candles(sym_name)
            if not candles or len(candles) < 30: continue

            features = compute_features(candles, sym_name)
            if not features: continue

            fusion = engine.fuse(features)
            if fusion["signal"] == "NO_TRADE" or fusion["score"] < 30: continue

            ltp = features["price"]
            atr_val = features["atr14"]
            sl_pts = max(atr_val * 2.5, ltp * info["min_sl"])
            tgt_pts = sl_pts * 2.0
            direction = fusion["signal"]
            opt_type = "CE" if direction == "BUY_CE" else "PE"
            atm = round(ltp / info["interval"]) * info["interval"]
            opt_exch = info["opt_exchange"]

            # Option fetch
            opt_ltp=None; opt_sym=None; opt_tok=None
            try:
                with open("data/scrip_master.json") as f: scrips=jj.load(f)
                strike_s = str(int(atm))
                matches = [s for s in scrips
                    if s.get("exch_seg","").upper()==opt_exch
                    and s.get("symbol","").upper().startswith(sym_name.upper())
                    and s.get("symbol","").upper().endswith(strike_s+opt_type)]
                def ekey(s):
                    try: return dt2.datetime.strptime(s.get("expiry",""),"%d%b%Y").date()
                    except: return dt2.date(2099,1,1)
                future = [s for s in matches if ekey(s)>=today and ekey(s).year<2090]
                if future:
                    future.sort(key=ekey)
                    best = future[0]
                    opt_sym = best.get("symbol")
                    opt_tok = str(best.get("token",""))
                    if broker:
                        opt_ltp = broker.get_ltp(opt_exch, opt_sym, opt_tok)
            except: pass

            opt_entry = opt_ltp or 0
            results.append({
                "symbol":   sym_name,
                "signal":   direction,
                "score":    fusion["score"],
                "strategy": "MYTHOS",
                "price":    ltp,
                "rsi":      features["rsi14"],
                "atr":      round(atr_val, 2),
                "trend":    "BULL" if features["ema_trend"]==1 else "BEAR",
                "rr":       "1:2",
                "qty":      info["lot"],
                "sl":       round(ltp-sl_pts,2) if direction=="BUY_CE" else round(ltp+sl_pts,2),
                "target":   round(ltp+tgt_pts,2) if direction=="BUY_CE" else round(ltp-tgt_pts,2),
                "sl_pts":   round(sl_pts,2),
                "reasons":  fusion.get("reasons",[]),
                # Option fields for buy button
                "opt_symbol":   opt_sym,
                "opt_token":    opt_tok,
                "opt_exchange": opt_exch,
                "opt_lot":      info["lot"],
                "opt_ltp":      opt_ltp,
                "opt_entry":    opt_entry,
                "opt_sl":       round(opt_entry*0.80,2) if opt_entry else 0,
                "opt_target":   round(opt_entry*1.40,2) if opt_entry else 0,
                "opt_trail":    round(opt_entry*0.90,2) if opt_entry else 0,
                "opt_strike":   atm,
                "opt_type":     opt_type,
                # 3-layer scores
                "layer1": fusion["rule"]["score"],
                "layer2": fusion["ml"]["confidence"],
                "layer3": fusion["llm"]["approved"],
            })

        return jsonify({"success":True,"signals":results,"count":len(results)})
    except Exception as e:
        import traceback
        logger.error("scalping_scan: %s", traceback.format_exc()[-300:])
        return jsonify({"success":False,"error":str(e),"signals":[],"count":0})


def scalping_stats():
    try:
        from scalping_engine.ai_engine import get_performance_stats, get_strategy_weights
        return jsonify({"success":True,
                       "stats":get_performance_stats(),
                       "weights":get_strategy_weights()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/scalping/backtest", methods=["POST"])
@require_auth
def scalping_backtest():
    try:
        from scalping_engine.backtest import run_backtest
        from broker.global_broker import get_broker
        broker = get_broker()
        SYMS = [
            {"name":"NIFTY","token":"99926000","exchange":"NSE"},
            {"name":"BANKNIFTY","token":"99926009","exchange":"NSE"},
        ]
        candles_by_sym = {}
        for sym in SYMS:
            raw = broker.get_candles(sym["token"],sym["exchange"],"FIVE_MINUTE",5)
            if raw:
                candles_by_sym[sym["name"]] = [
                    {"o":float(c[1]),"h":float(c[2]),"l":float(c[3]),
                     "c":float(c[4]),"v":float(c[5]) if len(c)>5 else 0} for c in raw]
        results = run_backtest(candles_by_sym)
        return jsonify({"success":True,"results":results})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})
@app.route("/api/scalping/buy", methods=["POST"])
@require_auth
def scalping_buy():
    try:
        data = request.json or {}
        # Subscription gate
        _role = getattr(request,'role','demo')
        _paper = data.get('paper', True)
        if _role == 'demo' and not _paper:
            return jsonify({"success":False,"error":"Demo: paper trade only. Upgrade to PREMIUM.","upgrade_url":"/v5/upgrade"})
        if _role == 'demo':
            import sqlite3 as _sq2
            from datetime import datetime as _dt2
            _c2 = _sq2.connect("data/chanakya_v5.db")
            _today2 = _dt2.now().strftime("%Y-%m-%d")
            _cnt2 = _c2.execute("SELECT COUNT(*) FROM trades WHERE username=? AND DATE(created_at)=?",
                                (request.username, _today2)).fetchone()[0]
            _c2.close()
            if _cnt2 >= 1:
                return jsonify({"success":False,"error":"Demo: 1 trade/day limit. Upgrade to PREMIUM.","upgrade_url":"/v5/upgrade"})
        sym        = data.get("opt_symbol")
        token      = data.get("opt_token")
        exchange   = data.get("opt_exchange","NFO")
        qty        = int(data.get("opt_lot",1))
        entry      = float(data.get("opt_entry",0))
        sl         = float(data.get("opt_sl",0))
        target     = float(data.get("opt_target",0))
        trail      = float(data.get("opt_trail",0))
        signal     = data.get("signal","BUY_CE")
        index_sym  = data.get("symbol","NIFTY")
        strategy   = data.get("strategy","BREAKOUT")
        paper      = data.get("paper", True)
        username   = request.username

        if not sym or not entry:
            return jsonify({"success":False,"error":"Missing params"})

        import sqlite3 as sq, datetime as dt
        conn = sq.connect("data/chanakya_v5.db")

        if paper:
            # Paper trade
            conn.execute("""INSERT INTO trades
                (username,symbol,direction,entry_price,sl_price,target_price,
                 quantity,mode,status,strategy,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (username, sym, "BUY", entry, sl, target, qty,
                 "PAPER","OPEN", strategy,
                 dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            trade_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit(); conn.close()
            return jsonify({"success":True,"trade_id":trade_id,"mode":"PAPER",
                           "message":f"Paper BUY {sym} @ ₹{entry}",
                           "sl":sl,"target":target,"trail":trail})
        else:
            # Live order via Angel One
            from broker.global_broker import get_broker
            broker = get_broker()
            if not broker.connected:
                return jsonify({"success":False,"error":"Broker not connected"})
            # Place limit order
            price_buf = round(entry * 1.002, 2)  # 0.2% buffer for limit
            order_resp = broker.obj.placeOrder({
                "variety":"NORMAL","tradingsymbol":sym,
                "symboltoken":token,"transactiontype":"BUY",
                "exchange":exchange,"ordertype":"LIMIT",
                "producttype":"INTRADAY","duration":"DAY",
                "price":str(price_buf),"quantity":str(qty)
            })
            order_id = order_resp.get("data",{}).get("orderid","")
            conn.execute("""INSERT INTO trades
                (username,symbol,direction,entry_price,sl_price,target_price,
                 quantity,mode,status,strategy,order_id,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (username,sym,"BUY",entry,sl,target,qty,
                 "LIVE","OPEN",strategy,order_id,
                 dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit(); conn.close()
            return jsonify({"success":True,"order_id":order_id,"mode":"LIVE",
                           "message":f"LIVE LIMIT BUY {sym} @ ₹{price_buf}",
                           "sl":sl,"target":target})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/scalping/monitor")
@require_auth
def scalping_monitor():
    """Monitor open scalping trades — check SL trail"""
    try:
        import sqlite3 as sq
        conn = sq.connect("data/chanakya_v5.db")
        trades = conn.execute("""SELECT id,symbol,direction,entry_price,sl_price,
            target_price,quantity,mode,strategy,created_at,trading_symbol,token
            FROM trades WHERE username=? AND status='OPEN'
            ORDER BY id DESC""",
            (request.username,)).fetchall()
        result = []
        from broker.global_broker import get_broker
        broker = get_broker()
        for t in trades:
            tid,sym,dire,entry,sl,target,qty,mode,strat,ts,trading_sym,tok = t
            qty=int(qty or 1); entry=float(entry or 0); sl=float(sl or 0); target=float(target or 0)
            # Get current LTP
            ltp = None
            try:
                # Try WebSocket first (instant)
                from broker.websocket_mgr import get_ltp_by_symbol
                ltp = get_ltp_by_symbol(sym)
                # Fallback to REST
                if not ltp:
                    import json as jj
                    with open("data/scrip_master.json") as f2: scrips=jj.load(f2)
                    # Match by full symbol name (for options like NATURALGAS22MAY26280CE)
                    # Use token from DB directly (fastest)
                    tok = str(tok or "")  # token column from trades
                    if tok and tok != "None":
                        # Determine exchange from token
                        nse_tokens = ["99926000","99926009","99926037","99926074"]
                        mcx_tokens = ["488290","488505","466583","67695"]
                        if tok in nse_tokens:
                            ltp = broker.get_ltp("NSE", sym, tok)
                        elif any(tok.startswith(x[:3]) for x in mcx_tokens) or int(tok or 0) > 400000:
                            ltp = broker.get_ltp("MCX", trading_sym or sym, tok)
                        else:
                            ltp = broker.get_ltp("NFO", trading_sym or sym, tok)
                    else:
                        # Fallback scrip master
                        lookup = (trading_sym or sym or "").upper()
                        found = [s for s in scrips if s.get("symbol","").upper()==lookup]
                        if not found:
                            found = [s for s in scrips if s.get("symbol","").upper()==sym.upper()]
                        if found:
                            s2 = found[0]
                            ltp = broker.get_ltp(s2.get("exch_seg","NFO"), s2.get("symbol",""), str(s2.get("token","")))
            except: pass

            pnl = 0; trail_sl = sl; status_msg = "HOLD"
            if ltp:
                pnl = round((ltp - (entry or 0)) * (qty or 1), 2)
                # Trailing SL logic (SEBI style)
                profit_pct = (ltp - (entry or 0)) / (entry or 1) * 100
                if profit_pct >= 15:
                    trail_sl = round(ltp * 0.90, 2)  # Trail to 90% of current
                elif profit_pct >= 10:
                    trail_sl = round(ltp * 0.88, 2)
                elif profit_pct >= 5:
                    trail_sl = round(entry * 1.02, 2)  # Move to cost+2%
                trail_sl = max(trail_sl, sl)
                # Status
                if ltp <= sl:       status_msg = "⚠️ SL_HIT"
                elif ltp >= target: status_msg = "🎯 TARGET_HIT"
                elif trail_sl > sl: status_msg = "📈 TRAILING"

            result.append({
                "id":tid,"symbol":sym,"direction":dire,
                "entry":entry,"sl":sl,"target":target,
                "qty":qty,"mode":mode,"strategy":strat,
                "ltp":ltp,"pnl":pnl,"trail_sl":trail_sl,
                "status":status_msg,"timestamp":ts
            })
        conn.close()
        return jsonify({"success":True,"trades":result,"count":len(result)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})
@app.route("/api/mythos/debug")
@require_auth
def mythos_debug():
    try:
        from ai.feature_engine import compute_features
        from ai.decision_engine import ChanakyaDecisionEngine
        from broker.global_broker import get_broker
        import time, datetime, pytz

        broker = get_broker()
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.datetime.now(IST)
        mcx_open = 9 <= now.hour <= 23
        debug = {"time": now.strftime("%H:%M"), "mcx_open": mcx_open,
                 "broker_connected": broker.is_connected()}

        # Test CRUDEOIL
        if not broker.is_connected(): broker.connect()
        time.sleep(0.5)
        raw = broker.get_candles("488290","MCX","FIVE_MINUTE",2)
        debug["crudeoil_candles"] = len(raw) if raw else 0

        if raw and len(raw) >= 30:
            candles=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),
                      "c":float(x[4]),"v":float(x[5]) if len(x)>5 else 0} for x in raw]
            features = compute_features(candles, "CRUDEOIL")
            debug["features_ok"] = features is not None
            if features:
                debug["rsi"] = features["rsi14"]
                debug["vwap_dist"] = features["vwap_dist_pct"]
                debug["structure"] = features["structure"]
                eng = ChanakyaDecisionEngine()
                fusion = eng.fuse(features)
                debug["signal"] = fusion["signal"]
                debug["score"] = fusion["score"]
                debug["rule"] = {"signal":fusion["rule"]["signal"],"score":fusion["rule"]["score"]}
                debug["threshold_pass"] = fusion["score"] >= 42 and fusion["signal"] != "NO_TRADE"
        return jsonify({"success":True,"debug":debug})
    except Exception as e:
        import traceback
        return jsonify({"success":False,"error":str(e),"trace":traceback.format_exc()[-500:]})
@app.route("/api/signals/nse-index")
@require_auth
def signals_nse_index():
    """NSE Index F&O — Mythos 3-layer AI Engine"""
    try:
        from ai.feature_engine import compute_features
        from ai.decision_engine import ChanakyaDecisionEngine
        from data_stream.data_manager import get_data_manager
        import json as jj, datetime as dt2, time
        dm = get_data_manager()
        if not dm.is_market_open("NSE"):
            return jsonify({"success":True,"signals":[],"market":"NSE_CLOSED",
                          "message":"NSE 9:15AM-3:30PM IST madhe open aahe"})
        broker = dm._get_broker()
        engine = ChanakyaDecisionEngine()
        NSE = [
            {"name":"NIFTY",    "token":"99926000","exchange":"NSE","lot":65,"interval":50,"min_sl":0.004},
            {"name":"BANKNIFTY","token":"99926009","exchange":"NSE","lot":30,"interval":100,"min_sl":0.004},
            {"name":"FINNIFTY", "token":"99926037","exchange":"NSE","lot":65,"interval":50,"min_sl":0.004},
        ]
        results = []
        today = dt2.date.today()
        for sym in NSE:
            time.sleep(0.5)
            candles = dm.get_candles(sym["name"])
            if not candles or len(candles)<30: continue
            features = compute_features(candles, sym["name"])
            if not features: continue
            fusion = engine.fuse(features)
            if fusion["signal"]=="NO_TRADE" or fusion["score"]<30: continue
            ltp = features["price"]
            atr_val = features["atr14"]
            sl_pts = max(atr_val*2.5, ltp*sym["min_sl"])
            tgt_pts = sl_pts * 2.0
            opt_type = "CE" if fusion["signal"]=="BUY_CE" else "PE"
            atm = round(ltp/sym["interval"])*sym["interval"]
            # Option LTP
            opt_ltp=None; opt_sym=None
            try:
                with open("data/scrip_master.json") as f: scrips=jj.load(f)
                strike_s=str(int(atm))
                matches=[s for s in scrips
                         if s.get("exch_seg","").upper()=="NFO"
                         and s.get("symbol","").upper().startswith(sym["name"].upper())
                         and s.get("symbol","").upper().endswith(strike_s+opt_type)]
                def ekey(s):
                    try: return dt2.datetime.strptime(s.get("expiry",""),"%d%b%Y").date()
                    except: return dt2.date(2099,1,1)
                future=[s for s in matches if ekey(s)>=today and ekey(s).year<2090]
                if future:
                    future.sort(key=ekey)
                    best=future[0]
                    opt_ltp=broker.get_ltp("NFO",best.get("symbol",""),str(best.get("token","")))
                    opt_sym=best.get("symbol")
            except: pass
            opt_entry=opt_ltp or 0
            results.append({
                "symbol": sym["name"], "market":"NSE_INDEX",
                "signal": fusion["signal"], "score": fusion["score"],
                "risk":   fusion.get("risk","MEDIUM"),
                "ltp":    ltp,
                "sl":     round(ltp-sl_pts,2) if fusion["signal"]=="BUY_CE" else round(ltp+sl_pts,2),
                "target": round(ltp+tgt_pts,2) if fusion["signal"]=="BUY_CE" else round(ltp-tgt_pts,2),
                "sl_pts": round(sl_pts,2), "rr":"1:2",
                "rsi": features["rsi14"], "atr": atr_val,
                "vwap_dist": features["vwap_dist_pct"],
                "atm_strike": atm, "lot": sym["lot"],
                "opt_symbol": opt_sym, "opt_ltp": opt_ltp,
                "opt_sl":     round(opt_entry*0.80,2) if opt_entry else 0,
                "opt_target": round(opt_entry*1.40,2) if opt_entry else 0,
                "layer1": fusion["rule"]["score"],
                "layer2": fusion["ml"]["confidence"],
                "layer3": fusion["llm"]["approved"],
                "reasons": fusion.get("reasons",[]),
            })
        return jsonify({"success":True,"signals":results,"count":len(results),"market":"NSE_INDEX"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/signals/mcx")
@require_auth
def signals_mcx():
    """MCX Commodity F&O — Mythos 3-layer AI Engine"""
    try:
        from ai.feature_engine import compute_features
        from ai.decision_engine import ChanakyaDecisionEngine
        from data_stream.data_manager import get_data_manager
        import json as jj, datetime as dt2, time
        dm = get_data_manager()
        if not dm.is_market_open("MCX"):
            return jsonify({"success":True,"signals":[],"market":"MCX_CLOSED",
                          "message":"MCX 9:00AM-11:30PM IST madhe open aahe"})
        broker = dm._get_broker()
        engine = ChanakyaDecisionEngine()
        MCX = [
            {"name":"CRUDEOIL",  "token":"488290","exchange":"MCX","lot":100,"interval":50,"min_sl":0.006},
            {"name":"NATURALGAS","token":"488505","exchange":"MCX","lot":1250,"interval":10,"min_sl":0.008},
            {"name":"GOLD",      "token":"67694", "exchange":"MCX","lot":100,"interval":100,"min_sl":0.005},
        ]
        results = []
        today = dt2.date.today()
        for sym in MCX:
            time.sleep(0.5)
            candles = dm.get_candles(sym["name"])
            if not candles or len(candles)<30: continue
            features = compute_features(candles, sym["name"])
            if not features: continue
            fusion = engine.fuse(features)
            if fusion["signal"]=="NO_TRADE" or fusion["score"]<55: continue
            ltp = features["price"]
            atr_val = features["atr14"]
            sl_pts = max(atr_val*2.5, ltp*sym["min_sl"])
            tgt_pts = sl_pts * 2.0
            opt_type = "CE" if fusion["signal"]=="BUY_CE" else "PE"
            atm = round(ltp/sym["interval"])*sym["interval"]
            opt_ltp=None; opt_sym=None
            try:
                with open("data/scrip_master.json") as f: scrips=jj.load(f)
                strike_s=str(int(atm))
                matches=[s for s in scrips
                         if s.get("exch_seg","").upper()=="MCX"
                         and s.get("symbol","").upper().startswith(sym["name"].upper())
                         and s.get("symbol","").upper().endswith(strike_s+opt_type)]
                def ekey(s):
                    try: return dt2.datetime.strptime(s.get("expiry",""),"%d%b%Y").date()
                    except: return dt2.date(2099,1,1)
                future=[s for s in matches if ekey(s)>=today and ekey(s).year<2090]
                if future:
                    future.sort(key=ekey)
                    best=future[0]
                    opt_ltp=broker.get_ltp("MCX",best.get("symbol",""),str(best.get("token","")))
                    opt_sym=best.get("symbol")
            except: pass
            opt_entry=opt_ltp or 0
            results.append({
                "symbol": sym["name"], "market":"MCX",
                "signal": fusion["signal"], "score": fusion["score"],
                "risk":   fusion.get("risk","MEDIUM"),
                "ltp":    ltp,
                "sl":     round(ltp-sl_pts,2) if fusion["signal"]=="BUY_CE" else round(ltp+sl_pts,2),
                "target": round(ltp+tgt_pts,2) if fusion["signal"]=="BUY_CE" else round(ltp-tgt_pts,2),
                "sl_pts": round(sl_pts,2), "rr":"1:2",
                "rsi": features["rsi14"], "atr": atr_val,
                "atm_strike": atm, "lot": sym["lot"],
                "opt_symbol": opt_sym, "opt_ltp": opt_ltp,
                "opt_sl":     round(opt_entry*0.80,2) if opt_entry else 0,
                "opt_target": round(opt_entry*1.40,2) if opt_entry else 0,
                "layer1": fusion["rule"]["score"],
                "layer2": fusion["ml"]["confidence"],
                "layer3": fusion["llm"]["approved"],
                "reasons": fusion.get("reasons",[]),
            })
        return jsonify({"success":True,"signals":results,"count":len(results),"market":"MCX"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/signals/equity")
@require_auth
def signals_equity():
    """NSE Equity signals — direct stock (no F&O)"""
    try:
        from engine.scanner import NSE_EQUITY, _analyze
        from broker.global_broker import get_broker
        import datetime, pytz
        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.datetime.now(IST)
        if not ((now.hour==9 and now.minute>=15) or (10<=now.hour<=15) or
                (now.hour==15 and now.minute<=30)):
            return jsonify({"success":True,"signals":[],"market":"NSE_CLOSED"})
        broker = get_broker()
        results = []
        for sym in NSE_EQUITY:
            raw = broker.get_candles(sym["token"],sym["exchange"],"FIVE_MINUTE",2)
            if not raw or len(raw)<15: continue
            sig = _analyze(raw, sym["symbol"])
            if not sig or sig.get("signal") not in ["BUY","SELL"]: continue
            if sig.get("score",0) < 75: continue  # Higher threshold for equity
            ltp = float(raw[-1][4])
            sl_pts = ltp * sym["min_sl_pct"]  # % based SL for equity
            tgt_pts = sl_pts * 2.0
            results.append({
                "symbol": sym["symbol"],
                "market": "NSE_EQUITY",
                "signal": sig["signal"],
                "score":  sig.get("score",0),
                "ltp":    ltp,
                "sl":     round(ltp-sl_pts,2) if sig["signal"]=="BUY" else round(ltp+sl_pts,2),
                "target": round(ltp+tgt_pts,2) if sig["signal"]=="BUY" else round(ltp-tgt_pts,2),
                "sl_pct": f"{sym['min_sl_pct']*100:.1f}%",
                "note":   "Direct equity — no F&O",
                "reasons": sig.get("reasons",[]),
            })
        return jsonify({"success":True,"signals":results,"count":len(results),"market":"NSE_EQUITY"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})
# Start Telegram bot
try:
    from alerts.telegram_bot import start as tg_start, alert_system
    tg_start()
    logger.info('Telegram bot started')
except Exception as e:
    logger.warning('Telegram not configured: %s', e)

# DISABLED_DUP_WS # Auto-start WebSocket for live LTP (24/7)
# DISABLED_DUP_WS try:
# DISABLED_DUP_WS     from broker.websocket_mgr import start as ws_start, status as ws_status
# DISABLED_DUP_WS     import threading
# DISABLED_DUP_WS     _ws_thread = threading.Thread(target=ws_start, daemon=True)
# DISABLED_DUP_WS     _ws_thread.start()
# DISABLED_DUP_WS     import time; time.sleep(3)
# DISABLED_DUP_WS     logger.info("WS Status: %s", ws_status()["connected"])
# DISABLED_DUP_WS except Exception as e:
# DISABLED_DUP_WS     logger.error("WS start failed: %s", e)
# Auto-start WebSocket (24/7 live LTP)
try:
    from broker.websocket_mgr import start as ws_start, status as ws_status
    import threading as _thr
    _wst = _thr.Thread(target=ws_start, daemon=True, name="ws-24x7")
    _wst.start()
    import time; time.sleep(3)
    logger.info("WS Status: %s", ws_status().get("connected"))
except Exception as e:
    logger.error("WS start failed: %s", e)

# Start Watchdog

try:

    from core.watchdog import run_watchdog

    from core.thread_registry import start_singleton

    start_singleton("Watchdog", run_watchdog)

    logger.info("🛡 Watchdog started")

    try:

        rec = recover_open_trades()

        logger.info(
            f"♻ Recovered "
            f"{rec['count']} open trades"
        )

        stale = detect_stale_trades()

        if stale:

            logger.warning(
                f"⚠ Stale trades detected: "
                f"{len(stale)}"
            )

    except Exception as re:

        logger.error(
            f"Recovery engine: {re}"
        )


except Exception as e:

    logger.error(f"Watchdog start failed: {e}")

    logger.error("WS start failed: %s", e)
# DISABLED_DUP_WS try:
# DISABLED_DUP_WS     from broker.websocket_mgr import start as ws_start, status as ws_status
# DISABLED_DUP_WS     import threading
# DISABLED_DUP_WS     threading.Thread(target=ws_start, daemon=True).start()
# DISABLED_DUP_WS     import time; time.sleep(2)
# DISABLED_DUP_WS     print("WebSocket:", ws_status())
# DISABLED_DUP_WS except Exception as e:
# DISABLED_DUP_WS     print("WS start error:", e)

# Pre-warm DataManager cache on startup
try:
    from data_stream.data_manager import get_data_manager
    import threading
    dm = get_data_manager()
    t = threading.Thread(target=dm.warm_cache, daemon=True)
    t.start()
except: pass



# ═══ SYMBOL MANAGEMENT APIS ═══

@app.route("/api/admin/symbols/search")
@require_auth
def search_symbols():
    """Search scrip master for symbol token/lot"""
    try:
        q = request.args.get("q","").upper().strip()
        exchange = request.args.get("exchange","").upper()
        if len(q) < 2:
            return jsonify({"success":False,"error":"Min 2 chars"})
        import json as jj
        with open("data/scrip_master.json") as f: scrips = jj.load(f)
        results = []
        seen = set()
        for s in scrips:
            sym  = s.get("symbol","").upper()
            name = s.get("name","").upper()
            exch = s.get("exch_seg","").upper()
            itype = s.get("instrumenttype","").upper()
            # Filter: only index/future/equity — not options
            if itype in ["CE","PE","OPTFUT","OPTIDX"]: continue
            if exchange and exch != exchange: continue
            if q not in sym and q not in name: continue
            # Deduplicate
            key = f"{name}_{exch}"
            if key in seen: continue
            seen.add(key)
            # Detect instrument type
            if exch in ["NFO","BFO"]:
                typ = "index" if "NIFTY" in sym or "SENSEX" in sym else "equity"
            elif exch == "MCX":
                typ = "commodity"
            else:
                typ = "equity"
            # Check if options exist
            has_opts = any(
                o.get("name","").upper()==name and
                o.get("exch_seg","").upper() in ["NFO","MCX"] and
                o.get("instrumenttype","").upper() in ["CE","PE","OPTFUT","OPTIDX"]
                for o in scrips[:5000]  # limit check
            ) if len(results) < 5 else False
            results.append({
                "symbol": name,
                "token":  s.get("token",""),
                "exchange": exch,
                "type": typ,
                "lot_size": int(float(s.get("lotsize",1) or 1)),
                "tick_size": float(s.get("tick_size",0.05) or 0.05),
                "instrument": itype,
            })
            if len(results) >= 15: break
        return jsonify({"success":True,"results":results,"count":len(results)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols", methods=["GET"])
@require_auth
def get_symbols():
    """Get all trading symbols"""
    try:
        import sqlite3 as sq
        conn = sq.connect("data/chanakya_v5.db")
        rows = conn.execute("""
            SELECT id,symbol,token,exchange,instrument_type,lot_size,
                   strike_interval,min_sl_pct,has_options,option_exchange,
                   is_active,created_at
            FROM trading_symbols ORDER BY exchange,instrument_type,symbol
        """).fetchall()
        conn.close()
        syms = [{"id":r[0],"symbol":r[1],"token":r[2],"exchange":r[3],
                 "type":r[4],"lot":r[5],"interval":r[6],"min_sl":r[7],
                 "has_options":bool(r[8]),"opt_exchange":r[9],
                 "active":bool(r[10]),"created":r[11]} for r in rows]
        return jsonify({"success":True,"symbols":syms,"total":len(syms)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols", methods=["POST"])
@require_role("developer","administrator")
def add_symbol():
    """Add new trading symbol"""
    try:
        data = request.json or {}
        sym      = data.get("symbol","").upper().strip()
        token    = str(data.get("token","")).strip()
        exchange = data.get("exchange","NSE").upper()
        sym_type = data.get("type","equity")
        lot      = int(data.get("lot_size",1))
        interval = int(data.get("strike_interval",50))
        min_sl   = float(data.get("min_sl_pct",0.004))
        has_opts = int(data.get("has_options",0))
        opt_exch = data.get("opt_exchange","NFO").upper()
        tick     = float(data.get("tick_size",0.05))

        if not sym or not token:
            return jsonify({"success":False,"error":"symbol and token required"})

        import sqlite3 as sq
        conn = sq.connect("data/chanakya_v5.db")
        conn.execute("""
            INSERT OR REPLACE INTO trading_symbols
            (symbol,token,exchange,instrument_type,lot_size,tick_size,
             strike_interval,min_sl_pct,has_options,option_exchange,is_active,added_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,1,?)
        """, (sym,token,exchange,sym_type,lot,tick,interval,min_sl,has_opts,opt_exch,
              request.username))
        conn.commit()
        conn.close()

        # Reload DataManager
        from data_stream.data_manager import get_data_manager
        dm = get_data_manager()
        total = dm.reload_symbols()

        return jsonify({"success":True,"message":f"{sym} added",
                       "total_symbols":total})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols/<symbol>", methods=["DELETE"])
@require_role("developer","administrator")
def delete_symbol(symbol):
    """Delete/deactivate trading symbol"""
    try:
        sym = symbol.upper()
        protected = ["NIFTY","BANKNIFTY","CRUDEOIL"]
        if sym in protected:
            return jsonify({"success":False,"error":f"{sym} is protected"})
        import sqlite3 as sq
        conn = sq.connect("data/chanakya_v5.db")
        conn.execute("UPDATE trading_symbols SET is_active=0 WHERE symbol=?", (sym,))
        conn.commit()
        conn.close()

        from data_stream.data_manager import get_data_manager
        dm = get_data_manager()
        dm.reload_symbols()

        return jsonify({"success":True,"message":f"{sym} removed"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols/<symbol>/expiry")
@require_auth
def symbol_expiry(symbol):
    """Auto-detect nearest expiry for symbol"""
    try:
        sym = symbol.upper()
        import json as jj, datetime as dt2, sqlite3 as sq
        today = dt2.date.today()

        # Get exchange from DB
        conn = sq.connect("data/chanakya_v5.db")
        row = conn.execute(
            "SELECT opt_exchange FROM trading_symbols WHERE symbol=? AND is_active=1",
            (sym,)).fetchone()
        conn.close()
        opt_exch = row[0] if row else "NFO"

        with open("data/scrip_master.json") as f: scrips = jj.load(f)

        # Find options for this symbol
        opts = [s for s in scrips
                if s.get("name","").upper()==sym
                and s.get("exch_seg","").upper()==opt_exch
                and s.get("instrumenttype","").upper() in ["CE","PE","OPTFUT","OPTIDX"]]

        def parse_exp(s):
            try: return dt2.datetime.strptime(s.get("expiry",""),"%d%b%Y").date()
            except: return dt2.date(2099,1,1)

        future = [s for s in opts if parse_exp(s) >= today and parse_exp(s).year < 2090]
        future.sort(key=parse_exp)

        expiries = sorted(set(s.get("expiry","") for s in future if s.get("expiry","")))

        return jsonify({"success":True,"symbol":sym,
                       "nearest_expiry": expiries[0] if expiries else None,
                       "all_expiries": expiries[:5]})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Global Broker Admin Routes ─────────────────────────
@app.route("/api/broker/status")
@require_auth
def broker_live_status():
    try:
        from broker.global_broker import get_broker
        b = get_broker()
        connected = b.is_connected() if hasattr(b,'is_connected') else b.connected
        import time
        last = getattr(b,'_last_connect', getattr(b._auth if hasattr(b,'_auth') else b, '_session_start', 0)) if hasattr(b,'_auth') else getattr(b,'_last_connect',0)
        age = int(time.time()-last) if last else 0
        return jsonify({"success":True,"status":{
            "connected":connected,
            "session_age_s":age,
            "session_ttl_s":max(0,25200-age),
        }})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/global-broker")
@require_role("developer","administrator")
def get_global_broker():
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv("/app/chanakya/.env")
        return jsonify({"success":True,"broker":{
            "api_key":   os.getenv("ANGEL_API_KEY",""),
            "client_id": os.getenv("ANGEL_CLIENT_ID",""),
            "password":  os.getenv("ANGEL_PASSWORD",""),
            "totp_key":  os.getenv("ANGEL_TOTP_KEY",""),
        }})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/global-broker", methods=["POST"])
@require_role("developer","administrator")
def save_global_broker():
    try:
        data = request.json or {}
        api_key   = data.get("api_key","").strip()
        client_id = data.get("client_id","").strip()
        password  = data.get("password","").strip()
        totp_key  = data.get("totp_key","").strip()
        if not all([api_key,client_id,password,totp_key]):
            return jsonify({"success":False,"error":"All fields required"})
        # Update .env file
        env_path = "/app/chanakya/.env"
        env = open(env_path).read()
        import re
        env = re.sub(r"ANGEL_API_KEY=.*",    f"ANGEL_API_KEY={api_key}",    env)
        env = re.sub(r"ANGEL_CLIENT_ID=.*",  f"ANGEL_CLIENT_ID={client_id}",env)
        env = re.sub(r"ANGEL_PASSWORD=.*",   f"ANGEL_PASSWORD={password}",  env)
        env = re.sub(r"ANGEL_TOTP_KEY=.*",   f"ANGEL_TOTP_KEY={totp_key}",  env)
        open(env_path,"w").write(env)
        # Reconnect broker
        import os
        os.environ["ANGEL_API_KEY"]   = api_key
        os.environ["ANGEL_CLIENT_ID"] = client_id
        os.environ["ANGEL_PASSWORD"]  = password
        os.environ["ANGEL_TOTP_KEY"]  = totp_key
        from broker.global_broker import get_broker
        b = get_broker()
        b.api_key=api_key; b.client_id=client_id
        b.password=password; b.totp_key=totp_key
        ok = b.connect()
        return jsonify({"success":True,"broker_connected":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


# ══ Socket.IO — Real-time LTP push ═══════════════════════
from flask_socketio import SocketIO
@socketio.on("connect")
def on_client_connect():
    logger.info("SocketIO client connected")

@socketio.on("disconnect")
def on_client_disconnect():
    logger.info("SocketIO client disconnected")

@socketio.on("subscribe")
def on_subscribe(data):
    """Client subscribes to specific tokens"""
    pass  # Broadcast mode — all clients get all ticks

# ══ LTP Broadcaster thread ════════════════════════════════
import threading as _threading

def _ltp_broadcast_loop():
    """Every 250ms broadcast latest LTP to all SocketIO clients"""
    import time as _t
    _prev = {}
    while True:
        _t.sleep(0.25)  # 4 ticks/sec max
        try:
            from broker.websocket_mgr import get_all_ltp
            from engine.scanner import WATCHLIST
            batch = {}
            for sym_info in WATCHLIST:
                sym   = sym_info["symbol"]
                token = str(sym_info["token"])
                exch  = sym_info["exchange"]
                cached = get_all_ltp().get(token)
                if isinstance(cached, dict):
                    price = cached.get("price")
                    ts    = cached.get("ts", 0)
                    import time as _t2
                    # Force fresh REST if WS stale
                    if not price or _t2.time()-ts > 30:
                        try:
                            from broker.global_broker import get_broker as _gb2
                            price = _gb2().get_ltp(exch, sym, token)
                            if price: ts = _t2.time()
                        except: pass
                    if price:
                        prev_price = _prev.get(token, 0)
                        if abs(float(price) - float(prev_price or 0)) > 0.01:  # changed only
                            batch[token] = {
                                "symbol": sym,
                                "exchange": exch,
                                "price": round(float(price),2),
                                "prev":  round(float(prev_price),2) if prev_price else round(float(price),2),
                                "ts": round(_t2.time()*1000),
                            }
                            _prev[token] = price
            if batch:
                socketio.emit("ltp_update", batch)
        except Exception as _e:
            pass  # Never crash broadcaster

_broadcaster = _threading.Thread(target=_ltp_broadcast_loop, daemon=True, name="LTPBroadcast")
_broadcaster.start()


@app.route("/api/ltp/live")
def ltp_live():
    """Fast LTP for all active symbols — called every 2s from frontend"""
    try:
        from data_stream.data_manager import get_data_manager
        dm = get_data_manager()
        data = {}
        for sym in ["NIFTY","BANKNIFTY","FINNIFTY","CRUDEOIL","NATURALGAS","GOLD"]:
            ltp = dm.get_ltp(sym)
            if ltp: data[sym] = ltp
        return jsonify({"success":True,"ltp":data,"ts":__import__("time").time()})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/api/pnl")
@require_auth
def get_pnl():
    try:
        import sqlite3 as sq
        conn = sq.connect("data/chanakya_v5.db")
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        trades = conn.execute("""
            SELECT pnl,status FROM trades
            WHERE username=? AND created_at>=?
        """, (request.username, today+" 00:00:00")).fetchall()
        conn.close()
        total_pnl = sum(float(t[0] or 0) for t in trades)
        total = len(trades)
        wins = sum(1 for t in trades if float(t[0] or 0) > 0)
        losses = sum(1 for t in trades if float(t[0] or 0) < 0)
        wr = round(wins/total*100) if total > 0 else 0
        return jsonify({"success":True,
                       "pnl":round(total_pnl,2),
                       "stats":{"total_trades":total,"wins":wins,
                                  "losses":losses,"win_rate":wr,
                                  "total_pnl":round(total_pnl,2)}})
    except Exception as e:
        return jsonify({"success":False,"pnl":0,
                       "stats":{"total_trades":0,"wins":0,"losses":0,"win_rate":0}})

@app.route("/api/history")
@require_auth
def trade_history():
    try:
        import sqlite3 as sq
        conn = sq.connect("data/chanakya_v5.db")
        trades = conn.execute("""
            SELECT id,symbol,direction,entry_price,exit_price,pnl,status,strategy,created_at
            FROM trades WHERE username=?
            ORDER BY id DESC LIMIT 50
        """, (request.username,)).fetchall()
        conn.close()
        return jsonify({"success":True,"trades":[
            {"id":t[0],"symbol":t[1],"direction":t[2],
             "entry_price":t[3],"exit_price":t[4],"pnl":t[5],
             "status":t[6],"strategy":t[7],"created_at":t[8]}
            for t in trades]})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"trades":[]})
@app.route("/api/stream/ltp")
@require_auth
def stream_ltp():
    """SSE — Live LTP every second from WebSocket cache"""
    from flask import Response, stream_with_context
    import json, time
    token = request.headers.get("X-Auth-Token","")

    def generate():
        while True:
            try:
                from broker.websocket_mgr import get_all_ltp_named, is_connected
                data = {
                    "ltp": get_all_ltp_named(),
                    "ws": is_connected(),
                    "ts": int(time.time()*1000)
                }
                yield f"data: {json.dumps(data)}\n\n"
            except Exception as e:
                yield f"data: {{}}\n\n"
            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        }
    )

@app.route("/api/options/chain")
@require_auth
@require_feature("options_chain_nse")
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
        # Cache options chain for 60s
        import time as _time
        _oc_cache = getattr(options_chain, '_cache', {})
        options_chain._cache = _oc_cache
        _cache_key = f"{symbol}_{sel_expiry}"
        _cached = _oc_cache.get(_cache_key)
        if _cached and _time.time() - _cached['ts'] < 60:
            return jsonify(_cached['data'])

        # Only fetch LTP for ATM ±10 strikes (performance)
        # First pass: build strike map without LTP
        for s in chain_opts:
            sym = s.get("symbol","")
            strike = s.get("strike","")
            try: strike = float(strike)/100 if float(strike)>10000 else float(strike)
            except: continue
            tok = str(s.get("token",""))
            if strike not in strikes:
                strikes[strike] = {"strike":strike,"ce_ltp":0,"pe_ltp":0,
                                   "ce_oi":0,"pe_oi":0,"ce_sym":"","pe_sym":"","ce_tok":"","pe_tok":""}
            if sym.endswith("CE"):
                strikes[strike]["ce_sym"] = sym
                strikes[strike]["ce_tok"] = tok
            elif sym.endswith("PE"):
                strikes[strike]["pe_sym"] = sym
                strikes[strike]["pe_tok"] = tok

        # Second pass: fetch LTP only for ATM ±5 strikes
        all_strikes = sorted(strikes.keys())
        atm_approx = min(all_strikes, key=lambda x: abs(x-spot)) if all_strikes and spot else None
        if atm_approx:
            atm_idx = all_strikes.index(atm_approx)
            active = all_strikes[max(0,atm_idx-5):atm_idx+6]
        else:
            active = all_strikes[:10]
        for strike in active:
            for side in [("ce_sym","ce_tok","ce_ltp"),("pe_sym","pe_tok","pe_ltp")]:
                sym,tok_k,ltp_k = side
                s_sym = strikes[strike].get(sym,"")
                s_tok = strikes[strike].get(tok_k,"")
                if s_sym and s_tok:
                    try: strikes[strike][ltp_k] = broker.get_ltp(exch_seg,s_sym,s_tok) or 0
                    except: pass

        # Sort strikes, find ATM
        all_chain = sorted(strikes.values(), key=lambda x:x["strike"])
        # Filter to ATM±15 only for display
        if all_chain and spot:
            atm_approx2 = min(all_chain, key=lambda x: abs(x["strike"]-spot))["strike"]
            atm_idx2 = [i for i,r in enumerate(all_chain) if r["strike"]==atm_approx2]
            if atm_idx2:
                ai = atm_idx2[0]
                chain = all_chain[max(0,ai-15):ai+16]
            else:
                chain = all_chain
        else:
            chain = all_chain
        atm = min(chain, key=lambda x: abs(x["strike"]-spot))["strike"] if chain and spot else 0

        # PCR
        total_ce_oi = sum(c["ce_oi"] for c in chain)
        total_pe_oi = sum(c["pe_oi"] for c in chain)
        pcr = round(total_pe_oi/total_ce_oi,2) if total_ce_oi else 0

        # Subscribe active tokens to WebSocket for live LTP
        try:
            from broker.websocket_mgr import add_token, _ws, _connected
            exch_num = 5 if is_mcx else 2  # MCX_FO=5, NSE_FO=2
            for strike in active:
                for tok_k in ["ce_tok","pe_tok"]:
                    tok_v = strikes[strike].get(tok_k,"")
                    if tok_v and _connected and _ws:
                        add_token(exch_num, tok_v)
        except: pass

        result = {
            "success":True,"symbol":symbol,"expiry":sel_expiry,
            "all_expiries":expiries,"spot":spot,"atm":atm,"pcr":pcr,
            "max_pain":atm,"is_mcx":is_mcx,"chain":chain,
            "total":len(chain)
        }
        options_chain._cache[_cache_key] = {"data":result,"ts":_time.time()}
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({"success":False,"error":str(e),"trace":traceback.format_exc()[-200:]})


@app.route("/api/options/ltp")
@require_auth
def options_ltp():
    """Fast LTP poll for subscribed option tokens"""
    tokens = request.args.get("tokens","").split(",")
    from broker.websocket_mgr import get_ltp
    result = {}
    for tok in tokens:
        tok = tok.strip()
        if tok:
            ltp = get_ltp(tok)
            if ltp: result[tok] = ltp
    return jsonify({"success":True,"ltp":result})

if __name__ == "__main__":
    PORT = int(os.getenv("PORT",5002))
    logger.info(f"Chanakya AI v5.0 starting on port {PORT}")
    import threading
    threading.Thread(target=_startup_train, daemon=True).start()
    threading.Thread(target=_prediction_scheduler, daemon=True).start()

    # ── WebSocket Manager start ────────────────────────
    def _start_websocket():
        import time
        time.sleep(8)  # Broker connect होऊ दे आधी
        try:
            from broker.websocket_mgr import start as ws_start
            ws_start()
            logger.info("✅ WebSocket Manager started")
        except Exception as e:
            logger.error(f"WebSocket Manager start error: {e}")

    threading.Thread(target=_start_websocket, daemon=True, name="WSManagerInit").start()

    # ── Pivot Blueprint ──────────────────────────────
    from api.routes.pivot import pivot_bp
    app.register_blueprint(pivot_bp, url_prefix="/api/pivot")

    # SocketIO run (backward compatible with Flask)
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False, allow_unsafe_werkzeug=True)







