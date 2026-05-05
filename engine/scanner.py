import os, logging, sys
sys.path.insert(0,'/root/chanakya_v5')
logger = logging.getLogger(__name__)

WATCHLIST = [
    {"symbol":"NIFTY",      "token":"99926000","exchange":"NSE","type":"index"},
    {"symbol":"BANKNIFTY",  "token":"99926009","exchange":"NSE","type":"index"},
    {"symbol":"FINNIFTY",   "token":"99926037","exchange":"NSE","type":"index"},
    {"symbol":"CRUDEOIL",   "token":"488290",  "exchange":"MCX","type":"commodity"},
    {"symbol":"NATURALGAS", "token":"488505",  "exchange":"MCX","type":"commodity"},
    {"symbol":"GOLD",       "token":"67694",   "exchange":"MCX","type":"commodity"},
    {"symbol":"RELIANCE",   "token":"2885",    "exchange":"NSE","type":"equity"},
    {"symbol":"TCS",        "token":"11536",   "exchange":"NSE","type":"equity"},
    {"symbol":"INFY",       "token":"1594",    "exchange":"NSE","type":"equity"},
    {"symbol":"WIPRO",      "token":"3787",    "exchange":"NSE","type":"equity"},
    {"symbol":"HDFCBANK",   "token":"1333",    "exchange":"NSE","type":"equity"},
    {"symbol":"ICICIBANK",  "token":"4963",    "exchange":"NSE","type":"equity"},
    {"symbol":"SBIN",       "token":"3045",    "exchange":"NSE","type":"equity"},
    {"symbol":"TATASTEEL",  "token":"3499",    "exchange":"NSE","type":"equity"},
    {"symbol":"SUZLON",     "token":"12018",   "exchange":"NSE","type":"equity"},
    {"symbol":"YESBANK",    "token":"11915",   "exchange":"NSE","type":"equity"},
]

def _analyze(candles, symbol):
    try:
        from engine.indicators import ema, rsi, macd, vwap, atr, supertrend
        if len(candles) < 10: return None
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        ltp    = closes[-1]
        r      = rsi(closes)
        e9     = ema(closes,9); e21 = ema(closes,21)
        m,mh   = macd(closes)
        vw     = vwap(candles[-50:] if len(candles)>=50 else candles)
        at     = atr(candles)
        st     = supertrend(candles)
        vol_avg = sum(vols)/len(vols)
        vol_ratio = round(vols[-1]/vol_avg,2) if vol_avg>0 else 1
        # Direction first — then score direction-aware
        direction = "BUY" if e9>e21 and r<70 else "SELL"
        # Score aligned to direction
        score = 0
        if direction=="BUY":
            if e9>e21: score+=25
            if 40<r<70: score+=20
            if mh>0: score+=15
            if ltp>vw: score+=20
            if vol_ratio>=1.2: score+=10
            if st=="UP": score+=10
        else:  # SELL
            if e9<e21: score+=25
            if 30<r<60: score+=20
            if mh<0: score+=15
            if ltp<vw: score+=20
            if vol_ratio>=1.2: score+=10
            if st=="DOWN": score+=10
        sl = round(ltp-1.5*at,1) if direction=="BUY" else round(ltp+1.5*at,1)
        target = round(ltp+3*at,1) if direction=="BUY" else round(ltp-3*at,1)
        rr = round(abs(target-ltp)/abs(ltp-sl),1) if ltp!=sl else 0
        # Fake filter
        fake = []
        if vol_ratio<0.5: fake.append("LowVol")
        if abs(mh)<0.001: fake.append("WeakMACD")
        return {"symbol":symbol,"ltp":ltp,"direction":direction,
                "entry":ltp,"sl":sl,"target":target,"rr":rr,
                "score":score,"rsi":r,"vwap":vw,"vwap_bias":"ABOVE" if ltp>vw else "BELOW",
                "ema_cross":"BULL" if e9>e21 else "BEAR",
                "vol_ratio":vol_ratio,"fake":fake,"atr":at}
    except Exception as e:
        logger.debug(f"analyze {symbol}: {e}"); return None


def is_market_open():
    """NSE: Mon-Fri 9:15-15:30, MCX: Mon-Fri 9:00-23:30"""
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1530  # NSE hours

def scan_all(broker=None):
    try:
        if not is_market_open():
            logger.info("Market closed — skipping scan")
            return []

        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        if not broker or not broker.is_connected():
            logger.warning("Broker not connected for scan")
            return []
        from data_stream.cache import get as cget, set as cset
        signals = []
        for stock in WATCHLIST:
            try:
                ckey = f"candles_{stock['symbol']}_5m"
                candles = cget(ckey)
                if not candles:
                    candles = broker.get_candles(stock["token"], stock["exchange"], "FIVE_MINUTE", days=2)
                    if candles: cset(ckey, candles, ttl=60)
                if not candles or len(candles)<10: continue
                sig = _analyze(candles, stock["symbol"])
                if not sig: continue
                sig["exchange"] = stock["exchange"]
                sig["type"] = stock["type"]
                sig["token"] = stock["token"]
                if sig["score"] >= 50 and not sig["fake"]:
                    signals.append(sig)
            except Exception as e:
                logger.debug(f"scan {stock['symbol']}: {e}")
        signals.sort(key=lambda x: -x["score"])
        logger.info(f"Scan done: {len(signals)} signals")
        return signals
    except Exception as e:
        logger.error(f"scan_all: {e}"); return []

def get_live_ltps(broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        from data_stream.cache import get as cget, set as cset
        ltps = {}
        for stock in WATCHLIST[:6]:
            ckey = f"ltp_{stock['symbol']}"
            ltp = cget(ckey)
            if not ltp:
                ltp = broker.get_ltp(stock["exchange"], stock["symbol"], stock["token"])
                if ltp: cset(ckey, ltp, ttl=5)
            if ltp: ltps[stock["symbol"]] = ltp
        return ltps
    except Exception as e:
        logger.error(f"get_ltps: {e}"); return {}
