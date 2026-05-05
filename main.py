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
    at_start(mode="PAPER", auto_trade=False)
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
if __name__ == "__main__":
    PORT = int(os.getenv("PORT",5002))
    logger.info(f"Chanakya AI v5.0 starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
