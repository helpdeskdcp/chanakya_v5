"""
Chanakya SmartWebSocket Manager™ — 24/7 Live LTP
Direct Angel One WebSocket — Binary parse — Auto JWT refresh
"""
import threading
from core.auth_throttle import (
    can_refresh,
    mark_attempt,
    mark_success,
    mark_failure
)

_REFRESH_LOCK = threading.Lock()
import time, logging, os, re, json, struct, ssl
import websocket
from core.heartbeat import beat
from core.rate_limiter import allow
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("ws_mgr")
IST = pytz.timezone("Asia/Kolkata")

# ── LTP + OI Cache ─────────────────────────────────────────────────
_ltp      = {}   # {token: price}
_oi       = {}   # {token: open_interest}
_vol      = {}   # {token: volume}
_bid      = {}   # {token: bid_price}
_ask      = {}   # {token: ask_price}
_ltp_lock = threading.Lock()

# ── State ─────────────────────────────────────────────────────────
_ws          = None
_ws_thread = None
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
    2: ["57036","57037"],  # NFO ATM options
    5: ["488290","488505","466583","67695"],             # MCX
}

ENV_PATH = "/app/chanakya/.env"

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

def get_oi(token):
    with _ltp_lock: return _oi.get(str(token))

def get_bid_ask(token):
    with _ltp_lock: return _bid.get(str(token)), _ask.get(str(token))

def get_all_oi():
    with _ltp_lock: return dict(_oi)

def set_ltp(token, price):
    beat()
    with _ltp_lock: _ltp[str(token)] = float(price)

def set_tick(token, price, oi=None, vol=None, bid=None, ask=None):
    beat()
    with _ltp_lock:
        tok = str(token)
        if price: _ltp[tok] = float(price)
        if oi is not None: _oi[tok] = int(oi)
        if vol is not None: _vol[tok] = int(vol)
        if bid is not None: _bid[tok] = float(bid)
        if ask is not None: _ask[tok] = float(ask)

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
    """SmartAPI V2 Binary Parser"""

    try:

        if len(data) < 60:
            return None

        # DEBUG LOG REMOVED

        # ---- TOKEN ----
        raw_token = data[2:27]

        token = (
            raw_token
            .replace(b"\\x00", b"")
            .decode("utf-8", errors="ignore")
            .strip()
        )

        token = "".join(ch for ch in token if ch.isdigit())

        # DEBUG LOG REMOVED

        if not token:
            return None

        # ---- FIXED SMARTAPI V2 LTP OFFSET ----

        try:

            ltp_raw = struct.unpack("<i", data[43:47])[0]

            ltp = ltp_raw / 100.0

            global LAST_TICK_TS
            import time
            globals()["LAST_TICK_TS"] = time.time()

            if ltp <= 0:
                return None

            return {
                "token": token,
                "ltp": ltp,
                "oi": None,
                "vol": None,
                "bid": None,
                "ask": None
            }

        except Exception as e:

            logger.error(f"LTP PARSE ERROR: {e}")

            return None

        if ltp <= 0:
            return None

        return {
            "token": token,
            "ltp": ltp,
            "oi": None,
            "vol": None,
            "bid": None,
            "ask": None
        }

    except Exception as e:

        logger.error(f"PARSE ERROR: {e}")

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
        from broker.auth_manager import get_auth

        auth = get_auth()

        if not auth.ensure_connected():
            logger.error("AuthManager connection failed")
            return False

        api = auth.get_api()

        if not api:
            logger.error("AuthManager returned no API")
            return False

        _feed_token = getattr(api, "feed_token", "")

        if not _feed_token:
            logger.error("Feed token missing")
            return False

        creds = _load_env()

        _jwt = creds.get("jwt", "")
        _jwt_expiry = datetime.now(IST) + timedelta(hours=6)

        logger.info("✅ JWT refreshed via AuthManager")

        return True

    except Exception as e:
        logger.error(f"JWT refresh error: {e}")
        return False

    try:

        gate = can_refresh()

        if not gate["allowed"]:

            logger.warning(
                f"⏳ JWT cooldown "
                f"{gate['wait']}s "
                f"(fails={gate['fails']})"
            )

            return False

        mark_attempt()

        import pyotp

        from SmartApi import SmartConnect

        creds = _load_env()

        logger.info("Using centralized AuthManager...")

        obj = SmartConnect(
            api_key=creds["api_key"]
        )

        totp = pyotp.TOTP(
            creds["totp_key"]
        ).now()

        data = obj.generateSession(
            creds["client_id"],
            creds["password"],
            totp
        )

        if data.get("status"):

            _jwt = data["data"]["jwtToken"]                 .replace("Bearer ","")                 .strip()

            _feed_token = data["data"]["feedToken"]

            _jwt_expiry = datetime.now(IST) + timedelta(hours=22)

            _save_env("ANGEL_JWT", _jwt)

            _save_env("ANGEL_FEED_TOKEN", _feed_token)

            mark_success()

            logger.info("✅ JWT refreshed")

            return True

        mark_failure()

        return False

    except Exception as e:

        mark_failure()

        logger.error(
            "JWT refresh error: %s",
            e
        )

        return False

    finally:

        _REFRESH_LOCK.release()


def _is_jwt_valid():
    return _jwt and _feed_token and _jwt_expiry and datetime.now(IST) < _jwt_expiry

# ── Subscribe ─────────────────────────────────────────────────────
def _subscribe(ws_obj):
    """Send subscription for all tokens"""
    for exch_type, tokens in WATCH.items():
        msg = json.dumps({
            "action": 1,
            "params": {
                "mode": 3,  # SNAP_QUOTE: LTP + OI + Volume + Bid/Ask
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

            if parsed:
                tok = parsed["token"]

                set_tick(
                    tok,
                    parsed["ltp"],
                    parsed.get("oi"),
                    parsed.get("vol"),
                    parsed.get("bid"),
                    parsed.get("ask")
                )

                if tok in TOKEN_MAP:
                    logger.debug(
                        "TICK %s LTP=%.2f OI=%s",
                        TOKEN_MAP[tok],
                        parsed["ltp"],
                        parsed.get("oi")
                    )

        elif isinstance(msg, str):
            d = json.loads(msg)

            if "token" in d and "ltp" in d:
                set_tick(
                    d["token"],
                    d.get("ltp"),
                    d.get("oi"),
                    d.get("vol")
                )

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
            if not allow("jwt_refresh", cooldown=15):
                logger.warning("⏳ JWT refresh cooldown active")
                return False

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
        logger.info("WS AUTH client=%s feed=%s jwt=%s",
                    client_id,
                    str(feed)[:15] if feed else None,
                    str(jwt)[:20] if jwt else None)

        _ws.run_forever(
            ping_interval=25,
            ping_timeout=10,
            reconnect=5,
            sslopt={"cert_reqs": ssl.CERT_NONE},
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

    global _running, _ws_thread

    if _ws_thread and _ws_thread.is_alive():

        logger.warning(
            "⛔ WS thread already alive"
        )

        return

    if _running:

        logger.warning(
            "⛔ WS manager already running"
        )

        return

    _running = True

    logger.info(
        "WS start waiting for fresh auth tokens..."
    )

    _ws_thread = threading.Thread(
        target=_run_forever,
        daemon=True,
        name="ws-24x7"
    )

    _ws_thread.start()

    logger.info(
        "✅ WebSocket singleton started"
    )


def stop():
    global _running, _ws
    
    _running = False
    _ws_thread = None

    if _ws:
        try: _ws.close()
        except: pass

def add_token(exchange_type, token):
    if exchange_type not in WATCH: WATCH[exchange_type] = []
    if token not in WATCH[exchange_type]:
        WATCH[exchange_type].append(token)
        TOKEN_MAP[token] = token
        if _connected and _ws: _subscribe(_ws)