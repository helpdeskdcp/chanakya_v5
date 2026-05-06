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

def detect_intent(message):
    msg = message.upper()
    if any(x in msg for x in ["BUY","SELL","KHAREDI","VIKRI","GHYACHA","SIGNAL"]):
        return "trade_signal"
    if any(x in msg for x in ["OPTION","CE","PE","ATM","OTM","ITM","STRADDLE","STRANGLE"]):
        return "options"
    if any(x in msg for x in ["CHART","TREND","PATTERN","SUPPORT","RESISTANCE"]):
        return "chart_analysis"
    if any(x in msg for x in ["PRICE","LTP","RATE","BHAV","KIMAT"]):
        return "price_check"
    if any(x in msg for x in ["STRATEGY","PLAN","KASA","HOW","KAISA"]):
        return "strategy"
    if any(x in msg for x in ["MARKET","NIFTY","BANKNIFTY","SENSEX"]):
        return "market_outlook"
    if any(x in msg for x in ["PROFIT","LOSS","PNL","P&L","KAMAVLA","GAVLA"]):
        return "pnl_advice"
    if any(x in msg for x in ["HELP","KAY","WHAT","KAAY","SHIKVNAR"]):
        return "help"
    return "general"

def get_deep_analysis(symbol, token, exchange, broker):
    try:
        from engine.indicators import ema, rsi, macd, vwap, atr, supertrend
        from data_stream.cache import get as cget, set as cset
        result = {"symbol": symbol, "exchange": exchange}
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
            ltp  = closes[-1]
            r    = rsi(closes)
            e9   = ema(closes, 9)
            e21  = ema(closes, 21)
            e50  = ema(closes[-50:] if len(closes)>=50 else closes, 50)
            m,mh = macd(closes)
            vw   = vwap(candles[-50:] if len(candles)>=50 else candles)
            at   = atr(candles)
            st   = supertrend(candles)
            vol_avg   = sum(vols)/len(vols)
            vol_ratio = round(vols[-1]/vol_avg, 2) if vol_avg > 0 else 1
            high_20 = max(highs[-20:]) if len(highs)>=20 else max(highs)
            low_20  = min(lows[-20:])  if len(lows)>=20  else min(lows)
            pos_pct = round((ltp-low_20)/(high_20-low_20)*100,1) if high_20!=low_20 else 50
            bull_count = sum(1 for c in [e9>e21, ltp>vw, mh>0, r>50, st=="UP"] if c)
            trend = "STRONG_UP" if bull_count>=4 else "UP" if bull_count==3 else "STRONG_DOWN" if bull_count<=1 else "SIDEWAYS"
            tf_data[tf] = {
                "ltp": ltp, "rsi": round(r,1),
                "ema9": round(e9,2), "ema21": round(e21,2),
                "macd_hist": round(mh,2), "vwap": round(vw,2),
                "atr": round(at,2), "supertrend": st,
                "vol_ratio": vol_ratio, "trend": trend,
                "bull_count": bull_count, "pos_pct": pos_pct,
                "sl_buy":   round(ltp - 1.5*at, 2),
                "tgt_buy":  round(ltp + 3.0*at, 2),
                "sl_sell":  round(ltp + 1.5*at, 2),
                "tgt_sell": round(ltp - 3.0*at, 2),
            }
        result["timeframes"] = tf_data
        ml_conf = 50
        try:
            from ai.ml_engine import predict_confidence
            base = broker.get_candles(token, exchange, "FIVE_MINUTE", 2)
            if base: ml_conf = round(predict_confidence(base)*100, 1)
        except: pass
        result["ml_confidence"] = ml_conf
        if tf_data:
            bull_tfs  = sum(1 for v in tf_data.values() if "UP" in v["trend"])
            bear_tfs  = sum(1 for v in tf_data.values() if "DOWN" in v["trend"])
            total_tfs = len(tf_data)
            result["bull_tfs"]  = bull_tfs
            result["bear_tfs"]  = bear_tfs
            result["total_tfs"] = total_tfs
            result["direction"] = "BUY" if bull_tfs >= bear_tfs else "SELL"
            base_tf = tf_data.get("5m") or tf_data.get("15m") or list(tf_data.values())[0]
            result["ltp"]    = base_tf["ltp"]
            result["entry"]  = base_tf["ltp"]
            result["sl"]     = base_tf["sl_buy"]   if result["direction"]=="BUY" else base_tf["sl_sell"]
            result["target"] = base_tf["tgt_buy"]  if result["direction"]=="BUY" else base_tf["tgt_sell"]
            result["atr"]    = base_tf["atr"]
            rr = abs(result["target"]-result["entry"]) / abs(result["entry"]-result["sl"]) if result["entry"]!=result["sl"] else 0
            result["rr"] = round(rr, 2)
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

def get_live_ltps(broker):
    ltps = {}
    try:
        from data_stream.cache import get as cget, set as cset
        for name, token, exch, typ in SYMBOLS:
            ltp = cget("ltp_"+name)
            if not ltp:
                ltp = broker.get_ltp(exch, name, token)
                if ltp: cset("ltp_"+name, ltp, ttl=5)
            if ltp: ltps[name] = ltp
    except: pass
    return ltps


SEBI_TRADING_MATH = """
=== CHANAKYA NEURAL ENGINE — SEBI MATH FRAMEWORK ===

1. EXPECTANCY = (Win% × Avg_Win) - (Loss% × Avg_Loss)
   Positive expectancy = profitable strategy
   Target: Expectancy > 0.5R per trade

2. POSITION SIZE = (Capital × Risk%) / Stop_Loss_Points
   Max Risk per trade: 2% of capital
   Kelly Criterion: f = (bp - q) / b (advanced sizing)

3. PROBABILITY FRAMEWORK:
   Win Rate > 60% with 1:2 RR = High Edge System
   Breakeven WR = 1 / (1 + RR_ratio)
   At 1:2 RR → breakeven at 33.3% win rate

4. OPTIONS GREEKS:
   Delta (Δ): Price change per ₹1 move (CE: 0-1, PE: -1 to 0)
   Theta (Θ): Daily time decay loss (negative for buyers)
   Gamma (Γ): Rate of Delta change (high near ATM at expiry)
   Vega (v): Premium change per 1% IV change
   ATM option loses 1/3 value in last week (Theta decay)

5. VOLATILITY:
   IV > HV → Options expensive (sell strategy)
   IV < HV → Options cheap (buy strategy)
   VIX > 20 → High fear, good for contrarian buys

6. BLACK-SCHOLES (Option Fair Price):
   C = S×N(d1) - K×e^(-rt)×N(d2)
   Use: Compare market premium vs fair value

7. EMA FORMULA: EMA = Price×k + EMA_prev×(1-k)
   k = 2/(period+1)
   EMA crossover = trend change signal

8. RSI FORMULA: RSI = 100 - (100/(1+RS))
   RS = Avg_Gain/Avg_Loss (14 periods)
   RSI>70 = Overbought, RSI<30 = Oversold

9. ATR (Average True Range):
   TR = max(High-Low, |High-Prev_Close|, |Low-Prev_Close|)
   ATR = 14-period avg of TR
   Use: Dynamic stop-loss = Entry ± 1.5×ATR

10. VWAP = Σ(Price×Volume) / Σ(Volume)
    Price > VWAP = Bullish bias
    Price < VWAP = Bearish bias
    Best for intraday entries

11. PIVOT POINTS:
    PP = (H+L+C)/3
    R1=2×PP-L, R2=PP+(H-L), R3=H+2×(PP-L)
    S1=2×PP-H, S2=PP-(H-L), S3=L-2×(H-PP)

12. FIBONACCI LEVELS:
    23.6%, 38.2%, 50%, 61.8%(Golden), 78.6%
    Extensions: 127.2%, 161.8%(Target)
    61.8% = strongest retracement level
"""

def build_market_context(analysis, ltps):
    now = datetime.now(IST)
    h,mn = now.hour, now.minute
    nse_open = (9,15)<=(h,mn)<=(15,30) and now.weekday()<5
    mcx_open = now.weekday()<5
    lines = []
    lines.append(f"Time={now.strftime('%d-%b %H:%M IST')} NSE={'OPEN' if nse_open else 'CLOSED'} MCX={'OPEN' if mcx_open else 'CLOSED'}")
    if ltps:
        lines.append("LIVE_LTP: " + " | ".join([f"{k}={int(v)}" for k,v in ltps.items()]))
    if analysis and "timeframes" in analysis and not "error" in analysis:
        sym = analysis["symbol"]
        lines.append(f"\n{sym} ANALYSIS:")
        lines.append(f"  LTP={analysis.get('ltp',0)} DIR={analysis.get('direction','?')} ML={analysis.get('ml_confidence',50)}%")
        lines.append(f"  Entry={analysis.get('entry',0)} SL={analysis.get('sl',0)} Target={analysis.get('target',0)} RR=1:{analysis.get('rr',0)}")
        lines.append(f"  Bull_TF={analysis.get('bull_tfs',0)}/{analysis.get('total_tfs',0)} Bear_TF={analysis.get('bear_tfs',0)}/{analysis.get('total_tfs',0)}")
        for tf, d in analysis.get("timeframes",{}).items():
            lines.append(f"  [{tf}] {d['trend']} RSI={d['rsi']} EMA9/21={d['ema9']}/{d['ema21']} VWAP={d['vwap']} Vol={d['vol_ratio']}x")
        if "options" in analysis:
            opt = analysis["options"]
            lines.append(f"  OPTIONS: PCR={opt.get('pcr')} Bias={opt.get('bias')} MaxPain={opt.get('max_pain')} ATM={opt.get('atm_strike')}")
            lines.append(f"  CE_LTP={opt.get('atm_ce_ltp')} PE_LTP={opt.get('atm_pe_ltp')} Support={opt.get('support_oi')} Res={opt.get('resistance_oi')}")
    # News context
    try:
        from ai.news_sentiment import get_live_news, analyze_sentiment
        news = get_live_news()
        if news:
            ov = analyze_sentiment(news[:5])
            lines.append("NEWS: "+ov.get("label","NEUTRAL")+" "+ov.get("reason",""))
    except: pass
    return "\n".join(lines)

def get_user_context(username=None, role="demo"):
    from config.subscriptions import days_remaining, TIERS
    ctx = {"role": role, "is_premium": role in ["gold","platinum","developer","administrator"]}
    return ctx

def chanakya_chat(message, broker=None, username=None, role="demo"):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        from ai.groq_client import get_client
        client = get_client()
        if not client: return "AI unavailable"

        intent = detect_intent(message)
        msg_up = message.upper()

        # Detect primary symbol
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
                    "SELL","NSE","MCX","BSE","ATM","OTM","ITM","CE","PE",
                    "KARU","GHYA","SANGA","KASA","AATA","MALA","TULA"}
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

        # Live LTPs
        ltps = get_live_ltps(broker) if broker and broker.is_connected() else {}

        # Market context
        market_ctx = build_market_context(analysis, ltps)

        # User context
        is_premium = role in ["gold","platinum","developer","administrator","silver"]
        is_demo    = role in ["demo","premium"]

        # Smart engagement hints
        engagement = ""
        if is_demo:
            engagement = """
ENGAGEMENT RULES FOR DEMO USER:
- Give partial analysis — tease premium features
- Mention: "Gold subscription madhe full MTF analysis milto"
- After answering, ask 1 smart follow-up question
- Examples: "Tumhi intraday karta ka swing?" / "Kis capital ne trading karta?"
- Make them feel Chanakya AI is indispensable
- Never be pushy — be genuinely helpful first
"""
        else:
            engagement = """
ENGAGEMENT RULES FOR PREMIUM USER:
- Give COMPLETE world-class analysis
- After signal, suggest related plays
- Examples: "NIFTY BUY madhe BANKNIFTY pan similar setup aahe"
- Make them feel they have unfair advantage
"""

        system = f"""You are CHANAKYA AI 🔱 — India's Most Intelligent Trading System.

PERSONALITY:
- Wise like Chanakya (ancient strategist)
- Sharp like a professional trader  
- Warm like a trusted mentor
- Never wrong tone — always confident
- Better than ChatGPT/Claude for Indian markets

CAPABILITIES:
✅ Live MTF analysis (1m/5m/15m/30m/1hr)
✅ XGBoost ML predictions
✅ Options chain PCR/OI/MaxPain
✅ 1,80,000 stocks knowledge
✅ Groq LLaMA 3.3 70B reasoning

USER: {username or 'Trader'} | Plan: {role.upper()} | Intent: {intent}

{engagement}

LIVE MARKET DATA:
{market_ctx}

RESPONSE RULES:
1. ALWAYS specific Entry/SL/Target with ₹ values
2. ALWAYS Risk-Reward ratio
3. ALWAYS ML confidence % if available  
4. Explain WHY in simple terms
5. Reply in SAME language as user (Marathi/Hindi/English mix ok)
6. Use SEBI math framework for analysis:
   - Always mention Expectancy when discussing strategy
   - Quote Probability % with Win Rate context
   - Explain Greeks for options questions (Delta/Theta/Gamma/Vega)
   - Use ATR for stop-loss recommendations
   - VWAP for intraday bias
   - Fibonacci for targets/support
7. For predictions: mention probability %, expected move, IV context
6. NEWS context madhe asel tar respond madhe mention karo: "📰 News: [sentiment] - [key point]"
7. News sentiment BUY/SELL bias varti influence karato
6. Max 6 lines — powerful and concise
7. End with ONE smart follow-up question (not pushy)
8. If demo user asks advanced feature → mention Gold plan naturally

FORMAT (adapt based on intent):
🎯 [Signal/Answer]
💰 Entry: ₹X | SL: ₹X | Target: ₹X  
📊 RR: 1:X | ML: X% | TF: X/Y agree
📈 Why: [reason]
❓ [Smart follow-up question]"""

        try:
            from ai.groq_client import ask
            full_msg = system + "\n\nUser: " + message
            reply = ask(full_msg, max_tokens=300, temperature=0.25)
        except Exception as e:
        logger.error("chanakya_chat: %s", e)
        return "AI error: " + str(e)
