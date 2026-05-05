"""
Chanakya Scalping Engine — Multi-Strategy AI
Strategies: BREAKOUT, REVERSAL, RANGE_BOUND
"""
from scalping_engine.indicators import ema, rsi, atr, vwap, volume_spike, higher_high_lower_low
import json, os

def load_config():
    path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(path) as f: return json.load(f)

def detect_volatility_regime(atr_val, price, threshold=0.015):
    """HIGH/LOW/MEDIUM volatility"""
    atr_pct = atr_val / price if price > 0 else 0
    if atr_pct > threshold * 1.5: return "HIGH"
    if atr_pct < threshold * 0.5: return "LOW"
    return "MEDIUM"

def select_strategy(trend, vol_regime, vol_spike):
    """AI dynamically selects best strategy"""
    if vol_regime == "HIGH" and vol_spike:
        return "BREAKOUT"
    if trend == "SIDEWAYS" and vol_regime == "LOW":
        return "RANGE_BOUND"
    if trend in ("UPTREND","DOWNTREND") and not vol_spike:
        return "REVERSAL"
    return "BREAKOUT"

def breakout_signal(closes, highs, lows, volumes, vwap_val, rsi_val, ema9, ema21):
    """Breakout: Price > VWAP + RSI > 55 + Volume Spike"""
    price = closes[-1]
    vol_spike = volume_spike(volumes)
    score = 0
    reasons = []

    if price > vwap_val:
        score += 25; reasons.append("Price>VWAP")
    if rsi_val > 55:
        score += 20; reasons.append(f"RSI={rsi_val}")
    if vol_spike:
        score += 25; reasons.append("VolSpike")
    if ema9 > ema21:
        score += 20; reasons.append("EMA_Bull")
    if price > max(highs[-5:-1]):
        score += 10; reasons.append("NewHigh")

    if score >= 65 and price > vwap_val:
        return {"signal":"BUY_CE","score":score,"reasons":reasons,"strategy":"BREAKOUT"}
    if price < vwap_val and rsi_val < 45 and vol_spike:
        return {"signal":"BUY_PE","score":score,"reasons":reasons,"strategy":"BREAKOUT"}
    return {"signal":"NO_TRADE","score":score,"reasons":reasons,"strategy":"BREAKOUT"}

def reversal_signal(closes, highs, lows, rsi_val, vwap_val, atr_val):
    """Reversal: RSI extreme + Price structure reversal"""
    price = closes[-1]
    score = 0
    reasons = []

    # Oversold reversal → BUY CE
    if rsi_val < 35:
        score += 30; reasons.append(f"RSI_Oversold={rsi_val}")
    if price < vwap_val * 0.998:
        score += 20; reasons.append("Below_VWAP")
    if lows[-1] > lows[-2]:
        score += 25; reasons.append("HigherLow")
    if closes[-1] > closes[-2]:
        score += 15; reasons.append("Green_Candle")

    if score >= 65 and rsi_val < 40:
        return {"signal":"BUY_CE","score":score,"reasons":reasons,"strategy":"REVERSAL"}

    # Overbought reversal → BUY PE
    if rsi_val > 70 and price > vwap_val * 1.002:
        return {"signal":"BUY_PE","score":min(score+20,100),
                "reasons":["RSI_Overbought"],"strategy":"REVERSAL"}

    return {"signal":"NO_TRADE","score":score,"reasons":reasons,"strategy":"REVERSAL"}

def range_bound_signal(closes, highs, lows, rsi_val, vwap_val, atr_val):
    """Range-bound: Trade within range using mean reversion"""
    price = closes[-1]
    high20 = max(highs[-20:]) if len(highs)>=20 else max(highs)
    low20  = min(lows[-20:])  if len(lows)>=20  else min(lows)
    rng = high20 - low20
    if rng == 0: return {"signal":"NO_TRADE","score":0,"reasons":[],"strategy":"RANGE_BOUND"}

    pct_pos = (price - low20) / rng
    score = 0; reasons = []

    if pct_pos < 0.25 and rsi_val < 45:
        score = 80; reasons = [f"Near_Support pct={pct_pos:.2f}","RSI_Low"]
        return {"signal":"BUY_CE","score":score,"reasons":reasons,"strategy":"RANGE_BOUND"}
    if pct_pos > 0.75 and rsi_val > 55:
        score = 80; reasons = [f"Near_Resistance pct={pct_pos:.2f}","RSI_High"]
        return {"signal":"BUY_PE","score":score,"reasons":reasons,"strategy":"RANGE_BOUND"}

    return {"signal":"NO_TRADE","score":score,"reasons":reasons,"strategy":"RANGE_BOUND"}

def generate_signal(candles):
    """
    Main signal generator — Multi-strategy AI
    candles: list of dicts {o,h,l,c,v}
    Returns: signal dict
    """
    if len(candles) < 21:
        return {"signal":"NO_TRADE","score":0,"reason":"Insufficient data"}

    opens  = [c['o'] for c in candles]
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    closes = [c['c'] for c in candles]
    vols   = [c.get('v',0) for c in candles]

    # Compute indicators
    ema9_val  = ema(closes, 9)
    ema21_val = ema(closes, 21)
    rsi_val   = rsi(closes, 14)
    atr_val   = atr(highs, lows, closes, 14)
    vwap_val  = vwap(highs, lows, closes, vols)
    trend     = higher_high_lower_low(highs, lows)
    vol_spike = volume_spike(vols)
    vol_reg   = detect_volatility_regime(atr_val, closes[-1])

    # Select strategy
    strategy = select_strategy(trend, vol_reg, vol_spike)

    # Run all 3 strategies
    breakout = breakout_signal(closes, highs, lows, vols, vwap_val, rsi_val, ema9_val, ema21_val)
    reversal = reversal_signal(closes, highs, lows, rsi_val, vwap_val, atr_val)
    range_bd = range_bound_signal(closes, highs, lows, rsi_val, vwap_val, atr_val)

    # Select best signal based on active strategy
    strategy_map = {
        "BREAKOUT": breakout,
        "REVERSAL": reversal,
        "RANGE_BOUND": range_bd
    }
    best = strategy_map[strategy]

    # Consensus boost
    signals = [breakout, reversal, range_bd]
    agree = sum(1 for s in signals if s["signal"] == best["signal"] and best["signal"] != "NO_TRADE")
    if agree > 1: best["score"] = min(best["score"] + 10 * (agree-1), 100)

    best.update({
        "price": closes[-1],
        "ema9": ema9_val,
        "ema21": ema21_val,
        "rsi": rsi_val,
        "atr": atr_val,
        "vwap": vwap_val,
        "trend": trend,
        "vol_regime": vol_reg,
        "vol_spike": vol_spike,
        "strategies_agree": agree,
        "active_strategy": strategy
    })
    return best
