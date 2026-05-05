import math

def ema(data, period):
    try:
        if len(data) < period: return data[-1] if data else 0
        k = 2/(period+1)
        e = sum(data[:period])/period
        for v in data[period:]: e = v*k + e*(1-k)
        return round(e, 2)
    except: return 0

def rsi(closes, period=14):
    try:
        if len(closes) < period+1: return 50
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i]-closes[i-1]
            gains.append(max(d,0)); losses.append(max(-d,0))
        ag = sum(gains[-period:])/period
        al = sum(losses[-period:])/period
        return round(100-(100/(1+ag/al)) if al>0 else 100, 1)
    except: return 50

def macd(closes):
    try:
        if len(closes) < 26: return 0, 0
        # Proper MACD: signal = 9-EMA of macd_line, histogram = macd - signal
        macd_vals = []
        for i in range(26, len(closes)+1):
            e12i = ema(closes[:i], 12)
            e26i = ema(closes[:i], 26)
            macd_vals.append(e12i - e26i)
        macd_line = macd_vals[-1] if macd_vals else 0
        signal_line = ema(macd_vals, 9) if len(macd_vals) >= 9 else macd_vals[-1] if macd_vals else 0
        histogram = macd_line - signal_line
        return round(macd_line, 2), round(histogram, 2)
    except: return 0, 0

def vwap(candles):
    try:
        tv = 0; tpv = 0
        for c in candles:
            h,l,cl,v = float(c[2]),float(c[3]),float(c[4]),float(c[5])
            p = (h+l+cl)/3
            tv += v; tpv += p*v
        return round(tpv/tv, 2) if tv > 0 else 0
    except: return 0

def atr(candles, period=14):
    try:
        trs = []
        for c in candles:
            h,l = float(c[2]),float(c[3])
            trs.append(h-l)
        if not trs: return 0
        recent = trs[-period:] if len(trs)>=period else trs
        return round(sum(recent)/len(recent), 2)
    except: return 0

def supertrend(candles, period=10, multiplier=3):
    try:
        if len(candles) < period: return "UP"
        closes = [float(c[4]) for c in candles]
        a = atr(candles, period)
        ltp = closes[-1]
        mid = (float(candles[-1][2])+float(candles[-1][3]))/2
        upper = mid + multiplier*a
        lower = mid - multiplier*a
        return "UP" if ltp > lower else "DOWN"
    except: return "UP"
