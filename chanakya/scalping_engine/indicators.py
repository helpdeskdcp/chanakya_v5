"""
Chanakya Scalping Engine — Indicators Module
SEBI Math Framework: VWAP, RSI, EMA, ATR, Volume
"""
import numpy as np

def ema(prices, period):
    if len(prices) < period: return prices[-1] if prices else 0
    k = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period
    for p in prices[period:]:
        ema_val = p * k + ema_val * (1 - k)
    return round(ema_val, 2)

def rsi(prices, period=14):
    if len(prices) < period + 1: return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.001
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def atr(highs, lows, closes, period=14):
    if len(closes) < 2: return 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    if not trs: return 0
    return round(sum(trs[-period:]) / min(len(trs), period), 2)

def vwap(highs, lows, closes, volumes):
    if not volumes or sum(volumes) == 0: return closes[-1] if closes else 0
    typical = [(h+l+c)/3 for h,l,c in zip(highs, lows, closes)]
    tp_vol = sum(t*v for t,v in zip(typical, volumes))
    total_vol = sum(volumes)
    return round(tp_vol / total_vol, 2) if total_vol > 0 else closes[-1]

def volume_spike(volumes, period=20, threshold=2.0):
    if len(volumes) < period: return False
    avg = sum(volumes[-period-1:-1]) / period
    return volumes[-1] > avg * threshold if avg > 0 else False

def higher_high_lower_low(highs, lows, lookback=5):
    if len(highs) < lookback + 1: return "NEUTRAL"
    recent_h = highs[-lookback:]
    recent_l = lows[-lookback:]
    if recent_h[-1] > max(recent_h[:-1]) and recent_l[-1] > min(recent_l[:-1]):
        return "UPTREND"
    if recent_h[-1] < max(recent_h[:-1]) and recent_l[-1] < min(recent_l[:-1]):
        return "DOWNTREND"
    return "SIDEWAYS"

def expectancy(win_rate, avg_win, avg_loss):
    """SEBI Math: Expectancy = (WR × Avg_Win) - (LR × Avg_Loss)"""
    loss_rate = 1 - win_rate
    return round((win_rate * avg_win) - (loss_rate * avg_loss), 4)

def position_size(capital, risk_pct, entry, stop_loss, lot_size=1):
    """SEBI Position Sizing Formula"""
    risk_amt = capital * risk_pct / 100
    pts_risk = abs(entry - stop_loss)
    if pts_risk == 0: return lot_size
    qty = int(risk_amt / pts_risk)
    return max(lot_size, (qty // lot_size) * lot_size)

def kelly_criterion(win_rate, rr_ratio):
    """Advanced position sizing"""
    if rr_ratio == 0: return 0
    q = 1 - win_rate
    return max(0, round(win_rate - (q / rr_ratio), 4))
