import logging
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

WATCHLIST = [
    {"symbol":"NIFTY",      "token":"99926000","exchange":"NSE","type":"index"},
    {"symbol":"BANKNIFTY",  "token":"99926009","exchange":"NSE","type":"index"},
    {"symbol":"FINNIFTY",   "token":"99926037","exchange":"NSE","type":"index"},
    {"symbol":"CRUDEOIL",   "token":"488290",  "exchange":"MCX","type":"commodity"},
    {"symbol":"NATURALGAS", "token":"488505",  "exchange":"MCX","type":"commodity"},
    {"symbol":"RELIANCE",   "token":"2885",    "exchange":"NSE","type":"equity"},
    {"symbol":"TCS",        "token":"11536",   "exchange":"NSE","type":"equity"},
    {"symbol":"WIPRO",      "token":"3787",    "exchange":"NSE","type":"equity"},
    {"symbol":"HDFCBANK",   "token":"1333",    "exchange":"NSE","type":"equity"},
    {"symbol":"ICICIBANK",  "token":"4963",    "exchange":"NSE","type":"equity"},
    {"symbol":"SBIN",       "token":"3045",    "exchange":"NSE","type":"equity"},
    {"symbol":"TATASTEEL",  "token":"3499",    "exchange":"NSE","type":"equity"},
    {"symbol":"SUZLON",     "token":"12018",   "exchange":"NSE","type":"equity"},
]

INTERVALS = [
    ("ONE_MINUTE",    "1m", 1),
    ("FIVE_MINUTE",   "5m", 2),
    ("FIFTEEN_MINUTE","15m",5),
    ("THIRTY_MINUTE", "30m",10),
    ("ONE_HOUR",      "1hr",20),
]

def analyze_tf(candles, tf):
    try:
        from engine.indicators import ema, rsi, macd, vwap, atr
        if not candles or len(candles)<5: return None
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        ltp = closes[-1]
        r   = rsi(closes)
        e9  = ema(closes,9); e21 = ema(closes,21)
        m,mh = macd(closes)
        vw   = vwap(candles[-50:] if len(candles)>=50 else candles)
        at   = atr(candles)
        vol_avg = sum(vols)/len(vols)
        vol_ratio = round(vols[-1]/vol_avg,2) if vol_avg>0 else 1
        if e9>e21 and r<72: trend="UP"
        elif e9<e21 and r>28: trend="DOWN"
        else: trend="SIDEWAYS"
        # Direction first, then direction-aware scoring
        if e9>e21 and r<72: trend_dir="UP"
        elif e9<e21 and r>28: trend_dir="DOWN"
        else: trend_dir="SIDEWAYS"
        score = 0
        if trend_dir=="UP":
            if e9>e21: score+=25
            if 40<r<72: score+=20
            if mh>0: score+=15
            if ltp>vw: score+=20
            if vol_ratio>=1.2: score+=10
        elif trend_dir=="DOWN":
            if e9<e21: score+=25
            if 28<r<60: score+=20
            if mh<0: score+=15
            if ltp<vw: score+=20
            if vol_ratio>=1.2: score+=10
        fake = []
        if vol_ratio<0.5: fake.append("LowVol")
        if abs(mh)<0.001: fake.append("WeakMACD")
        return {"tf":tf,"ltp":ltp,"rsi":round(r,1),"trend":trend,
                "vwap_bias":"ABOVE" if ltp>vw else "BELOW",
                "macd":"BULL" if mh>0 else "BEAR",
                "vol_ratio":vol_ratio,"score":score,"fake":fake,
                "sl":round(ltp-1.5*at,1),"target":round(ltp+3*at,1),"atr":round(at,2)}
    except Exception as e:
        logger.debug("analyze_tf %s: %s", tf, e)
        return None

def predict_symbol(symbol, token, exchange, broker):
    try:
        from data_stream.cache import get as cget, set as cset
        results = {}
        now = datetime.now(IST)
        h,mn = now.hour,now.minute
        nse_open = (9,15)<=(h,mn)<=(15,30) and now.weekday()<5
        mcx_open = (9,0)<=(h,mn)<=(23,30) and now.weekday()<5
        is_open = (exchange=="NSE" and nse_open) or (exchange=="MCX" and mcx_open)
        if not is_open: return None  # Market closed for this exchange
        for interval,tf,days in INTERVALS:
            ckey = "pred_"+symbol+"_"+tf
            candles = cget(ckey)
            if not candles:
                candles = broker.get_candles(token, exchange, interval, days)
                if candles: cset(ckey, candles, ttl=60)
            if not candles: continue
            r = analyze_tf(candles, tf)
            if r: results[tf] = r
        if not results: return None
        bull = sum(1 for v in results.values() if v["trend"]=="UP")
        bear = sum(1 for v in results.values() if v["trend"]=="DOWN")
        total = len(results)
        # Dynamic threshold: 60% of available TFs must agree
        threshold = max(2, round(total * 0.6))
        if bull>=threshold: overall="BULLISH"; direction="BUY"
        elif bear>=threshold: overall="BEARISH"; direction="SELL"
        else: return None
        scores = [v["score"] for v in results.values()]
        conf = int(sum(scores)/len(scores))
        base = results.get("5m") or results.get("15m") or list(results.values())[0]
        ltp = base["ltp"]; sl = base["sl"]; target = base["target"]
        if direction=="SELL":
            sl = round(ltp+base["atr"]*1.5,1)
            target = round(ltp-base["atr"]*3,1)
        rr = round(abs(target-ltp)/abs(ltp-sl),1) if ltp!=sl else 0
        all_fake = []
        for v in results.values(): all_fake.extend(v.get("fake",[]))
        if all_fake: conf -= len(set(all_fake))*10
        conf = max(45, min(95, conf))
        # Groq verdict
        verdict = ""
        try:
            from ai.groq_client import get_client
            client = get_client()
            if client:
                tf_sum = " | ".join([v["tf"]+":"+v["trend"] for v in results.values()])
                prompt = (symbol+" "+direction+" LTP="+str(ltp)+" SL="+str(sl)+" T="+str(target)+
                         " RR="+str(rr)+" bull_tf="+str(bull)+"/"+str(total)+" "+tf_sum+
                         "\n1-line verdict: STRONG/MODERATE/WEAK + reason")
                r = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role":"user","content":prompt}],
                    max_tokens=60, temperature=0.1)
                verdict = r.choices[0].message.content.strip()
                pass  # allow weak signals
        except: pass
        # XGBoost confidence boost
        ml_conf = 0.5
        try:
            from ai.ml_engine import predict_confidence
            base_candles = broker.get_candles(token, exchange, "FIVE_MINUTE", 2)
            if base_candles:
                ml_conf = predict_confidence(base_candles)
                # Blend MTF score with ML confidence
                conf = int(conf * 0.6 + ml_conf * 100 * 0.4)
                conf = max(45, min(95, conf))
        except: pass
        return {"symbol":symbol,"exchange":exchange,"direction":direction,
                "ltp":ltp,"entry":ltp,"sl":sl,"target":target,"rr":rr,
                "confidence":conf,"overall":overall,"bull_tf":bull,"bear_tf":bear,
                "total_tf":total,"ai_verdict":verdict,"fake":list(set(all_fake)),
                "scanned_at":now.strftime("%H:%M IST")}
    except Exception as e:
        logger.debug("predict %s: %s", symbol, e)
        return None

def run_scan(broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        if not broker or not broker.is_connected(): return []
        signals = []
        for s in WATCHLIST:
            sig = predict_symbol(s["symbol"],s["token"],s["exchange"],broker)
            if sig: signals.append(sig)
        signals.sort(key=lambda x: -x["confidence"])
        logger.info("Prediction scan: %d signals", len(signals))
        # Send top 3 signals to telegram
        try:
            from notifications.telegram import alert_signal
            for s in signals[:3]:
                if s["confidence"] >= 60:
                    alert_signal(s["symbol"],s["direction"],s["entry"],s["sl"],s["target"],s["confidence"])
        except: pass
        return signals
    except Exception as e:
        logger.error("run_scan: %s", e)
        return []

def get_math_context(symbol, ltp, atr, rsi, ema9, ema21):
    """SEBI Math Framework context for AI"""
    capital = 100000  # default
    risk_pct = 2
    sl_pts = atr * 1.5 if atr else ltp * 0.01
    pos_size = int((capital * risk_pct / 100) / sl_pts) if sl_pts > 0 else 1

    # Expectancy (assuming 60% WR, 1:2 RR)
    win_rate = 0.60
    rr = 2.0
    expectancy = (win_rate * rr) - ((1 - win_rate) * 1)

    # EMA signal
    ema_signal = "BULLISH" if ema9 > ema21 else "BEARISH"

    # RSI context
    rsi_ctx = "OVERBOUGHT" if rsi > 70 else "OVERSOLD" if rsi < 30 else "NEUTRAL"

    # VWAP proxy
    vwap_bias = "ABOVE_VWAP_BULLISH" if ltp > ema21 else "BELOW_VWAP_BEARISH"

    return (
        f"MATH_CONTEXT: PosSiz={pos_size} ExpectancyR={expectancy:.2f} "
        f"ATR={atr:.2f} SL={sl_pts:.2f} "
        f"EMA={ema_signal} RSI={rsi:.0f}({rsi_ctx}) "
        f"VWAP_BIAS={vwap_bias}"
    )
