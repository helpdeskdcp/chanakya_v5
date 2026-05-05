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


# ── Symbol Manager Routes ──────────────────────────────
@app.route("/api/symbols")
@require_auth
def get_symbols():
    try:
        from database.symbol_manager import get_user_symbols
        user = request.user
        syms = get_user_symbols(request.username, user.get("role","demo"))
        return jsonify({"success":True,"symbols":syms,"total":len(syms)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols")
@require_role("developer","administrator")
def admin_get_symbols():
    try:
        from database.symbol_manager import get_all_symbols
        syms = get_all_symbols(active_only=False)
        return jsonify({"success":True,"symbols":syms})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols", methods=["POST"])
@require_role("developer","administrator")
def admin_add_symbol():
    try:
        data = request.json or {}
        from database.symbol_manager import add_symbol, set_symbol_access
        sid = add_symbol(
            data.get("symbol",""), data.get("trading_symbol",""),
            data.get("token",""), data.get("exchange","NSE"),
            data.get("instrument_type","INDEX"),
            int(data.get("lot_size",1)), float(data.get("tick_size",0.05)),
            request.username)
        if not sid:
            return jsonify({"success":False,"error":"Add failed"})
        # Default access set करूया
        roles = data.get("roles", ["developer","administrator","platinum","gold","premium","silver"])
        users = data.get("users", [])
        can_live = int(data.get("can_live",0))
        for role in roles:
            can_l = 1 if role in ["developer","administrator","platinum","gold"] else can_live
            set_symbol_access(sid,"role",role,1,1,can_l,1)
        for user in users:
            set_symbol_access(sid,"user",user,1,1,can_live,1)
        return jsonify({"success":True,"symbol_id":sid})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols/<int:sid>", methods=["DELETE"])
@require_role("developer","administrator")
def admin_delete_symbol(sid):
    try:
        from database.symbol_manager import delete_symbol
        ok = delete_symbol(sid)
        return jsonify({"success":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols/<int:sid>/access", methods=["POST"])
@require_role("developer","administrator")
def admin_set_access(sid):
    try:
        data = request.json or {}
        from database.symbol_manager import set_symbol_access
        ok = set_symbol_access(sid,
            data.get("access_type","role"), data.get("access_value",""),
            int(data.get("can_scan",1)), int(data.get("can_paper",1)),
            int(data.get("can_live",0)), int(data.get("can_signal",1)))
        return jsonify({"success":ok})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/admin/symbols/search")
@require_role("developer","administrator")
def admin_search_symbol():
    try:
        query = request.args.get("q","")
        exchange = request.args.get("exchange","NSE")
        from database.symbol_manager import search_angel_symbol
        results = search_angel_symbol(query, exchange)
        return jsonify({"success":True,"results":results})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── App Settings Routes ────────────────────────────────
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


# ── Auto start position monitor on boot ───────────────
try:
    from trading.auto_trader import start as at_start
    at_start(mode="PAPER", auto_trade=True)
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

                opt_entry=opt_ltp or 0
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
                    "opt_sl":   round(opt_entry*0.70,2) if opt_entry else 0,
                    "opt_target":round(opt_entry*1.40,2) if opt_entry else 0,
                    "opt_trail": round(opt_entry*0.85,2) if opt_entry else 0,
                    "opt_exchange":EXCH.get(sym["name"],"NFO"),
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
    try:
        from scalping_engine.strategy import generate_signal
        from scalping_engine.risk_manager import RiskManager
        from scalping_engine.ai_engine import adaptive_confidence
        from broker.global_broker import get_broker
        broker = get_broker()
        SYMS = [
            {"name":"NIFTY","token":"99926000","exchange":"NSE","lot":65,"interval":50},
            {"name":"BANKNIFTY","token":"99926009","exchange":"NSE","lot":30,"interval":100},
            {"name":"CRUDEOIL","token":"488290","exchange":"MCX","lot":100,"interval":50},
            {"name":"NATURALGAS","token":"488505","exchange":"MCX","lot":1250,"interval":10},
        ]
        rm = RiskManager()
        results = []
        import datetime as dt
        from datetime import datetime
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(IST)
        now_h = now_ist.hour; now_m = now_ist.minute
        # Market hours
        nse_open = (now_h==9 and now_m>=15) or (10<=now_h<=15) or (now_h==15 and now_m<=30)
        mcx_open = (now_h>=9 and now_h<=23) or now_h==0
        today = dt.date.today()
        for sym in SYMS:
            # Skip NSE symbols when NSE closed
            if sym["exchange"]=="NSE" and not nse_open: continue
            # Skip MCX when MCX closed
            if sym["exchange"]=="MCX" and not mcx_open: continue
            import time
            time.sleep(0.3)  # Rate limit protection
            raw = None
            for attempt in range(3):
                try:
                    raw = broker.get_candles(sym["token"],sym["exchange"],"FIVE_MINUTE",2)
                    if raw and len(raw)>=22: break
                    time.sleep(1)
                except: time.sleep(1)
            if not raw or len(raw)<22: continue
            candles=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),
                      "c":float(x[4]),"v":float(x[5]) if len(x)>5 else 0} for x in raw]
            sig = generate_signal(candles)
            conf = adaptive_confidence(sig["score"],sig["active_strategy"],sym["name"])
            sig["confidence"]=conf
            # MCX lower threshold (thinner market but still tradeable)
            min_conf = 55 if sym["exchange"]=="MCX" else 62
            if sig["signal"]=="NO_TRADE" or conf<min_conf: continue
            tp = rm.calculate_trade(sig["signal"],sig["price"],sig["atr"],sym["lot"])
            # Option selection
            opt_type = "CE" if sig["signal"]=="BUY_CE" else "PE"
            interval = sym.get("interval",50)
            atm = round(sig["price"]/interval)*interval
            opt_ltp = None; opt_sym = None; opt_token = None
            # Try ATM then nearby strikes
            for strike_offset in [0, 1, -1, 2, -2]:
                strike = atm + strike_offset*interval
                try:
                    import json as jj
                    with open("data/scrip_master.json") as f: scrips=jj.load(f)
                    EXCH_MAP={"NIFTY":"NFO","BANKNIFTY":"NFO","FINNIFTY":"NFO",
                               "CRUDEOIL":"MCX","NATURALGAS":"MCX"}
                    pexch = EXCH_MAP.get(sym["name"],"NFO")
                    strike_s = str(int(strike))
                    matches = [s for s in scrips
                               if s.get("exch_seg","").upper()==pexch
                               and s.get("symbol","").upper().startswith(sym["name"].upper())
                               and s.get("symbol","").upper().endswith(strike_s+opt_type)]
                    import datetime as dt2
                    def ekey(s):
                        try: return dt2.datetime.strptime(s.get("expiry",""),"%d%b%Y").date()
                        except: return dt2.date(2099,1,1)
                    future = [s for s in matches if ekey(s)>=today and ekey(s).year<2090]
                    if not future: continue
                    future.sort(key=ekey)
                    best = future[0]
                    ltp = broker.get_ltp(pexch, best.get("symbol",""), str(best.get("token","")))
                    if ltp and ltp>0:
                        opt_ltp=ltp; opt_sym=best.get("symbol"); opt_token=str(best.get("token"))
                        atm=strike; break
                except: continue
            # Option TP with option price
            opt_entry = opt_ltp or 0
            opt_sl     = round(opt_entry*0.70,2) if opt_entry else 0
            opt_target = round(opt_entry*1.40,2) if opt_entry else 0
            opt_trail  = round(opt_entry*0.85,2) if opt_entry else 0
            results.append({
                "symbol":sym["name"],"signal":sig["signal"],
                "price":sig["price"],"score":conf,
                "strategy":sig["active_strategy"],
                "sl":tp["sl"],"target":tp["target"],"qty":tp["qty"],
                "rsi":sig["rsi"],"trend":sig["trend"],
                "reasons":sig["reasons"],"rr":tp["rr"],
                "atr":sig["atr"],
                # Option details
                "opt_type":opt_type,
                "opt_symbol":opt_sym,
                "opt_token":opt_token,
                "opt_ltp":opt_ltp,
                "opt_strike":atm,
                "opt_entry":opt_entry,
                "opt_sl":opt_sl,
                "opt_target":opt_target,
                "opt_trail":opt_trail,
                "opt_lot":sym["lot"],
                "opt_exchange":EXCH_MAP.get(sym["name"],"NFO"),
            })
        return jsonify({"success":True,"signals":results,"count":len(results)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/scalping/stats")
@require_auth
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
            target_price,quantity,mode,strategy,created_at
            FROM trades WHERE username=? AND status='OPEN'
            ORDER BY id DESC""",
            (request.username,)).fetchall()
        result = []
        from broker.global_broker import get_broker
        broker = get_broker()
        for t in trades:
            tid,sym,dire,entry,sl,target,qty,mode,strat,ts = t
            # Get current LTP
            ltp = None
            try:
                # Find token from scrip master
                import json as jj
                with open("data/scrip_master.json") as f: scrips=jj.load(f)
                found = [s for s in scrips if s.get("symbol","").upper()==sym.upper()]
                if found:
                    s = found[0]
                    ltp = broker.get_ltp(s.get("exch_seg","NFO"),sym,str(s.get("token","")))
            except: pass

            pnl = 0; trail_sl = sl; status_msg = "HOLD"
            if ltp:
                pnl = round((ltp - entry) * qty, 2)
                # Trailing SL logic (SEBI style)
                profit_pct = (ltp - entry) / entry * 100 if entry > 0 else 0
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
if __name__ == "__main__":
    PORT = int(os.getenv("PORT",5002))
    logger.info(f"Chanakya AI v5.0 starting on port {PORT}")
    import threading
    threading.Thread(target=_startup_train, daemon=True).start()
    threading.Thread(target=_prediction_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)



