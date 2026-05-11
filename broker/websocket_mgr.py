# broker/websocket_mgr.py
# Chanakya AI v5.0 — WebSocket Manager
# NSE + MCX real-time LTP via SmartWebSocketV2
# Auto-reconnect + Auto-resubscribe

import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger("websocket_mgr")

# ── LTP Cache (shared with rest of system) ─────────────────────────
_ltp_cache  = {}   # {"TOKEN": price}
_ltp_lock   = threading.Lock()

# ── Subscription Registry ──────────────────────────────────────────
_subscriptions = {}  # {exchange_type: [tokens]}
_sub_lock       = threading.RLock()

# ── WebSocket State ────────────────────────────────────────────────
_ws         = None
_ws_lock    = threading.Lock()
_connected  = False
_running    = False
_thread     = None

# Angel One Exchange Type constants
NSE_CM = 1   # NSE Cash/Index
NSE_FO = 2   # NSE F&O
MCX_FO = 5   # MCX F&O

# WATCHLIST tokens — NSE F&O + MCX
# Format: {exchange_type: [token_strings]}
DEFAULT_TOKENS = {
    NSE_FO: [
        "99926000",   # NIFTY 50
        "99926009",   # BANKNIFTY
        "99926074",   # FINNIFTY
    ],
    MCX_FO: [
        "234230",     # CRUDEOIL
        "234235",     # NATURALGAS
    ],
}


# ── LTP Access ────────────────────────────────────────────────────
def get_ltp(token):
    """Token चा latest LTP return करतो"""
    with _ltp_lock:
        return _ltp_cache.get(str(token))

def get_all_ltp():
    """सगळे cached LTP return करतो"""
    with _ltp_lock:
        return dict(_ltp_cache)

def set_ltp(token, price):
    """Manual LTP set (REST API fallback साठी)"""
    with _ltp_lock:
        _ltp_cache[str(token)] = price


# ── WebSocket Callbacks ───────────────────────────────────────────
def _on_data(wsapp, data):
    """Real-time tick data येतो इथे"""
    try:
        token = str(data.get("token", ""))
        ltp   = data.get("last_traded_price", 0)
        if token and ltp:
            # Angel One LTP is in paise — convert to rupees
            price = ltp / 100.0
            with _ltp_lock:
                _ltp_cache[token] = price

            # Event bus ला publish करा
            try:
                from core.event_bus import publish
                publish("ltp_update", {"token": token, "ltp": price})
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"on_data error: {e}")


def _on_open(wsapp):
    global _connected
    _connected = True
    logger.info("✅ WebSocket connected!")

    # सगळे subscriptions restore करा
    _resubscribe_all()


def _on_error(wsapp, error):
    global _connected
    _connected = False
    logger.error(f"🔴 WebSocket error: {error}")


def _on_close(wsapp, *args):
    global _connected
    _connected = False
    close_status_code = args[0] if len(args)>0 else None
    close_msg = args[1] if len(args)>1 else None
    logger.warning(f"🟡 WebSocket closed: {close_status_code} {close_msg}")

    # Auto-reconnect — thread मध्ये करा (deadlock avoid)
    if _running:
        logger.info("🔄 WebSocket auto-reconnect scheduled...")
        t = threading.Thread(target=_reconnect, daemon=True, name="WSReconnect")
        t.start()


# ── Subscribe / Unsubscribe ───────────────────────────────────────
def _resubscribe_all():
    """Reconnect नंतर सगळे tokens परत subscribe करा"""
    global _ws
    with _sub_lock:
        if not _subscriptions:
            # Default tokens subscribe करा
            _subscriptions.update(DEFAULT_TOKENS)

        token_list = [
            {"exchangeType": exch, "tokens": tokens}
            for exch, tokens in _subscriptions.items()
            if tokens
        ]

    if not token_list:
        return

    try:
        with _ws_lock:
            if _ws:
                _ws.subscribe(
                    correlation_id = "chanakya01",
                    mode           = 1,  # LTP mode
                    token_list     = token_list,
                )
                logger.info(f"✅ Resubscribed {sum(len(v) for v in _subscriptions.values())} tokens")
    except Exception as e:
        logger.error(f"Resubscribe error: {e}")


def subscribe_tokens(exchange_type, tokens):
    """
    नवीन tokens subscribe करा.
    exchange_type: NSE_CM=1, NSE_FO=2, MCX_FO=5
    tokens: list of string token IDs
    """
    with _sub_lock:
        if exchange_type not in _subscriptions:
            _subscriptions[exchange_type] = []
        for t in tokens:
            if t not in _subscriptions[exchange_type]:
                _subscriptions[exchange_type].append(t)

    if not _connected:
        return

    try:
        with _ws_lock:
            if _ws:
                _ws.subscribe(
                    correlation_id = "chanakya01",
                    mode           = 1,
                    token_list     = [{"exchangeType": exchange_type, "tokens": tokens}],
                )
                logger.info(f"✅ Subscribed {tokens} on exchange {exchange_type}")
    except Exception as e:
        logger.error(f"Subscribe error: {e}")


# ── Connect / Reconnect ───────────────────────────────────────────
def _create_ws():
    """SmartWebSocketV2 instance तयार करा"""
    try:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        from broker.auth_manager import get_auth

        auth   = get_auth()
        status = auth.status()

        if not status.get("connected"):
            logger.error("Auth not connected — cannot create WebSocket")
            return None

        api    = auth.get_api()

        # feed_token — auth status मधून fetch करा
        feed_token = ""
        try:
            feed_token = status.get("feed_token", "") or getattr(api, "feed_token", "") or ""
        except Exception:
            pass

        ws = SmartWebSocketV2(
            auth_token        = api.access_token,
            api_key           = api.api_key,
            client_code       = status.get("client_id", ""),
            feed_token        = feed_token,
            max_retry_attempt = 3,
        )

        # Callbacks bind करा
        ws.on_open  = _on_open
        ws.on_data  = _on_data
        ws.on_error = _on_error
        ws.on_close = _on_close

        return ws
    except Exception as e:
        logger.error(f"WebSocket create error: {e}")
        return None


def _reconnect():
    """WebSocket reconnect करा"""
    global _ws, _connected

    if not _running:
        return

    logger.info("🔄 Reconnecting WebSocket...")
    with _ws_lock:
        try:
            if _ws:
                try:
                    _ws.close_connection()
                except Exception:
                    pass
            _ws = None
            _connected = False
        except Exception:
            pass

    time.sleep(2)
    # Thread मध्ये start करा — blocking call आहे
    t = threading.Thread(target=_start_ws, daemon=True, name="WSRestart")
    t.start()


def _start_ws():
    """WebSocket start करा background thread मध्ये — Loop based (no recursion)"""
    global _ws

    retry = 0
    while _running:
        ws = _create_ws()
        if not ws:
            retry += 1
            wait = min(30 * retry, 120)  # max 2 min wait
            logger.error(f"❌ WebSocket creation failed — retry {retry} in {wait}s")
            time.sleep(wait)
            continue

        with _ws_lock:
            _ws = ws

        try:
            logger.info("🔌 Starting WebSocket connection...")
            _ws.connect()  # Blocking — runs until disconnect
        except Exception as e:
            logger.error(f"WebSocket connect error: {e}")

        if _running:
            logger.info("🔄 WebSocket disconnected — reconnecting in 5s...")
            time.sleep(5)
        retry = 0  # Reset retry count on successful connect


# ── Heartbeat Monitor ─────────────────────────────────────────────
def _is_market_hours():
    """Market hours आहे का — Weekend skip"""
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return 9 <= now.hour < 24

def _heartbeat_monitor():
    """दर 30 sec WebSocket alive आहे का check करतो"""
    while _running:
        time.sleep(30)
        try:
            if not _connected and _running:
                if _is_market_hours():
                    logger.warning("💔 Heartbeat: WebSocket dead — reconnecting...")
                    _reconnect()
                else:
                    logger.debug("💤 Market closed — skip reconnect")
            else:
                logger.debug(f"💓 Heartbeat OK | LTP cache: {len(_ltp_cache)} tokens")
        except Exception as e:
            logger.debug(f"Heartbeat error: {e}")

# ── Public API ────────────────────────────────────────────────────
def start():
    """WebSocket Manager start करा"""
    global _running, _thread

    if _running:
        logger.warning("WebSocket manager already running")
        return

    _running = True
    logger.info("🚀 WebSocket Manager starting...")

    # Main WS thread
    _thread = threading.Thread(target=_start_ws, daemon=True, name="WSManager")
    _thread.start()

    # Heartbeat thread
    hb = threading.Thread(target=_heartbeat_monitor, daemon=True, name="WSHeartbeat")
    hb.start()

    logger.info("✅ WebSocket Manager started (NSE_FO + MCX_FO)")


def stop():
    """WebSocket Manager stop करा"""
    global _running, _connected, _ws

    _running   = False
    _connected = False

    with _ws_lock:
        if _ws:
            try:
                _ws.close_connection()
            except Exception:
                pass
            _ws = None

    logger.info("🛑 WebSocket Manager stopped")


def status():
    """Current status return करा"""
    return {
        "connected":     _connected,
        "running":       _running,
        "ltp_count":     len(_ltp_cache),
        "subscriptions": {k: len(v) for k, v in _subscriptions.items()},
        "cached_tokens": list(_ltp_cache.keys()),
    }
