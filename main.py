from werkzeug.middleware.proxy_fix import ProxyFix
import os, sys, logging
sys.path.insert(0,'/root/chanakya_v5')
from flask import Flask, jsonify, request, render_template, session
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler("data/app.log")])
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="frontend/templates")
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

# ── Auth routes ────────────────────────────────────────
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
        user = get_user(username) or {}
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
        from engine.scanner import get_live_ltps
        from data_stream.cache import get as cget, set as cset
        ltps = cget("market_ltps")
        if not ltps:
            ltps = get_live_ltps()
            if ltps: cset("market_ltps", ltps, ttl=5)
        return jsonify({"success":True,"data":ltps or {}})
    except Exception as e:
        return jsonify({"success":False,"error":str(e),"data":{}})

# ── Signal routes ──────────────────────────────────────
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
        from ai.chat import smart_chat
        from broker.global_broker import get_broker
        reply = smart_chat(msg, get_broker())
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
        if mode == "open":
            trades = get_open_trades(request.username)
        else:
            trades = get_all_trades(request.username)
        # Add live LTP to each trade
        try:
            broker = get_broker()
            if broker and broker.is_connected():
                for t in trades:
                    ltp = broker.get_ltp(t.get("exchange","NSE"), t.get("symbol",""), t.get("token",""))
                    if ltp:
                        t["ltp"] = ltp
                        qty = t.get("qty",1)
                        entry = t.get("entry_price",0)
                        if t.get("direction") == "BUY":
                            t["live_pnl"] = round((ltp-entry)*qty, 2)
                        else:
                            t["live_pnl"] = round((entry-ltp)*qty, 2)
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
        sigs = None if force else cget("predictions")
        if not sigs:
            import threading
            from ai.predictor import run_scan
            sigs = run_scan(get_broker())
            if sigs: cset("predictions", sigs, ttl=300)
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


@app.route("/api/options-chain")
@require_auth
def options_chain():
    try:
        symbol = request.args.get("symbol","NIFTY")
        from data_stream.cache import get as cget, set as cset
        from broker.global_broker import get_broker
        key = "chain_"+symbol
        data = cget(key)
        if not data:
            from ai.options_ai import get_option_signal
            data = get_option_signal(symbol, get_broker())
            if data and "error" not in data: cset(key, data, ttl=300)
        return jsonify({"success":True,"data":data})
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
            return jsonify({"success":False,"error":"Broker not connected"})
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

if __name__ == "__main__":
    PORT = int(os.getenv("PORT",5002))
    logger.info(f"Chanakya AI v5.0 starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
