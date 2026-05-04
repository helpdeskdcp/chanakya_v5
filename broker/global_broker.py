import os, logging, time, pyotp
logger = logging.getLogger(__name__)

_broker = None

class GlobalBroker:
    def __init__(self):
        self.api = None
        self.connected = False
        self.api_key   = os.getenv("ANGEL_API_KEY","")
        self.client_id = os.getenv("ANGEL_CLIENT_ID","")
        self.password  = os.getenv("ANGEL_PASSWORD","")
        self.totp_key  = os.getenv("ANGEL_TOTP_KEY","")

    def connect(self):
        try:
            from SmartApi import SmartConnect
            self.api = SmartConnect(api_key=self.api_key)
            totp = pyotp.TOTP(self.totp_key).now()
            r = self.api.generateSession(self.client_id, self.password, totp)
            if r and r.get("status"):
                self.connected = True
                logger.info(f"Broker connected: {self.client_id}")
                return True
            logger.error(f"Broker failed: {r}")
            return False
        except Exception as e:
            logger.error(f"Broker connect: {e}")
            self.connected = False
            return False

    def get_ltp(self, exchange, symbol, token):
        try:
            if not self.connected: return None
            r = self.api.ltpData(exchange, symbol, str(token))
            if r and r.get("data"):
                return float(r["data"]["ltp"])
        except Exception as e:
            logger.debug(f"LTP {symbol}: {e}")
        return None

    def get_candles(self, token, exchange, interval, days=2):
        try:
            if not self.connected: return []
            from datetime import datetime, timedelta
            import pytz
            IST = pytz.timezone("Asia/Kolkata")
            now = datetime.now(IST)
            r = self.api.getCandleData({
                "exchange": exchange,
                "symboltoken": str(token),
                "interval": interval,
                "fromdate": (now-timedelta(days=days)).strftime("%Y-%m-%d 09:00"),
                "todate": now.strftime("%Y-%m-%d %H:%M"),
            })
            if r and r.get("data"):
                return r["data"]
        except Exception as e:
            logger.debug(f"Candles {token}: {e}")
        return []

    def is_connected(self):
        return self.connected

def get_broker():
    global _broker
    if _broker is None:
        from dotenv import load_dotenv
        load_dotenv("/root/chanakya_v5/.env")
        _broker = GlobalBroker()
    if not _broker.connected:
        try: _broker.connect()
        except: pass
    return _broker

def get_ltp(exchange, symbol, token):
    try: return get_broker().get_ltp(exchange, symbol, token)
    except: return None

def get_candles(token, exchange, interval, days=2):
    try: return get_broker().get_candles(token, exchange, interval, days)
    except: return []

def is_connected():
    try: return get_broker().is_connected()
    except: return False
