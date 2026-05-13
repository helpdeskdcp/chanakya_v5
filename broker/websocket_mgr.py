"""
Chanakya SmartWebSocket Manager™ — 24/7 Live LTP
Features:
- Auto-reconnect on disconnect
- JWT auto-refresh (expires daily)
- Exponential backoff retry
- All NSE + MCX symbols
- Thread-safe LTP cache
- Health monitor
"""
import threading, time, logging, os, json
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("ws_mgr")
IST = pytz.timezone("Asia/Kolkata")

# ── LTP Cache ─────────────────────────────────────────────────────
_ltp = {}          # {token: price}
_ltp_lock = threading.Lock()
_last_tick = {}    # {token: timestamp}

# ── State ─────────────────────────────────────────────────────────
_ws          = None
_connected   = False
_running     = False
_jwt         = None
_feed_token  = None
_jwt_expiry  = None
_retry_count = 0
_lock        = threading.Lock()

# ── Token Registry ────────────────────────────────────────────────
# exchange_type: 1=NSE_CM, 2=NSE_FO, 5=MCX_FO
WATCH_TOKENS = {
    1: [   # NSE Cash/Index
        "99926000",   # NIFTY 50
        "99926009",   # BANKNIFTY
        "99926074",   # FINNIFTY
        "99926037",   # MIDCPNIFTY
    ],
    5: [   # MCX F&O
        "488290",     # CRUDEOIL
        "488505",     # NATURALGAS
        "67694",      # GOLD
        "67695",      # SILVER
    ]
}

# Token → Symbol name map
TOKEN_MAP = {
    "99926000": "NIFTY",
    "99926009": "BANKNIFTY",
    "99926074": "FINNIFTY",
    "99926037": "MIDCPNIFTY",
    "488290":   "CRUDEOIL",
    "488505":   "NATURALGAS",
    "67694":    "GOLD",
    "67695":    "SILVER",
}

# ── LTP Access ────────────────────────────────────────────────────
def get_ltp(token):
    with _ltp_lock:
        return _ltp.get(str(token))

def get_all_ltp():
    with _ltp_lock:
        return dict(_ltp)

def get_ltp_by_symbol(symbol):
    for tok, sym in TOKEN_MAP.items():
        if sym == symbol.upper():
            return get_ltp(tok)
    return None

def set_ltp(token, price):
    with _ltp_lock:
        _ltp[str(token)] = float(price)
        _last_tick[str(token)] = time.time()

def is_connected():
    return _connected

def status():
    return {
        "connected": _connected,
        "running": _running,
        "ltp_count": len(_ltp),
        "symbols": {TOKEN_MAP.get(k, k): v for k,v in _ltp.items()},
        "retry_count": _retry_count,
        "jwt_valid": _jwt is not None,
        "jwt_expiry": str(_jwt_expiry) if _jwt_expiry else None,
    }

# ── JWT Management ────────────────────────────────────────────────
def _get_credentials():
    """Load fresh credentials from .env"""
    from dotenv import load_dotenv
    load_dotenv("/root/chanakya_v5/.env", override=True)
    return {
        "api_key":    os.getenv("ANGEL_API_KEY"),
        "client_id":  os.getenv("ANGEL_CLIENT_ID"),
        "password":   os.getenv("ANGEL_PASSWORD"),
        "totp_key":   os.getenv("ANGEL_TOTP_KEY"),
        "jwt":        os.getenv("ANGEL_JWT"),
        "feed_token": os.getenv("ANGEL_FEED_TOKEN"),
    }

def _refresh_jwt():
    """Refresh JWT token — called daily or on 401"""
    global _jwt, _feed_token, _jwt_expiry
    try:
        import pyotp
        from SmartApi import SmartConnect
        creds = _get_credentials()
        obj = SmartConnect(api_key=creds["api_key"])
        totp = pyotp.TOTP(creds["totp_key"]).now()
        data = obj.generateSession(creds["client_id"], creds["password"], totp)
        if data.get("status"):
            _jwt = data["data"]["jwtToken"]
            _feed_token = data["data"]["feedToken"]
            _jwt_expiry = datetime.now(IST) + timedelta(hours=22)
            # Save to .env
            _save_env("ANGEL_JWT", _jwt)
            _save_env("ANGEL_FEED_TOKEN", _feed_token)
            logger.info("✅ JWT refreshed, valid till %s", _jwt_expiry)
            return True
        else:
            logger.error("JWT refresh failed: %s", data)
            return False
    except Exception as e:
        logger.error("JWT refresh error: %s", e)
        return False

def _save_env(key, value):
    """Save key=value to .env file"""
    import re
    env_path = "/root/chanakya_v5/.env"
    with open(env_path, "r") as f: content = f.read()
    if key + "=" in content:
        content = re.sub(key + r"=.*", key + "=" + value, content)
    else:
        content += f"\n{key}={value}"
    with open(env_path, "w") as f: f.write(content)

def _is_jwt_valid():
    """Check if JWT is still valid"""
    if not _jwt or not _jwt_expiry:
        return False
    return datetime.now(IST) < _jwt_expiry

def _is_market_hours():
    """Check if any market is open"""
    now = datetime.now(IST)
    h, m = now.hour, now.minute
    # NSE: 9:15-15:30
    nse = (h == 9 and m >= 15) or (10 <= h <= 14) or (h == 15 and m <= 30)
    # MCX: 9:00-23:30
    mcx = (h >= 9) and (h < 23 or (h == 23 and m <= 30))
    return nse or mcx

# ── WebSocket Callbacks ───────────────────────────────────────────
def _on_data(wsapp, data):
    """Handle incoming tick data"""
    global _connected
    try:
        if isinstance(data, str):
            data = json.loads(data)
        token = str(data.get("token", ""))
        ltp = data.get("last_traded_price", 0)
        if token and ltp:
            # Angel One sends LTP in paise for some, rupees for others
            price = float(ltp)
            if token in ["99926000","99926009","99926074","99926037"]:
                price = price / 100  # NSE Index in paise
            set_ltp(token, price)
    except Exception as e:
        logger.debug("Data parse error: %s | data: %s", e, str(data)[:100])

def _on_open(wsapp):
    global _connected, _retry_count
    _connected = True
    _retry_count = 0
    logger.info("✅ WebSocket connected!")
    _subscribe_all(wsapp)

def _on_error(wsapp, error):
    global _connected
    _connected = False
    logger.warning("⚠️ WebSocket error: %s", error)

def _on_close(wsapp, *args):
    global _connected
    _connected = False
    logger.warning("🔴 WebSocket closed")

def _subscribe_all(wsapp):
    """Subscribe to all tokens"""
    try:
        for exch_type, tokens in WATCH_TOKENS.items():
            token_list = [{"exchangeType": exch_type, "tokens": tokens}]
            wsapp.subscribe("chanakya_v5", 1, token_list)
            logger.info("Subscribed %d tokens on exchange %d", len(tokens), exch_type)
    except Exception as e:
        logger.error("Subscribe error: %s", e)

# ── Connection Manager ────────────────────────────────────────────
def _connect():
    """Create and connect WebSocket"""
    global _ws, _connected, _retry_count
    try:
        if not _is_jwt_valid():
            logger.info("JWT expired — refreshing...")
            if not _refresh_jwt():
                return False

        creds = _get_credentials()
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        _ws = SmartWebSocketV2(
            auth_token=_jwt or creds["jwt"],
            api_key=creds["api_key"],
            client_code=creds["client_id"],
            feed_token=_feed_token or creds["feed_token"],
        )
        _ws.on_open = _on_open
        _ws.on_data = _on_data
        _ws.on_error = _on_error
        _ws.on_close = _on_close
        _ws.connect()
        return True
    except Exception as e:
        logger.error("Connect error: %s", e)
        _connected = False
        return False

# ── Main Loop — 24/7 ─────────────────────────────────────────────
def _run_forever():
    """Main loop — reconnect on any disconnect"""
    global _running, _retry_count
    _running = True
    logger.info("🚀 WebSocket manager started — 24/7 mode")

    while _running:
        try:
            if not _connected:
                # Exponential backoff: 5s, 10s, 20s, 40s max 120s
                wait = min(5 * (2 ** min(_retry_count, 4)), 120)
                if _retry_count > 0:
                    logger.info("⏳ Reconnecting in %ds (attempt %d)...", wait, _retry_count+1)
                    time.sleep(wait)
                _retry_count += 1
                _connect()

            # Health check every 30s
            time.sleep(30)

            # JWT refresh 1hr before expiry
            if _jwt_expiry:
                remaining = (_jwt_expiry - datetime.now(IST)).total_seconds()
                if remaining < 3600:
                    logger.info("JWT expiring soon — refreshing...")
                    _refresh_jwt()

        except Exception as e:
            logger.error("Run loop error: %s", e)
            time.sleep(10)

# ── Public API ────────────────────────────────────────────────────
def start():
    """Start WebSocket in background thread"""
    global _running
    if _running:
        return
    # Load initial JWT
    creds = _get_credentials()
    global _jwt, _feed_token
    _jwt = creds.get("jwt")
    _feed_token = creds.get("feed_token")
    if _jwt:
        global _jwt_expiry
        _jwt_expiry = datetime.now(IST) + timedelta(hours=20)

    t = threading.Thread(target=_run_forever, daemon=True, name="ws-manager")
    t.start()
    logger.info("WebSocket manager thread started")

def stop():
    global _running, _connected, _ws
    _running = False
    _connected = False
    if _ws:
        try: _ws.close_connection()
        except: pass

def add_tokens(exchange_type, tokens):
    """Add new tokens to watch list"""
    if exchange_type not in WATCH_TOKENS:
        WATCH_TOKENS[exchange_type] = []
    for t in tokens:
        if t not in WATCH_TOKENS[exchange_type]:
            WATCH_TOKENS[exchange_type].append(t)
    if _connected and _ws:
        _subscribe_all(_ws)

