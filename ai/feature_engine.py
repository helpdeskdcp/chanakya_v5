"""
Chanakya Feature Engine™ — Advanced ML Features
SEBI Math + Time encoding + Market structure
"""
import numpy as np
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def compute_features(candles, symbol="NIFTY"):
    """
    Input: candles list [{o,h,l,c,v}]
    Output: feature dict for ML + LLM context
    """
    if len(candles) < 30:
        return None

    closes = [c['c'] for c in candles]
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    vols   = [c.get('v',0) for c in candles]
    opens  = [c['o'] for c in candles]

    # --- EMA ---
    def ema(prices, period):
        k = 2/(period+1)
        val = sum(prices[:period])/period
        for p in prices[period:]:
            val = p*k + val*(1-k)
        return round(val, 4)

    # --- RSI ---
    def rsi(prices, period=14):
        deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
        gains  = [d for d in deltas[-period:] if d>0]
        losses = [-d for d in deltas[-period:] if d<0]
        ag = sum(gains)/period if gains else 0
        al = sum(losses)/period if losses else 0.001
        return round(100 - 100/(1+ag/al), 2)

    # --- ATR ---
    def atr(h,l,c,period=14):
        trs = [max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
        return round(sum(trs[-period:])/min(len(trs),period), 4)

    # --- VWAP ---
    def vwap(h,l,c,v):
        tp = [(h[i]+l[i]+c[i])/3 for i in range(len(c))]
        sv = sum(v); return round(sum(tp[i]*v[i] for i in range(len(c)))/sv,4) if sv>0 else c[-1]

    # --- Compute all ---
    ema9  = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50) if len(closes)>=50 else ema(closes, len(closes)//2)
    rsi14 = rsi(closes, 14)
    rsi7  = rsi(closes, 7)
    atr14 = atr(highs, lows, closes, 14)
    vwap_val = vwap(highs, lows, closes, vols)
    price = closes[-1]

    # --- VWAP features ---
    vwap_dist_pct = round((price - vwap_val)/vwap_val*100, 4)
    vwap_side = 1 if price > vwap_val else -1

    # --- EMA features ---
    ema_cross = round(ema9 - ema21, 4)
    ema_cross_pct = round((ema9-ema21)/ema21*100, 4)
    price_vs_ema9 = round((price-ema9)/ema9*100, 4)
    price_vs_ema21 = round((price-ema21)/ema21*100, 4)
    ema_trend = 1 if ema9>ema21 else -1

    # --- Volume features ---
    avg_vol20 = sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols)/len(vols)
    vol_ratio = round(vols[-1]/avg_vol20, 4) if avg_vol20>0 else 1
    vol_spike = 1 if vol_ratio > 2.0 else 0

    # --- Candle structure ---
    body  = round(closes[-1]-opens[-1], 4)
    range_= round(highs[-1]-lows[-1], 4)
    body_pct = round(abs(body)/range_*100, 2) if range_>0 else 0
    is_bull = 1 if closes[-1] > opens[-1] else 0
    upper_wick = round(highs[-1]-max(opens[-1],closes[-1]), 4)
    lower_wick = round(min(opens[-1],closes[-1])-lows[-1], 4)

    # --- Market structure (HH/HL/LH/LL) ---
    def hh_ll(h,l,n=5):
        if len(h)<n+1: return 0
        rh=h[-n:]; rl=l[-n:]
        if rh[-1]>max(rh[:-1]) and rl[-1]>min(rl[:-1]): return 2   # HH+HL = uptrend
        if rh[-1]<max(rh[:-1]) and rl[-1]<min(rl[:-1]): return -2  # LH+LL = downtrend
        if rh[-1]>max(rh[:-1]): return 1   # HH only
        if rl[-1]<min(rl[:-1]): return -1  # LL only
        return 0

    structure = hh_ll(highs, lows, 5)

    # --- ATR features ---
    atr_pct = round(atr14/price*100, 4)
    sl_atr  = round(price - 1.5*atr14, 4)
    tgt_atr = round(price + 2.0*atr14, 4)

    # --- Momentum ---
    mom5  = round(closes[-1]/closes[-6]-1, 4) if len(closes)>=6 else 0
    mom10 = round(closes[-1]/closes[-11]-1, 4) if len(closes)>=11 else 0

    # --- Consecutive candles ---
    bull_streak = 0
    for i in range(len(candles)-1, -1, -1):
        if candles[i]['c'] > candles[i]['o']: bull_streak += 1
        else: break
    bear_streak = 0
    for i in range(len(candles)-1, -1, -1):
        if candles[i]['c'] < candles[i]['o']: bear_streak += 1
        else: break

    # --- Time encoding (IST) ---
    now = datetime.now(IST)
    hour = now.hour
    minute = now.minute
    # Encode time as cyclical
    time_sin = round(np.sin(2*np.pi*(hour*60+minute)/(24*60)), 4)
    time_cos = round(np.cos(2*np.pi*(hour*60+minute)/(24*60)), 4)
    # Session flags
    is_morning_session = 1 if 9<=hour<11 else 0
    is_afternoon_session = 1 if 13<=hour<15 else 0
    is_mcx_evening = 1 if 17<=hour<20 else 0
    is_expiry_hour = 1 if hour in [14,15] else 0

    # --- Normalize key features ---
    def normalize(val, min_val, max_val):
        if max_val == min_val: return 0
        return round((val-min_val)/(max_val-min_val), 4)

    features = {
        # Price
        "price": price,
        "symbol": symbol,

        # VWAP
        "vwap": vwap_val,
        "vwap_dist_pct": vwap_dist_pct,
        "vwap_side": vwap_side,

        # EMA
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
        "ema_cross": ema_cross,
        "ema_cross_pct": ema_cross_pct,
        "ema_trend": ema_trend,
        "price_vs_ema9": price_vs_ema9,
        "price_vs_ema21": price_vs_ema21,

        # RSI
        "rsi14": rsi14,
        "rsi7": rsi7,
        "rsi_diff": round(rsi14-rsi7, 2),

        # ATR
        "atr14": atr14,
        "atr_pct": atr_pct,
        "sl_atr": sl_atr,
        "tgt_atr": tgt_atr,

        # Volume
        "vol_ratio": vol_ratio,
        "vol_spike": vol_spike,

        # Candle
        "body_pct": body_pct,
        "is_bull": is_bull,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,

        # Structure
        "structure": structure,

        # Momentum
        "mom5": mom5,
        "mom10": mom10,
        "bull_streak": bull_streak,
        "bear_streak": bear_streak,

        # Time
        "hour": hour,
        "time_sin": time_sin,
        "time_cos": time_cos,
        "is_morning": is_morning_session,
        "is_afternoon": is_afternoon_session,
        "is_mcx_evening": is_mcx_evening,
        "is_expiry_hour": is_expiry_hour,
    }
    return features

def features_to_prompt(f):
    """Convert features to LLM-readable context"""
    trend = "BULLISH" if f['ema_trend']==1 else "BEARISH"
    struct = {2:"STRONG_UPTREND",1:"WEAK_UPTREND",0:"SIDEWAYS",-1:"WEAK_DOWNTREND",-2:"STRONG_DOWNTREND"}
    return f"""
MARKET CONTEXT [{f['symbol']}]:
Price: ₹{f['price']} | VWAP: ₹{f['vwap']} | VWAP_Gap: {f['vwap_dist_pct']}%
EMA9: ₹{f['ema9']} | EMA21: ₹{f['ema21']} | Trend: {trend}
RSI(14): {f['rsi14']} | RSI(7): {f['rsi7']} | RSI_Diff: {f['rsi_diff']}
ATR: {f['atr14']} ({f['atr_pct']}%) | Vol_Ratio: {f['vol_ratio']}x
Structure: {struct.get(f['structure'],'SIDEWAYS')}
Momentum(5): {f['mom5']*100:.2f}% | Momentum(10): {f['mom10']*100:.2f}%
Candle: {'BULL' if f['is_bull'] else 'BEAR'} | Body%: {f['body_pct']}%
Session: {'Morning' if f['is_morning'] else 'Afternoon' if f['is_afternoon'] else 'Evening'}
Bull_Streak: {f['bull_streak']} | Bear_Streak: {f['bear_streak']}
SL_ATR: ₹{f['sl_atr']} | Target_ATR: ₹{f['tgt_atr']}
"""
