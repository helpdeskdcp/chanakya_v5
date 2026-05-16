import statistics

def detect_regime(candles):
    """
    Detect market regime from candles
    candles = list of dicts with:
    high, low, close, volume
    """

    try:
        if not candles or len(candles) < 20:
            return {
                "regime": "UNKNOWN",
                "volatility": 0,
                "trend_strength": 0
            }

        closes = [float(c["close"]) for c in candles]
        highs  = [float(c["high"]) for c in candles]
        lows   = [float(c["low"]) for c in candles]

        ranges = [h - l for h, l in zip(highs, lows)]

        avg_range = statistics.mean(ranges[-10:])
        avg_close = statistics.mean(closes[-10:])

        volatility_pct = (avg_range / avg_close) * 100

        ema_fast = statistics.mean(closes[-5:])
        ema_slow = statistics.mean(closes[-20:])

        trend_strength = abs(ema_fast - ema_slow)

        # ── Regime Classification ──

        if volatility_pct > 2.5:
            regime = "VOLATILE"

        elif trend_strength > avg_close * 0.01:
            regime = "TRENDING"

        elif volatility_pct < 0.5:
            regime = "DEAD"

        else:
            regime = "CHOPPY"

        return {
            "regime": regime,
            "volatility": round(volatility_pct, 2),
            "trend_strength": round(trend_strength, 2)
        }

    except Exception as e:
        return {
            "regime": "ERROR",
            "error": str(e)
        }
