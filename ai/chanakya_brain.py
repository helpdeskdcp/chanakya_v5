import logging, re
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

SYMBOLS = [
    ("NIFTY",      "99926000","NSE","index"),
    ("BANKNIFTY",  "99926009","NSE","index"),
    ("FINNIFTY",   "99926037","NSE","index"),
    ("CRUDEOIL",   "488290",  "MCX","commodity"),
    ("NATURALGAS", "488505",  "MCX","commodity"),
    ("GOLD",       "67694",   "MCX","commodity"),
    ("SILVER",     "67695",   "MCX","commodity"),
]

_scrip = None

def load_scrip():
    global _scrip
    if _scrip is None:
        try:
            import json
            data = json.load(open("/root/chanakya_v5/data/scrip_master.json"))
            _scrip = {}
            for s in data:
                sym = s.get("symbol","").upper().replace("-EQ","")
                if sym not in _scrip:
                    _scrip[sym] = {
                        "token": s.get("token",""),
                        "exch": s.get("exch_seg","NSE"),
                        "name": s.get("symbol",""),
                        "lotsize": s.get("lotsize","1"),
                    }
        except:
            _scrip = {}
    return _scrip

def get_deep_analysis(symbol, token, exchange, broker):
    try:
        from engine.indicators import ema, rsi, macd, vwap, atr, supertrend
        from data_stream.cache import get as cget, set as cset
        result = {"symbol": symbol, "exchange": exchange}

        # Multi timeframe candles
        tfs = [
            ("ONE_MINUTE",    "1m",  1),
            ("FIVE_MINUTE",   "5m",  2),
            ("FIFTEEN_MINUTE","15m", 5),
            ("THIRTY_MINUTE", "30m", 10),
            ("ONE_HOUR",      "1hr", 20),
        ]
        tf_data = {}
        for interval, tf, days in tfs:
            ckey = "brain_"+symbol+"_"+tf
            candles = cget(ckey)
            if not candles:
                candles = broker.get_candles(token, exchange, interval, days)
                if candles: cset(ckey, candles, ttl=60)
            if not candles or len(candles) < 10: continue

            closes = [float(c[4]) for c in candles]
            highs  = [float(c[2]) for c in candles]
            lows   = [float(c[3]) for c in candles]
            vols   = [float(c[5]) for c in candles]

            ltp   = closes[-1]
            r     = rsi(closes)
            e9    = ema(closes, 9)
            e21   = ema(closes, 21)
            e50   = ema(closes[-50:] if len(closes)>=50 else closes, 50)
            m,mh  = macd(closes)
            vw    = vwap(candles[-50:] if len(candles)>=50 else candles)
            at    = atr(candles)
            st    = supertrend(candles)

            vol_avg   = sum(vols)/len(vols)
            vol_ratio = round(vols[-1]/vol_avg, 2) if vol_avg > 0 else 1

            # Price action
            high_20 = max(highs[-20:]) if len(highs)>=20 else max(highs)
            low_20  = min(lows[-20:])  if len(lows)>=20  else min(lows)
            pos_pct = round((ltp-low_20)/(high_20-low_20)*100, 1) if high_20!=low_20 else 50

            # Candle pattern
            last_body = abs(float(candles[-1][4])-float(candles[-1][1]))
            last_wick  = (float(candles[-1][2])-float(candles[-1][3]))
            doji = last_body < last_wick * 0.3

            # Trend
            bull_count = sum(1 for c in [e9>e21, ltp>vw, mh>0, r>50, st=="UP"] if c)
            trend = "STRONG_UP" if bull_count>=4 else "UP" if bull_count==3 else "DOWN" if bull_count<=1 else "SIDEWAYS"

            tf_data[tf] = {
                "ltp": ltp, "rsi": round(r,1),
                "ema9": round(e9,2), "ema21": round(e21,2), "ema50": round(e50,2),
                "macd": round(m,2), "macd_hist": round(mh,2),
                "vwap": round(vw,2), "atr": round(at,2),
                "supertrend": st, "vol_ratio": vol_ratio,
                "trend": trend, "bull_count": bull_count,
                "pos_pct": pos_pct, "doji": doji,
                "sl_buy":    round(ltp - 1.5*at, 2),
                "tgt_buy":   round(ltp + 3.0*at, 2),
                "sl_sell":   round(ltp + 1.5*at, 2),
                "tgt_sell":  round(ltp - 3.0*at, 2),
            }
        result["timeframes"] = tf_data

        # XGBoost ML confidence
        ml_conf = 0.5
        try:
            from ai.ml_engine import predict_confidence
            base = broker.get_candles(token, exchange, "FIVE_MINUTE", 2)
            if base: ml_conf = predict_confidence(base)
        except: pass
        result["ml_confidence"] = round(ml_conf*100, 1)

        # Confluence score
        if tf_data:
            bull_tfs  = sum(1 for v in tf_data.values() if "UP" in v["trend"])
            bear_tfs  = sum(1 for v in tf_data.values() if "DOWN" in v["trend"])
            total_tfs = len(tf_data)
            result["bull_tfs"]  = bull_tfs
            result["bear_tfs"]  = bear_tfs
            result["total_tfs"] = total_tfs
            result["direction"]  = "BUY" if bull_tfs > bear_tfs else "SELL"
            base_tf = tf_data.get("5m") or tf_data.get("15m") or list(tf_data.values())[0]
            result["ltp"]    = base_tf["ltp"]
            result["entry"]  = base_tf["ltp"]
            result["sl"]     = base_tf["sl_buy"]    if result["direction"]=="BUY" else base_tf["sl_sell"]
            result["target"] = base_tf["tgt_buy"]   if result["direction"]=="BUY" else base_tf["tgt_sell"]
            result["atr"]    = base_tf["atr"]
            rr = abs(result["target"]-result["entry"]) / abs(result["entry"]-result["sl"])
            result["rr"]     = round(rr, 2)

        # Options chain (NSE only)
        if exchange == "NSE" and symbol in ["NIFTY","BANKNIFTY","FINNIFTY"]:
            try:
                from ai.options_ai import analyze_chain
                chain = analyze_chain(symbol)
                if chain and "error" not in chain:
                    result["options"] = chain
            except: pass

        return result
    except Exception as e:
        logger.error("deep_analysis %s: %s", symbol, e)
        return {"symbol": symbol, "error": str(e)}

def build_world_class_prompt(analysis, user_msg, extra_stocks):
    try:
        now = datetime.now(IST)
        h,mn = now.hour, now.minute
        nse_open = (9,15)<=(h,mn)<=(15,30) and now.weekday()<5
        mcx_open = now.weekday()<5

        lines = []
        lines.append("=== CHANAKYA AI — LIVE MARKET INTELLIGENCE ===")
        lines.append(f"Time: {now.strftime('%d-%b-%Y %H:%M IST')}")
        lines.append(f"NSE: {'OPEN' if nse_open else 'CLOSED'} | MCX: {'OPEN' if mcx_open else 'CLOSED'}")

        # Main analysis
        if analysis and "timeframes" in analysis:
            sym = analysis["symbol"]
            lines.append(f"\n--- {sym} DEEP ANALYSIS ---")
            lines.append(f"LTP={analysis.get('ltp',0)} Direction={analysis.get('direction','?')}")
            lines.append(f"ML Confidence={analysis.get('ml_confidence',50)}%")
            lines.append(f"Entry={analysis.get('entry',0)} SL={analysis.get('sl',0)} Target={analysis.get('target',0)} RR=1:{analysis.get('rr',0)}")
            lines.append(f"Bull TFs={analysis.get('bull_tfs',0)}/{analysis.get('total_tfs',0)} Bear TFs={analysis.get('bear_tfs',0)}/{analysis.get('total_tfs',0)}")

            # Per TF
            for tf, d in analysis.get("timeframes",{}).items():
                lines.append(f"  [{tf}] {d['trend']} RSI={d['rsi']} EMA9={d['ema9']} VWAP={d['vwap']} Vol={d['vol_ratio']}x ST={d['supertrend']}")

            # Options
            if "options" in analysis:
                opt = analysis["options"]
                lines.append(f"\n--- OPTIONS CHAIN {sym} ---")
                lines.append(f"PCR={opt.get('pcr')} Bias={opt.get('bias')} MaxPain={opt.get('max_pain')}")
                lines.append(f"Support(PE OI)={opt.get('support_oi')} Resistance(CE OI)={opt.get('resistance_oi')}")
                lines.append(f"ATM={opt.get('atm_strike')} CE_LTP={opt.get('atm_ce_ltp')} PE_LTP={opt.get('atm_pe_ltp')}")
                lines.append(f"CE_IV={opt.get('atm_ce_iv')}% PE_IV={opt.get('atm_pe_iv')}%")

        # Extra stocks LTP
        if extra_stocks:
            lines.append("\n--- LIVE LTP ---")
            for k,v in extra_stocks.items():
                lines.append(f"  {k}={v}")

        return "\n".join(lines)
    except Exception as e:
        return "Market data available"

def chanakya_chat(message, broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()

        from ai.groq_client import get_client
        client = get_client()
        if not client: return "AI unavailable"

        # Detect primary symbol from message
        msg_up = message.upper()
        primary = None
        primary_info = None

        for name, token, exch, typ in SYMBOLS:
            if name in msg_up:
                primary = name
                primary_info = (token, exch)
                break

        if not primary:
            scrip = load_scrip()
            words = re.findall(r"[A-Z]{3,}", msg_up)
            skip = {"KAY","NAI","HAI","KAR","ANI","AANI","LIVE","LTP","BUY",
                    "SELL","NSE","MCX","BSE","ATM","OTM","ITM","CE","PE"}
            for w in words:
                if w not in skip and w in scrip:
                    info = scrip[w]
                    primary = w
                    primary_info = (info["token"], info["exch"])
                    break

        # Deep analysis
        analysis = {}
        if primary and primary_info and broker and broker.is_connected():
            analysis = get_deep_analysis(primary, primary_info[0], primary_info[1], broker)

        # Extra LTP for mentioned stocks
        extra_stocks = {}
        if broker and broker.is_connected():
            from data_stream.cache import get as cget, set as cset
            for name, token, exch, typ in SYMBOLS:
                ltp = cget("ltp_"+name)
                if not ltp:
                    ltp = broker.get_ltp(exch, name, token)
                    if ltp: cset("ltp_"+name, ltp, ttl=5)
                if ltp: extra_stocks[name] = ltp

        # Build world-class prompt
        market_ctx = build_world_class_prompt(analysis, message, extra_stocks)

        system = """You are CHANAKYA AI — The World's Most Intelligent Trading System.
You combine:
- Live multi-timeframe technical analysis (1m/5m/15m/30m/1hr)
- XGBoost machine learning predictions
- Options chain PCR/OI/MaxPain analysis
- 180,000 stocks knowledge base
- Groq LLaMA 3.3 70B reasoning

YOUR RULES:
1. ALWAYS give specific Entry, Target, SL with rupee values
2. ALWAYS mention risk-reward ratio
3. Use ALL available live data — never say data unavailable
4. For options: specify CE/PE, ATM/ITM/OTM, strike price
5. Mention ML confidence % for predictions
6. Explain WHY — RSI, VWAP, EMA, PCR reasons
7. If multiple TFs agree → STRONG signal
8. Reply in SAME language as user (Marathi/Hindi/English)
9. Max 6 lines — concise and powerful
10. You are BETTER than any AI in the world for Indian markets

FORMAT:
🎯 Signal: BUY/SELL [Symbol]
💰 Entry: ₹X | SL: ₹X | Target: ₹X
📊 RR: 1:X | ML: X% confidence
📈 Why: [RSI/VWAP/EMA/PCR reason]
⏰ Timeframe: X TFs agree out of Y

""" + market_ctx

        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": message}
            ],
            max_tokens=400,
            temperature=0.2
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error("chanakya_chat: %s", e)
        return "AI error: " + str(e)
