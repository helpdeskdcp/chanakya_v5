"""
Chanakya Data Manager™ — DB-driven Dynamic Symbol Registry
"""
import time, logging, threading, sqlite3
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
DB_PATH = "/root/chanakya_v5/data/chanakya_v5.db"

class DataManager:
    def __init__(self):
        self._cache = {}
        self._ltp_cache = {}
        self._lock = threading.Lock()
        self._broker = None
        self._connected = False
        self._last_connect = 0
        self._symbols_loaded = 0
        self.CANDLE_TTL = 60
        self.LTP_TTL = 5
        self.SYMBOLS = {}
        self._load_symbols()

    def _load_symbols(self):
        """Load symbols from DB — called on init + after add/delete"""
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute("""
                SELECT symbol,token,exchange,instrument_type,
                       lot_size,tick_size,strike_interval,min_sl_pct,
                       has_options,option_exchange
                FROM trading_symbols WHERE is_active=1
            """).fetchall()
            conn.close()
            syms = {}
            for r in rows:
                syms[r[0]] = {
                    "token": r[1], "exchange": r[2],
                    "type": r[3], "lot": r[4],
                    "tick": r[5], "interval": r[6],
                    "min_sl": r[7], "has_options": bool(r[8]),
                    "opt_exchange": r[9]
                }
            self.SYMBOLS = syms
            self._symbols_loaded = time.time()
            logger.info("DataManager: loaded %d symbols from DB", len(syms))
        except Exception as e:
            logger.error("DataManager._load_symbols: %s", e)

    def reload_symbols(self):
        """Force reload from DB"""
        self._load_symbols()
        return len(self.SYMBOLS)

    def _get_broker(self):
        try:
            from broker.global_broker import get_broker
            b = get_broker()
            if not b.is_connected():
                time.sleep(5)
                logger.info("DataManager: using shared broker reconnect")
                b.ensure_connected()
            self._broker = b
            self._connected = b.is_connected()
        except Exception as e:
            logger.error("DataManager broker: %s", e)
        return self._broker

    def get_candles(self, symbol, timeframe="FIVE_MINUTE", days=2, force=False):
        key = f"{symbol}_{timeframe}_{days}"
        now = time.time()
        with self._lock:
            if not force and key in self._cache:
                if now - self._cache[key]["ts"] < self.CANDLE_TTL:
                    return self._cache[key]["data"]
        sym = self.SYMBOLS.get(symbol)
        if not sym: return []
        broker = self._get_broker()
        if not broker:
            with self._lock:
                return self._cache.get(key, {}).get("data", [])
        try:
            raw = broker.get_candles(sym["token"], sym["exchange"], timeframe, days)
            if not raw: raise Exception("empty")
            candles = [{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),
                        "c":float(x[4]),"v":float(x[5]) if len(x)>5 else 0,
                        "t":x[0]} for x in raw]
            with self._lock:
                self._cache[key] = {"data": candles, "ts": now}
            self._connected = True
            return candles
        except Exception as e:
            logger.warning("get_candles %s: %s", symbol, e)
            self._connected = False
            with self._lock:
                return self._cache.get(key, {}).get("data", [])

    def get_ltp(self, symbol):
        now = time.time()
        with self._lock:
            if symbol in self._ltp_cache:
                if now - self._ltp_cache[symbol]["ts"] < self.LTP_TTL:
                    return self._ltp_cache[symbol]["ltp"]
        sym = self.SYMBOLS.get(symbol)
        if not sym: return 0
        broker = self._get_broker()
        if not broker: return 0
        try:
            ltp = broker.get_ltp(sym["exchange"], symbol, sym["token"])
            if ltp:
                with self._lock:
                    self._ltp_cache[symbol] = {"ltp": ltp, "ts": now}
            return ltp or 0
        except:
            with self._lock:
                return self._ltp_cache.get(symbol, {}).get("ltp", 0)

    def get_market_snapshot(self):
        snap = {}
        for sym in ["NIFTY","BANKNIFTY","CRUDEOIL","NATURALGAS","FINNIFTY","GOLD"]:
            ltp = self.get_ltp(sym)
            if ltp: snap[sym] = ltp
        return snap

    def is_market_open(self, market="NSE"):
        now = datetime.now(IST)
        h, m = now.hour, now.minute
        if market == "NSE":
            return (h==9 and m>=15) or (10<=h<=14) or (h==15 and m<=30)
        elif market == "MCX":
            return (h>=9) and (h<23 or (h==23 and m<=30))
        return False

    def get_symbols_by_type(self, sym_type=None, exchange=None):
        result = []
        for sym, info in self.SYMBOLS.items():
            if sym_type and info["type"] != sym_type: continue
            if exchange and info["exchange"] != exchange: continue
            result.append({"symbol": sym, **info})
        return result

    def warm_cache(self):
        logger.info("DataManager: warming cache...")
        count = 0
        for sym, info in self.SYMBOLS.items():
            if info["type"] == "equity": continue
            candles = self.get_candles(sym)
            if candles: count += 1
            time.sleep(0.4)
        logger.info("DataManager: warmed %d symbols", count)
        return count

_dm = None
def get_data_manager():
    global _dm
    if not _dm: _dm = DataManager()
    return _dm
