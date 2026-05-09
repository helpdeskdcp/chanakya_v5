import os,time,logging,threading
import pyotp
logger=logging.getLogger(__name__)

class AuthManager:
    SESSION_TTL=7*3600
    MAX_RETRIES=5
    BACKOFF_BASE=2

    def __init__(self):
        self._feed_token = ""
        self._lock=threading.Lock()
        self._api=None
        self._connected=False
        self._session_start=0
        self._retry_count=0
        self._last_attempt=0
        self._min_interval=60
        from dotenv import load_dotenv
        load_dotenv("/root/chanakya_v5/.env")
        self.api_key=os.getenv("ANGEL_API_KEY","")
        self.client_id=os.getenv("ANGEL_CLIENT_ID","")
        self.password=os.getenv("ANGEL_PASSWORD","")
        self.totp_key=os.getenv("ANGEL_TOTP_KEY","")

    def connect(self):
        with self._lock: return self._do_connect()

    def ensure_connected(self):
        with self._lock:
            if self._connected and not self._expired(): return True
            if time.time()-self._last_attempt < self._min_interval: return self._connected
            return self._do_connect()

    def get_api(self): return self._api if self._connected else None
    def is_connected(self): return self._connected and not self._expired()
    def _expired(self): return (time.time()-self._session_start)>self.SESSION_TTL

    def _do_connect(self):
        self._last_attempt=time.time()
        backoff=self.BACKOFF_BASE
        for attempt in range(1,self.MAX_RETRIES+1):
            try:
                from SmartApi import SmartConnect
                from broker.rate_limiter import acquire
                if not acquire(timeout=15):
                    logger.warning("AuthManager: rate limit timeout")
                    return False
                self._api=SmartConnect(api_key=self.api_key)
                totp=pyotp.TOTP(self.totp_key).now()
                r=self._api.generateSession(self.client_id,self.password,totp)
                if r and r.get("status"):
                    self._connected=True
                    self._session_start=time.time()
                    self._retry_count=0
                    # feed_token save करा — WebSocket साठी
                    self._feed_token = r.get("data", {}).get("feedToken", "")
                    if self._feed_token:
                        self._api.feed_token = self._feed_token
                    logger.info(f"AuthManager: connected [{self.client_id}] attempt={attempt} feed={'✅' if self._feed_token else '❌'}")
                    try:
                        from core.event_bus import publish,BROKER_CONNECTED
                        publish(BROKER_CONNECTED,{"client_id":self.client_id})
                    except: pass
                    return True
                logger.warning(f"AuthManager: attempt={attempt} failed: {r}")
            except Exception as e:
                logger.error(f"AuthManager: attempt={attempt} error: {e}")
            if attempt<self.MAX_RETRIES:
                logger.info(f"AuthManager: retry in {backoff}s...")
                time.sleep(backoff)
                backoff=min(backoff*2,60)
        self._connected=False
        self._retry_count+=1
        logger.error("AuthManager: all attempts failed")
        try:
            from core.event_bus import publish,BROKER_DISCONNECTED
            publish(BROKER_DISCONNECTED,{"reason":"auth_failed"})
        except: pass
        return False

    def status(self):
        age=int(time.time()-self._session_start) if self._connected else 0
        return {"connected":self._connected,"session_age_s":age,
                "session_ttl_s":max(0,self.SESSION_TTL-age),"retry_count":self._retry_count,
                "feed_token": getattr(self,"_feed_token",""),
                "client_id":  self.client_id}

_auth=None
_auth_lock=threading.Lock()

def get_auth():
    global _auth
    with _auth_lock:
        if _auth is None: _auth=AuthManager()
        return _auth
