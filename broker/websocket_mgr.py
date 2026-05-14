"""
Chanakya SmartWebSocket Manager™ — 24/7 Live LTP
Direct Angel One WebSocket — Binary parse — Auto JWT refresh
"""
import threading, time, logging, os, re, json, struct, ssl
import websocket
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("ws_mgr")
IST = pytz.timezone("Asia/Kolkata")

# ── LTP Cache ─────────────────────────────────────────────────────
_ltp      = {}
_ltp_lock = threading.Lock()

# ── State ─────────────────────────────────────────────────────────
_ws          = None
_connected   = False
_running     = False
_jwt         = None
_feed_token  = None
_jwt_expiry  = None
_retry_count = 0

# ── Token Registry ────────────────────────────────────────────────
TOKEN_MAP = {
    "99926000": "NIFTY",
    "99926009": "BANKNIFTY",
    "99926074": "MIDCPNIFTY",
    "99926037": "FINNIFTY",
    "488290":   "CRUDEOIL",
    "488505":   "NATURALGAS",
    "67694":    "GOLD",
    "67695":    "SILVER",
}

WATCH = {
    1: ["99926000","99926009","99926037","99926074"],  # NSE index
    5: ["488290","488505","466583","67695"],             # MCX
}

ENV_PATH = "/root/chanakya_v5/.env"

# ── LTP Access ────────────────────────────────────────────────────
def get_ltp(token):
    with _ltp_lock: return _ltp.get(str(token))

def get_ltp_by_symbol(symbol):
    for tok,sym in TOKEN_MAP.items():
        if sym==symbol.upper(): return get_ltp(tok)
    return None

def get_all_ltp():
    with _ltp_lock: return dict(_ltp)

def get_all_ltp_named():
    with _ltp_lock:
        return {TOKEN_MAP.get(k,k):v for k,v in _ltp.items()}

def set_ltp(token, price):
    with _ltp_lock: _ltp[str(token)] = float(price)

def is_connected(): return _connected

def status():
    return {
        "connected": _connected,
        "running":   _running,
        "ltp_count": len(_ltp),
        "symbols":   get_all_ltp_named(),
        "retry":     _retry_count,
    }

# ── Binary Parser (Angel One format) ─────────────────────────────
def _parse_binary(data):
    """Parse Angel One binary tick data"""
    try:
        # Minimum packet size check
        if len(data) < 51: return None
        # Extract token (bytes 2-27, null-terminated string)
        token_bytes = data[2:27]
        token = token_bytes.split(b'\x00')[0].decode('utf-8').strip()
        if not token: return None
        # LTP at bytes 43-51 (8 bytes, little-endian int64, in paise)
        ltp_paise = struct.unpack('<q', data[43:51])[0]
        # NSE index tokens → paise, MCX → direct
        ltp = ltp_paise / 100.0
        return {"token": token, "ltp": ltp}
    except Exception as e:
        logger.debug("Parse error: %s", e)
        return None

# ── JWT Management ────────────────────────────────────────────────
def _load_env():
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=True)
    return {
        "api_key":   os.getenv("ANGEL_API_KEY"),
        "client_id": os.getenv("ANGEL_CLIENT_ID"),
        "password":  os.getenv("ANGEL_PASSWORD"),
        "totp_key":  os.getenv("ANGEL_TOTP_KEY"),
        "jwt":       os.getenv("ANGEL_JWT",""),
        "feed":      os.getenv("ANGEL_FEED_TOKEN",""),
    }

def _save_env(key, value):
    with open(ENV_PATH,'r') as f: content=f.read()
    if key+'=' in content:
        content = re.sub(key+r'=.*', key+'='+value, content)
    else:
        content += f'\n{key}={value}'
    with open(ENV_PATH,'w') as f: f.write(content)

def _refresh_jwt():
    global _jwt, _feed_token, _jwt_expiry
    try:
        import pyotp
        from SmartApi import SmartConnect
        creds = _load_env()
        obj = SmartConnect(api_key=creds["api_key"])
        totp = pyotp.TOTP(creds["totp_key"]).now()
        data = obj.generateSession(creds["client_id"], creds["password"], totp)
        if data.get("status"):
            _jwt        = data["data"]["jwtToken"]
            _feed_token = data["data"]["feedToken"]
            _jwt_expiry = datetime.now(IST) + timedelta(hours=22)
            _save_env("ANGEL_JWT", _jwt)
            _save_env("ANGEL_FEED_TOKEN", _feed_token)
            logger.info("✅ JWT refreshed")
            return True
        return False
    except Exception as e:
        logger.error("JWT refresh error: %s", e)
        return False

def _is_jwt_valid():
    return _jwt and _feed_token and _jwt_expiry and datetime.now(IST) < _jwt_expiry

# ── Subscribe ─────────────────────────────────────────────────────
def _subscribe(ws_obj):
    """Send subscription for all tokens"""
    for exch_type, tokens in WATCH.items():
        msg = json.dumps({
            "action": 1,
            "params": {
                "mode": 1,
                "tokenList": [{"exchangeType": exch_type, "tokens": tokens}]
            }
        })
        try:
            ws_obj.send(msg)
            logger.info("Subscribed %d tokens exch=%d", len(tokens), exch_type)
        except Exception as e:
            logger.error("Subscribe error: %s", e)

# ── WebSocket Callbacks ───────────────────────────────────────────
def _on_open(ws):
    global _connected, _retry_count
    _connected   = True
    _retry_count = 0
    logger.info("✅ WebSocket CONNECTED!")
    _subscribe(ws)

def _on_message(ws, msg):
    try:
        if isinstance(msg, bytes):
            parsed = _parse_binary(msg)
            if parsed and parsed["token"] in TOKEN_MAP:
                set_ltp(parsed["token"], parsed["ltp"])
                logger.debug("LTP %s = %.2f", TOKEN_MAP[parsed["token"]], parsed["ltp"])
        elif isinstance(msg, str):
            d = json.loads(msg)
            if "token" in d and "ltp" in d:
                set_ltp(d["token"], d["ltp"])
    except Exception as e:
        logger.debug("Message error: %s", e)

def _on_error(ws, error):
    global _connected
    _connected = False
    logger.warning("⚠️ WS Error: %s", error)

def _on_close(ws, *args):
    global _connected
    _connected = False
    logger.warning("🔴 WS Closed")

# ── Connection ────────────────────────────────────────────────────
def _connect():
    global _ws, _jwt, _feed_token, _jwt_expiry
    try:
        if not _is_jwt_valid():
            logger.info("Refreshing JWT...")
            if not _refresh_jwt(): return False
        creds = _load_env()
        jwt   = _jwt or creds["jwt"]
        feed  = _feed_token or creds["feed"]
        api_key   = creds["api_key"]
        client_id = creds["client_id"]
        headers = {
            "Authorization": jwt,
            "x-api-key":     api_key,
            "x-client-code": client_id,
            "x-feed-token":  feed,
        }
        _ws = websocket.WebSocketApp(
            "wss://smartapisocket.angelone.in/smart-stream",
            header=[f"{k}: {v}" for k,v in headers.items()],
            on_open=_on_open, on_message=_on_message,
            on_error=_on_error, on_close=_on_close,
        )
        logger.info("Connecting to Angel One WebSocket...")
        _ws.run_forever(
            sslopt={"cert_reqs": ssl.CERT_NONE},
            ping_interval=25, ping_timeout=10
        )
    except Exception as e:
        logger.error("Connect error: %s", e)

# ── 24/7 Main Loop ────────────────────────────────────────────────
def _run_forever():
    global _running, _retry_count
    _running = True
    logger.info("🚀 WS Manager started — 24/7 mode")
    while _running:
        try:
            if not _connected:
                wait = min(5 * (2 ** min(_retry_count, 4)), 120)
                if _retry_count > 0:
                    logger.info("⏳ Reconnect in %ds (attempt %d)...", wait, _retry_count)
                    time.sleep(wait)
                _retry_count += 1
                _connect()  # Blocking until disconnect
            # JWT refresh check
            if _jwt_expiry:
                remaining = (_jwt_expiry - datetime.now(IST)).total_seconds()
                if remaining < 3600:
                    logger.info("JWT expiring — refreshing...")
                    _refresh_jwt()
            time.sleep(5)
        except Exception as e:
            logger.error("Loop error: %s", e)
            time.sleep(10)

def start():
    global _running, _jwt, _feed_token, _jwt_expiry
    if _running: return
    creds = _load_env()
    _jwt        = creds.get("jwt","")
    _feed_token = creds.get("feed","")
    _jwt_expiry = datetime.now(IST) + timedelta(hours=20)
    t = threading.Thread(target=_run_forever, daemon=True, name="ws-24x7")
    t.start()
    logger.info("WebSocket thread started")

def stop():
    global _running, _ws
    _running = False
    if _ws:
        try: _ws.close()
        except: pass

def add_token(exchange_type, token):
    if exchange_type not in WATCH: WATCH[exchange_type] = []
    if token not in WATCH[exchange_type]:
        WATCH[exchange_type].append(token)
        TOKEN_MAP[token] = token
        if _connected and _ws: _subscribe(_ws)
