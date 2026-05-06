"""
Chanakya Data Manager™ — Stable, Cached Market Data
Single source of truth for ALL modules
"""
import time, logging, threading
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

class DataManager:
    def __init__(self):
        self._cache = {}        # {key: {"data":[], "ts":0}}
        self._ltp_cache = {}    # {symbol: {"ltp":0, "ts":0}}
        self._lock = threading.Lock()
        self._broker = None
        self._connected = False
        self._last_connect_attempt = 0
        self.CANDLE_TTL = 60    # 60 sec cache for candles
        self.LTP_TTL = 5        # 5 sec cache for LTP

        # Symbol registry — single source
        self.SYMBOLS = {
            # NSE Index
            "NIFTY":     {"token":"99926000","exchange":"NSE","lot":65, "interval":50, "type":"index","min_sl":0.004},
            "BANKNIFTY": {"token":"99926009","exchange":"NSE","lot":30, "interval":100,"type":"index","min_sl":0.004},
            "FINNIFTY":  {"token":"99926037","exchange":"NSE","lot":65, "interval":50, "type":"index","min_sl":0.004},
            # MCX Commodity
            "CRUDEOIL":   {"token":"488290","exchange":"MCX","lot":100, "interval":50, "type":"commodity","min_sl":0.006},
            "NATURALGAS": {"token":"488505","exchange":"MCX","lot":1250,"interval":10, "type":"commodity","min_sl":0.008},
            "GOLD":       {"token":"67694", "exchange":"MCX","lot":100, "interval":100,"type":"commodity","min_sl":0.005},
            # NSE Equity
            "RELIANCE":  {"token":"2885", "exchange":"NSE","lot":1,"interval":5,"type":"equity","min_sl":0.008},
            "HDFCBANK":  {"token":"1333", "exchange":"NSE","lot":1,"interval":5,"type":"equity","min_sl":0.008},
            "ICICIBANK": {"token":"4963", "exchange":"NSE","lot":1,"interval":5,"type":"equity","min_sl":0.008},
            "SBIN":      {"token":"3045", "exchange":"NSE","lot":1,"interval":5,"type":"equity","min_sl":0.008},
            "TCS":       {"token":"11536","exchange":"NSE","lot":1,"interval":5,"type":"equity","min_sl":0.008},
        }

    def _get_broker(self):
        """Get connected broker — auto reconnect"""
        now = time.time()
        # Don't reconnect more than once per 30 sec
        if self._broker and self._connected:
            return self._broker
        if now - self._last_connect_attempt < 30:
            return self._broker
        try:
            self._last_connect_attempt = now
            from broker.global_broker import get_broker
            b = get_broker()
            if not b.is_connected():
                logger.info("DataManager: Reconnecting broker...")
                b.connect()
            if b.is_connected():
                self._broker = b
                self._connected = True
                logger.info("DataManager: Broker connected")
            else:
                self._connected = False
        except Exception as e:
            logger.error("DataManager broker error: %s", e)
            self._connected = False
        return self._broker

    def get_candles(self, symbol, timeframe="FIVE_MINUTE", days=2, force=False):
        """
        Get cached candles for symbol
        Returns list of dicts {o,h,l,c,v}
        """
        cache_key = f"{symbol}_{timeframe}_{days}"
        now = time.time()

        # Check cache first
        with self._lock:
            if not force and cache_key in self._cache:
                entry = self._cache[cache_key]
                if now - entry["ts"] < self.CANDLE_TTL:
                    return entry["data"]

        # Fetch from broker
        sym_info = self.SYMBOLS.get(symbol)
        if not sym_info:
            logger.warning("Unknown symbol: %s", symbol)
            return []

        broker = self._get_broker()
        if not broker:
            # Return cached even if stale
            with self._lock:
                if cache_key in self._cache:
                    return self._cache[cache_key]["data"]
            return []

        try:
            raw = broker.get_candles(sym_info["token"], sym_info["exchange"],
                                     timeframe, days)
            if not raw:
                raise Exception("Empty candles")
            candles = [{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),
                        "c":float(x[4]),"v":float(x[5]) if len(x)>5 else 0,
                        "t":x[0]} for x in raw]
            with self._lock:
                self._cache[cache_key] = {"data": candles, "ts": now}
            self._connected = True
            return candles
        except Exception as e:
            logger.warning("DataManager.get_candles %s: %s", symbol, e)
            self._connected = False
            # Return stale cache
            with self._lock:
                if cache_key in self._cache:
                    logger.info("Using stale cache for %s", symbol)
                    return self._cache[cache_key]["data"]
            return []

    def get_ltp(self, symbol):
        """Get cached LTP"""
        now = time.time()
        with self._lock:
            if symbol in self._ltp_cache:
                entry = self._ltp_cache[symbol]
                if now - entry["ts"] < self.LTP_TTL:
                    return entry["ltp"]

        sym_info = self.SYMBOLS.get(symbol)
        if not sym_info: return 0

        broker = self._get_broker()
        if not broker: return 0

        try:
            ltp = broker.get_ltp(sym_info["exchange"], symbol, sym_info["token"])
            if ltp:
                with self._lock:
                    self._ltp_cache[symbol] = {"ltp": ltp, "ts": now}
            return ltp or 0
        except Exception as e:
            with self._lock:
                if symbol in self._ltp_cache:
                    return self._ltp_cache[symbol]["ltp"]
            return 0

    def get_market_snapshot(self):
        """Quick market LTP for all symbols"""
        snapshot = {}
        for sym in ["NIFTY","BANKNIFTY","CRUDEOIL","NATURALGAS","FINNIFTY"]:
            ltp = self.get_ltp(sym)
            if ltp: snapshot[sym] = ltp
        return snapshot

    def is_market_open(self, market_type="NSE"):
        """Check if market is open"""
        now = datetime.now(IST)
        h, m = now.hour, now.minute
        if market_type == "NSE":
            return (h==9 and m>=15) or (10<=h<=14) or (h==15 and m<=30)
        elif market_type == "MCX":
            return (h>=9) and (h<23 or (h==23 and m<=30))
        return False

    def warm_cache(self):
        """Pre-warm cache for all symbols"""
        logger.info("DataManager: Warming cache...")
        count = 0
        for sym, info in self.SYMBOLS.items():
            if info["type"] == "equity": continue
            candles = self.get_candles(sym)
            if candles:
                count += 1
                logger.info("Cached %s: %d candles", sym, len(candles))
            time.sleep(0.5)
        logger.info("DataManager: Cache warmed — %d symbols", count)
        return count

# Global singleton
_dm = None
def get_data_manager():
    global _dm
    if not _dm:
        _dm = DataManager()
    return _dm
