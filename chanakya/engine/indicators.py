"""
Chanakya AI v5 — Technical Indicators (Fixed)
Fixes: True ATR, Wilder's RSI, Session VWAP, Proper Supertrend
"""
import math

def ema(data, period):
    """Exponential Moving Average"""
    try:
        if len(data) < period: return data[-1] if data else 0
        k = 2/(period+1)
        e = sum(data[:period])/period
        for v in data[period:]: e = v*k + e*(1-k)
        return round(e, 2)
    except: return 0

def rsi(closes, period=14):
    """
    Wilder's RSI (correct implementation)
    Uses EMA-like smoothing, not SMA
    """
    try:
        if len(closes) < period+1: return 50
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        # First average (SMA seed)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        # Wilder's smoothing (RMA)
        for i in range(period, len(gains)):
            avg_gain = (avg_gain*(period-1) + gains[i]) / period
            avg_loss = (avg_loss*(period-1) + losses[i]) / period
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return round(100 - (100/(1+rs)), 1)
    except: return 50

def macd(closes):
    """
    MACD with proper signal line
    macd_line = EMA12 - EMA26
    signal = 9-EMA of macd_line
    histogram = macd_line - signal
    """
    try:
        if len(closes) < 26: return 0, 0
        # Efficient: calculate incrementally
        k12 = 2/(12+1); k26 = 2/(26+1); k9 = 2/(9+1)
        e12 = sum(closes[:12])/12
        e26 = sum(closes[:26])/26
        for v in closes[12:26]: e12 = v*k12 + e12*(1-k12)

        macd_vals = []
        for v in closes[26:]:
            e12 = v*k12 + e12*(1-k12)
            e26 = v*k26 + e26*(1-k26)
            macd_vals.append(e12 - e26)

        if not macd_vals: return 0, 0
        macd_line = macd_vals[-1]

        # Signal line = 9-EMA of macd_vals
        if len(macd_vals) >= 9:
            signal = sum(macd_vals[:9])/9
            for v in macd_vals[9:]: signal = v*k9 + signal*(1-k9)
        else:
            signal = sum(macd_vals)/len(macd_vals)

        histogram = macd_line - signal
        return round(macd_line, 4), round(histogram, 4)
    except: return 0, 0

def vwap(candles):
    """
    Session VWAP — resets daily at market open
    Uses today's candles only (or last session)
    """
    try:
        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        # Filter today's candles
        today_c = [c for c in candles if str(c[0]).startswith(today)]
        # Fallback: last 75 candles (~1 session of 5-min)
        if not today_c:
            today_c = candles[-75:] if len(candles)>=75 else candles
        tv = 0; tpv = 0
        for c in today_c:
            h=float(c[2]); l=float(c[3])
            cl=float(c[4]); v=float(c[5])
            p = (h+l+cl)/3
            tv += v; tpv += p*v
        return round(tpv/tv, 2) if tv>0 else 0
    except: return 0

def atr(candles, period=14):
    """
    True Average True Range
    TR = max(H-L, |H-prev_close|, |L-prev_close|)
    Uses Wilder's smoothing
    """
    try:
        if len(candles) < 2: return 0
        trs = []
        for i in range(1, len(candles)):
            h  = float(candles[i][2])
            l  = float(candles[i][3])
            pc = float(candles[i-1][4])
            tr = max(h-l, abs(h-pc), abs(l-pc))
            trs.append(tr)
        if not trs: return 0
        # Wilder's ATR smoothing
        atr_val = sum(trs[:period])/period if len(trs)>=period else sum(trs)/len(trs)
        for tr in trs[period:]:
            atr_val = (atr_val*(period-1) + tr) / period
        return round(atr_val, 2)
    except: return 0

def supertrend(candles, period=10, multiplier=3):
    """
    Proper Supertrend with trend persistence and flip detection
    Returns: "UP" or "DOWN"
    """
    try:
        if len(candles) < period+1: return "UP"

        # Calculate ATR for each candle
        atrs = []
        for i in range(1, len(candles)):
            h=float(candles[i][2]); l=float(candles[i][3])
            pc=float(candles[i-1][4])
            tr=max(h-l, abs(h-pc), abs(l-pc))
            atrs.append(tr)

        trend = "UP"
        prev_upper = float('inf')
        prev_lower = 0

        for i in range(period, len(atrs)):
            c_idx = i + 1  # candle index
            h = float(candles[c_idx][2])
            l = float(candles[c_idx][3])
            cl= float(candles[c_idx][4])

            # ATR for this candle (rolling)
            window_trs = atrs[max(0,i-period+1):i+1]
            atr_v = sum(window_trs)/len(window_trs)

            mid = (h+l)/2
            raw_upper = mid + multiplier*atr_v
            raw_lower = mid - multiplier*atr_v

            # Band lock logic
            upper = raw_upper if raw_upper < prev_upper else prev_upper
            lower = raw_lower if raw_lower > prev_lower else prev_lower

            # Trend flip
            if trend == "UP":
                if cl < lower: trend = "DOWN"; lower = raw_lower
            else:
                if cl > upper: trend = "UP"; upper = raw_upper

            prev_upper = upper
            prev_lower = lower

        return trend
    except: return "UP"

def fibonacci_levels(candles, lookback=100):
    """Fibonacci Retracement levels"""
    recent = candles[-min(lookback,len(candles)):]
    highs  = [float(c[2]) for c in recent]
    lows   = [float(c[3]) for c in recent]
    sh=max(highs); sl=min(lows); diff=sh-sl
    return {
        "swing_high": round(sh,2), "swing_low": round(sl,2),
        "23.6%": round(sh-diff*0.236,2),
        "38.2%": round(sh-diff*0.382,2),
        "50.0%": round(sh-diff*0.500,2),
        "61.8%": round(sh-diff*0.618,2),
        "78.6%": round(sh-diff*0.786,2),
        "ext_127%": round(sl-diff*0.272,2),
        "ext_161%": round(sl-diff*0.618,2),
    }

def fibonacci_zone(ltp, levels, tol=0.002):
    """LTP कोणत्या Fib zone मध्ये आहे?"""
    zones = []
    for k,v in levels.items():
        if k in ["swing_high","swing_low"]: continue
        if abs(ltp-v)/max(ltp,1) <= tol:
            zones.append((k, v, round(abs(ltp-v)/ltp*100,3)))
    return sorted(zones, key=lambda x: x[2])

def pivot_levels(prev_high, prev_low, prev_close):
    """Standard Pivot Point levels"""
    pp = round((prev_high+prev_low+prev_close)/3, 2)
    r1 = round(2*pp-prev_low, 2)
    r2 = round(pp+(prev_high-prev_low), 2)
    r3 = round(r1+(prev_high-prev_low), 2)
    s1 = round(2*pp-prev_high, 2)
    s2 = round(pp-(prev_high-prev_low), 2)
    s3 = round(s1-(prev_high-prev_low), 2)
    return {"PP":pp,"R1":r1,"R2":r2,"R3":r3,"S1":s1,"S2":s2,"S3":s3}

def pivot_zone(ltp, levels, tol=0.003):
    hits = []
    for name,val in levels.items():
        dist = abs(ltp-val)/max(ltp,1)
        if dist<=tol: hits.append((name,val,round(dist*100,3)))
    return sorted(hits, key=lambda x: x[2])

def pivot_bias(ltp, levels):
    if ltp>levels["R1"]: return "STRONG_BULL"
    if ltp>levels["PP"]: return "BULL"
    if ltp<levels["S1"]: return "STRONG_BEAR"
    if ltp<levels["PP"]: return "BEAR"
    return "NEUTRAL"
