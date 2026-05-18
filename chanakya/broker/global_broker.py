import logging,time,threading
logger=logging.getLogger(__name__)

class GlobalBroker:
    def __init__(self):
        from broker.auth_manager import get_auth
        self._auth=get_auth()

    def connect(self): return self._auth.connect()
    def is_connected(self): return self._auth.is_connected()
    def ensure_connected(self): return self._auth.ensure_connected()
    def _api(self): return self._auth.get_api()

    def get_ltp(self,exchange,symbol,token):
        # ── WebSocket cache first (zero API calls) ──────
        try:
            from broker.websocket_mgr import get_ltp as ws_ltp
            cached = ws_ltp(str(token))
            if cached and cached > 0:
                try:
                    from core.shared_state import get,set as ss
                    c=get("ltp_cache") or {}
                    c[symbol]={"ltp":cached,"ts":time.time(),"src":"ws"}; ss("ltp_cache",c)
                except: pass
                return cached
        except Exception: pass

        # ── REST API fallback (WebSocket नसेल तर) ───────
        try:
            from broker.rate_limiter import acquire
            if not acquire(5): return None
            api=self._api()
            if not api: return None
            r=api.ltpData(exchange,symbol,str(token))
            if r and r.get("data"):
                ltp=float(r["data"]["ltp"])
                try:
                    from broker.websocket_mgr import set_ltp
                    set_ltp(str(token), ltp)  # Cache मध्ये save करा
                except: pass
                try:
                    from core.shared_state import get,set as ss
                    c=get("ltp_cache") or {}
                    c[symbol]={"ltp":ltp,"ts":time.time(),"src":"rest"}; ss("ltp_cache",c)
                except: pass
                return ltp
        except Exception as e: logger.debug(f"get_ltp [{symbol}]: {e}")
        return None

    def get_candles(self,token,exchange,interval,days=2):
        try:
            from broker.rate_limiter import acquire
            if not acquire(5): return []
            api=self._api()
            if not api: return []
            from datetime import datetime,timedelta
            import pytz
            IST=pytz.timezone("Asia/Kolkata")
            now=datetime.now(IST)
            r=api.getCandleData({
                "exchange":exchange,"symboltoken":str(token),"interval":interval,
                "fromdate":(now-timedelta(days=days)).strftime("%Y-%m-%d 09:00"),
                "todate":now.strftime("%Y-%m-%d %H:%M"),
            })
            if r and r.get("data"): return r["data"]
        except Exception as e: logger.debug(f"get_candles [{token}]: {e}")
        return []

    def place_order(self,symbol,exchange,token,direction,qty,
                    order_type="MARKET",product="INTRADAY"):
        try:
            from broker.rate_limiter import acquire
            if not acquire(10): return None
            api=self._api()
            if not api: logger.error("place_order: not connected"); return None
            r=api.placeOrder({
                "variety":"NORMAL","tradingsymbol":symbol,"symboltoken":str(token),
                "transactiontype":direction,"exchange":exchange,
                "ordertype":order_type,"producttype":product,
                "duration":"DAY","quantity":str(qty),
            })
            if r and r.get("data",{}).get("orderid"):
                oid=r["data"]["orderid"]
                logger.info(f"Order: {direction} {symbol} qty={qty} → {oid}")
                try:
                    from core.event_bus import publish,TRADE_OPENED
                    publish(TRADE_OPENED,{"symbol":symbol,"direction":direction,"qty":qty,"order_id":oid,"mode":"LIVE"})
                except: pass
                return oid
            logger.error(f"place_order failed: {r}"); return None
        except Exception as e: logger.error(f"place_order: {e}"); return None

    def status(self):
        from broker.rate_limiter import stats
        return {**self._auth.status(),"rate_limiter":stats()}

_inst=None
_lock=threading.Lock()

def get_broker():
    global _inst
    with _lock:
        if _inst is None: _inst=GlobalBroker(); _inst.connect()
    return _inst

def get_ltp(exchange,symbol,token): return get_broker().get_ltp(exchange,symbol,token)
def get_candles(token,exchange,interval,days=2): return get_broker().get_candles(token,exchange,interval,days)
def is_connected(): return get_broker().is_connected()
