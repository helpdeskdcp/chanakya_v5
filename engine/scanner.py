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
    {"symbol":"GOLDM",      "token":"67694", "exchange":"MCX","type":"commodity",
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

def _analyze(candles, symbol, stock=None):
    if stock is None: stock = {}
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
        at     = atr(candles) or (ltp * 0.002)
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
            if vw and vw>0 and ltp>vw: score+=20
            if vol_ratio>=1.2: score+=10
            if st=="UP": score+=10
        else:
            if e9<e21: score+=25
            if 30<r<60: score+=20
            if mh<0: score+=15
            if vw and vw>0 and ltp<vw: score+=20
            if vol_ratio>=1.2: score+=10
            if st=="DOWN": score+=10

        # Smart Money Score (max 100)
        smc, smc_details = smc_score(candles, direction)
        ms  = smc_details.get("structure","UNKNOWN")
        bos = smc_details.get("bos","NONE")
        vp  = smc_details.get("vp",{})

        # Blended score: 50% classic + 50% SMC
        final_score = round(score * 0.5 + smc * 0.5)

        # ── EMA50 Pyramid Bonus ──────────────────────────
        try:
            e50 = ema(closes[-50:] if len(closes)>=50 else closes, 50)
            if direction=="BUY":
                pyr_strong = e9>e21 and e21>e50 and ltp>e200 if "e200" in dir() else e9>e21 and e21>e50
            else:
                pyr_strong = e9<e21 and e21<e50 and ltp<e200 if "e200" in dir() else e9<e21 and e21<e50
            if pyr_strong:
                final_score = min(100, final_score + 20)
        except: pass

        # ── Fibonacci Zone Bonus ──────────────────────────
        fib_tag = ""
        try:
            from engine.indicators import fibonacci_levels, fibonacci_zone
            _fibs  = fibonacci_levels(candles, lookback=100)
            _zones = fibonacci_zone(ltp, _fibs, tol=0.003)
            for _zn, _zp, _zd in _zones:
                if direction=="BUY" and _zn in ["38.2%","50.0%","61.8%"]:
                    final_score = min(100, final_score + 20)
                    fib_tag = f"FIB_{_zn}_SUPPORT"; break
                elif direction=="SELL" and _zn in ["23.6%","38.2%","78.6%"]:
                    final_score = min(100, final_score + 20)
                    fib_tag = f"FIB_{_zn}_RESIST"; break
        except: pass

        # SL/Target: MCX=ATR only, NSE=OB+ATR
        ob = smc_details.get("ob",{})
        is_mcx = stock.get("exchange","NSE") == "MCX"

        if direction=="BUY":
            if is_mcx:
                # MCX: tight ATR-based SL always (OB too wide)
                sl     = round(ltp - 1.5*at, 1)   # 1.5×ATR
                target = round(ltp + 4.0*at, 1)   # 4×ATR → RR=2.67
            else:
                # NSE: OB-based (untouched)
                bull_ob = ob.get("bull_ob")
                min_sl_pct = 0.004 if symbol in ["NIFTY","BANKNIFTY","FINNIFTY"] else 0.006
                atr_sl = round(ltp - max(2.0*at, ltp*min_sl_pct), 1)
                sl     = round(bull_ob["low"] - at*0.5, 1) if bull_ob else atr_sl
                target = round(ltp + 3*at, 1)
        else:
            if is_mcx:
                # MCX: tight ATR-based SL always
                sl     = round(ltp + 1.5*at, 1)   # 1.5×ATR above
                target = round(ltp - 4.0*at, 1)   # 4×ATR below → RR=2.67
            else:
                # NSE: OB-based (untouched)
                bear_ob = ob.get("bear_ob")
                min_sl_pct = 0.004 if symbol in ["NIFTY","BANKNIFTY","FINNIFTY"] else 0.006
                atr_sl_sell = round(ltp + max(2.0*at, ltp*min_sl_pct), 1)
                sl     = round(bear_ob["high"] + at*0.5, 1) if bear_ob else atr_sl_sell
                target = round(ltp - 3*at, 1)

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


def is_market_open(exchange=None):
    """NSE: Mon-Fri 9:15-15:30, MCX: Mon-Fri 9:00-23:30"""
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    if now.weekday() >= 5: return False
    t = now.hour * 100 + now.minute
    if exchange == "NSE": return 915 <= t <= 1530
    if exchange == "MCX": return 900 <= t <= 2330
    # Default: either market open
    return (915 <= t <= 1530) or (900 <= t <= 2330)

def is_nse_open():
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    if now.weekday() >= 5: return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1530

def is_mcx_open():
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    if now.weekday() >= 5: return False
    t = now.hour * 100 + now.minute
    return 900 <= t <= 2330

def scan_all(broker=None):
    try:
        # Check if any market is open
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
                sig = _analyze(candles, stock["symbol"], stock)
                if not sig: continue
                sig["exchange"] = stock["exchange"]
                sig["type"] = stock["type"]
                sig["token"] = stock["token"]
                # Exchange hours check
                exch = stock["exchange"]
                if exch == "NSE" and not is_nse_open(): continue
                if exch == "MCX" and not is_mcx_open(): continue

                # ── 9:45 Time Filter ──────────────────────────
                from datetime import datetime as _dt
                import pytz as _pytz
                _now = _dt.now(_pytz.timezone("Asia/Kolkata"))
                if _now.hour==9 and _now.minute<45 and exch=="NSE":
                    logger.debug("Skip %s — 9:45 filter", stock["symbol"])
                    continue

                # ── EMA200 Trend Filter ────────────────────────
                try:
                    from engine.indicators import ema as _ema
                    _closes = [float(c[4]) for c in candles]
                    _e200   = _ema(_closes[-200:] if len(_closes)>=200 else _closes,
                                   min(200, len(_closes)))
                    _ltp    = _closes[-1]
                    _dirn   = sig["direction"]
                    _with_trend = ((_dirn=="BUY"  and _ltp > _e200) or
                                   (_dirn=="SELL" and _ltp < _e200))
                    # Score modifier
                    if _with_trend:
                        sig["score"] = min(100, sig["score"] + 15)
                        sig["trend_align"] = "WITH"
                    else:
                        sig["score"] = max(0, sig["score"] - 20)
                        sig["trend_align"] = "COUNTER"
                    sig["ema200"] = round(_e200, 2)
                except: sig["trend_align"] = "UNKNOWN"

                # ── Multi-Timeframe Alignment ─────────────────────
                try:
                    from engine.mtf_analyzer import mtf_analyze, mtf_score_boost
                    _mtf = mtf_analyze(broker, stock["token"], stock["exchange"], stock["symbol"])
                    sig  = mtf_score_boost(sig, _mtf)
                    if not _mtf.get("aligned") and sig["score"] < 60:
                        logger.debug("Skip %s — MTF not aligned (%s)", stock["symbol"], _mtf.get("reason",""))
                        continue
                except Exception as _me:
                    logger.debug("MTF error %s: %s", stock["symbol"], _me)

                # ── Volume Spike Filter (MCX only, during hours) ──
                try:
                    _vols   = [float(c[5]) for c in candles]
                    _avg_v  = sum(_vols[-20:-1])/19 if len(_vols)>=20 else sum(_vols)/len(_vols)
                    _v_ratio= _vols[-1]/max(_avg_v,1)
                    sig["vol_ratio"] = round(_v_ratio, 2)
                    # NSE: vol check only during market hours (avoid 0 volume)
                    if exch=="MCX" and _v_ratio < 0.8:
                        sig["fake"] = sig.get("fake",[]) + ["LowVol_MCX"]
                except: pass

                smc = sig.get("smc_score", 0)
                # Thresholds
                if exch == "MCX":
                    min_score = 45; min_smc = 20
                    # Evening MCX: volume naturally low → remove vol filters
                    fake = [f for f in sig.get("fake",[])
                            if f not in ["LowVol","LowVol_MCX"]]
                else:
                    min_score = 50; min_smc = 30
                    fake = sig.get("fake",[])

                if sig["score"] >= min_score and not fake and smc >= min_smc:
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
