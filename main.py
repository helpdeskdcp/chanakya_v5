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
        from ai.groq_client import chat_with_context
        ltps = get_live_ltps()
        reply = chat_with_context(msg, ltps)
        return jsonify({"success":True,"reply":reply})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Trade routes ───────────────────────────────────────
@app.route("/api/trades")
@require_auth
def get_trades():
    try:
        from trading.paper_engine import get_open_trades, get_all_trades
        mode = request.args.get("mode","open")
        if mode == "open":
            trades = get_open_trades(request.username)
        else:
            trades = get_all_trades(request.username)
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
            return jsonify({"success":bool(tid),"trade_id":tid,"mode":"PAPER"})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

@app.route("/api/trades/<int:tid>/close", methods=["POST"])
@require_auth
def close_trade(tid):
    try:
        data = request.json or {}
        exit_price = float(data.get("exit_price",0))
        from trading.paper_engine import close_trade as ct
        ok = ct(tid, exit_price, "manual")
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
@app.route("/api/pnl")
@require_auth
def pnl():
    try:
        from trading.paper_engine import get_pnl_summary
        return jsonify({"success":True,"pnl":get_pnl_summary(request.username)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})

# ── Frontend ───────────────────────────────────────────
@app.route("/")
@app.route("/v5")
@app.route("/v5/")
def index():
    try:
        return render_template("index.html")
    except:
        return "<h1>Chanakya AI v5.0</h1><p>Frontend loading...</p>"

if __name__ == "__main__":
    PORT = int(os.getenv("PORT",5002))
    logger.info(f"Chanakya AI v5.0 starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
