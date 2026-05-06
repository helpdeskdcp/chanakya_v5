import os, logging, sys
sys.path.insert(0,'/root/chanakya_v5')
logger = logging.getLogger(__name__)

# ═══ NSE INDEX F&O ═══ (Weekly options, high liquidity)
NSE_INDEX = [
    {"symbol":"NIFTY",     "token":"99926000","exchange":"NSE","type":"index",
     "lot":65, "interval":50, "min_sl_pct":0.004, "option_type":"weekly"},
    {"symbol":"BANKNIFTY", "token":"99926009","exchange":"NSE","type":"index",
     "lot":30, "interval":100,"min_sl_pct":0.004, "option_type":"weekly"},
    {"symbol":"FINNIFTY",  "token":"99926037","exchange":"NSE","type":"index",
     "lot":65, "interval":50, "min_sl_pct":0.004, "option_type":"weekly"},
]

# ═══ MCX COMMODITY F&O ═══ (Monthly options, 9AM-11:30PM)
MCX_COMMODITY = [
    {"symbol":"CRUDEOIL",   "token":"488290","exchange":"MCX","type":"commodity",
     "lot":100, "interval":50,"min_sl_pct":0.006,"option_type":"monthly"},
    {"symbol":"NATURALGAS", "token":"488505","exchange":"MCX","type":"commodity",
     "lot":1250,"interval":10,"min_sl_pct":0.008,"option_type":"monthly"},
    {"symbol":"GOLD",       "token":"67694", "exchange":"MCX","type":"commodity",
     "lot":100, "interval":100,"min_sl_pct":0.005,"option_type":"monthly"},
]

# ═══ NSE EQUITY ═══ (Direct stock — no F&O, different SL logic)
NSE_EQUITY = [
    {"symbol":"RELIANCE",  "token":"2885", "exchange":"NSE","type":"equity","lot":1,"min_sl_pct":0.008},
    {"symbol":"TCS",       "token":"11536","exchange":"NSE","type":"equity","lot":1,"min_sl_pct":0.008},
    {"symbol":"INFY",      "token":"1594", "exchange":"NSE","type":"equity","lot":1,"min_sl_pct":0.008},
    {"symbol":"HDFCBANK",  "token":"1333", "exchange":"NSE","type":"equity","lot":1,"min_sl_pct":0.008},
    {"symbol":"ICICIBANK", "token":"4963", "exchange":"NSE","type":"equity","lot":1,"min_sl_pct":0.008},
    {"symbol":"SBIN",      "token":"3045", "exchange":"NSE","type":"equity","lot":1,"min_sl_pct":0.008},
]

# Auto-trader only uses INDEX + MCX (NOT equity for F&O signals)
WATCHLIST = NSE_INDEX + MCX_COMMODITY  # Equity separate module madhe

def _analyze(candles, symbol):
    try:
        from engine.indicators import ema, rsi, macd, vwap, atr, supertrend
        from engine.smart_money import smc_score, market_structure, detect_bos, volume_profile
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

        # Direction first
        direction = "BUY" if e9>e21 and r<70 else "SELL"

        # Classic score (max 100)
        score = 0
        if direction=="BUY":
            if e9>e21: score+=25
            if 40<r<70: score+=20
            if mh>0: score+=15
            if ltp>vw: score+=20
            if vol_ratio>=1.2: score+=10
            if st=="UP": score+=10
        else:
            if e9<e21: score+=25
            if 30<r<60: score+=20
            if mh<0: score+=15
            if ltp<vw: score+=20
            if vol_ratio>=1.2: score+=10
            if st=="DOWN": score+=10

        # Smart Money Score (max 100)
        smc, smc_details = smc_score(candles, direction)
        ms  = smc_details.get("structure","UNKNOWN")
        bos = smc_details.get("bos","NONE")
        vp  = smc_details.get("vp",{})

        # Blended score: 50% classic + 50% SMC
        final_score = round(score * 0.5 + smc * 0.5)

        # Smart SL/Target using Order Blocks + ATR
        ob = smc_details.get("ob",{})
        if direction=="BUY":
            bull_ob = ob.get("bull_ob")
            # Minimum SL buffer (SEBI best practice)
    min_sl_pct = 0.004 if sym in ["NIFTY","BANKNIFTY","FINNIFTY"] else 0.006
    atr_sl = round(ltp - max(2.0*at, ltp*min_sl_pct), 1)
    sl = round(bull_ob["low"] - at*0.5, 1) if bull_ob else atr_sl
            target = round(ltp+3*at,1)
        else:
            bear_ob = ob.get("bear_ob")
            min_sl_pct = 0.004 if sym in ["NIFTY","BANKNIFTY","FINNIFTY"] else 0.006
    atr_sl_sell = round(ltp + max(2.0*at, ltp*min_sl_pct), 1)
    sl = round(bear_ob["high"] + at*0.5, 1) if bear_ob else atr_sl_sell
            target = round(ltp-3*at,1)

        rr = round(abs(target-ltp)/abs(ltp-sl),1) if ltp!=sl else 0

        # Fake filter
        fake = []
        if vol_ratio<0.5: fake.append("LowVol")
        if abs(mh)<0.001: fake.append("WeakMACD")
        if ms in ["CHOPPY","RANGING"] and smc < 20: fake.append("ChoppyMkt")

        return {"symbol":symbol,"ltp":ltp,"direction":direction,
                "entry":ltp,"sl":sl,"target":target,"rr":rr,
                "score":final_score,"classic_score":score,"smc_score":smc,
                "rsi":r,"vwap":vw,"vwap_bias":"ABOVE" if ltp>vw else "BELOW",
                "ema_cross":"BULL" if e9>e21 else "BEAR",
                "vol_ratio":vol_ratio,"fake":fake,"atr":at,
                "structure":ms,"bos":bos,
                "poc":vp.get("poc",0),"vah":vp.get("vah",0),"val":vp.get("val",0)}
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
                # SMC filter: Smart Money confirmation required
                smc = sig.get("smc_score", 0)
                if sig["score"] >= 50 and not sig["fake"] and smc >= 45:
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
