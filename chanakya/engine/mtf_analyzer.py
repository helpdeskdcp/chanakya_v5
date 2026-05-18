# engine/mtf_analyzer.py
# Multi-Timeframe Alignment Engine
# Timeframes: 1m, 3m, 5m, 15m
# Trade only when 3/4 or 4/4 timeframes align

import logging
logger = logging.getLogger("mtf")

# Angel One API interval strings
TF_MAP = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
}

def _tf_bias(candles, tf_label):
    """
    Single timeframe bias detection.
    Returns: {"tf","bias","ema_cross","rsi","vwap_bias","strength","trend"}
    bias = "BUY" | "SELL" | "NEUTRAL"
    strength = 0-100
    """
    try:
        from engine.indicators import ema, rsi, vwap, atr, supertrend
        if not candles or len(candles) < 10:
            return {"tf": tf_label, "bias": "NEUTRAL", "strength": 0}

        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        ltp    = closes[-1]

        e9  = ema(closes, 9)
        e21 = ema(closes, 21)
        e50 = ema(closes[-50:] if len(closes) >= 50 else closes, min(50, len(closes)))
        r   = rsi(closes)
        vw  = vwap(candles[-50:] if len(candles) >= 50 else candles)
        st  = supertrend(candles)

        score = 0
        bias  = "NEUTRAL"

        bull_signals = 0
        bear_signals = 0

        # EMA cross
        if e9 > e21:   bull_signals += 1
        elif e9 < e21: bear_signals += 1

        # EMA pyramid (e9 > e21 > e50)
        if e9 > e21 > e50:   bull_signals += 1
        elif e9 < e21 < e50: bear_signals += 1

        # Price vs VWAP
        if vw and ltp > vw:  bull_signals += 1
        elif vw and ltp < vw: bear_signals += 1

        # RSI
        if 45 < r < 70:   bull_signals += 1
        elif 30 < r < 55: bear_signals += 1

        # Supertrend
        if st == "UP":   bull_signals += 1
        elif st == "DOWN": bear_signals += 1

        # Price momentum (last 3 candles)
        if len(closes) >= 4:
            if closes[-1] > closes[-4]: bull_signals += 1
            else: bear_signals += 1

        total = bull_signals + bear_signals
        if total == 0:
            return {"tf": tf_label, "bias": "NEUTRAL", "strength": 0}

        if bull_signals > bear_signals:
            bias = "BUY"
            strength = round(bull_signals / total * 100)
        elif bear_signals > bull_signals:
            bias = "SELL"
            strength = round(bear_signals / total * 100)
        else:
            bias = "NEUTRAL"
            strength = 50

        return {
            "tf":         tf_label,
            "bias":       bias,
            "strength":   strength,
            "ema_cross":  "BULL" if e9 > e21 else "BEAR",
            "rsi":        round(r, 1),
            "vwap_bias":  "ABOVE" if (vw and ltp > vw) else "BELOW",
            "supertrend": st,
            "e9":         round(e9, 2),
            "e21":        round(e21, 2),
            "ltp":        round(ltp, 2),
        }
    except Exception as e:
        logger.debug(f"TF bias {tf_label}: {e}")
        return {"tf": tf_label, "bias": "NEUTRAL", "strength": 0}


def mtf_analyze(broker, token, exchange, symbol):
    """
    Full MTF analysis for a symbol.
    Fetches 1m/3m/5m/15m candles and checks alignment.

    Returns:
    {
        "aligned": True/False,
        "direction": "BUY"/"SELL"/"NEUTRAL",
        "score": 0-100,
        "timeframes": {1m:{...}, 3m:{...}, 5m:{...}, 15m:{...}},
        "aligned_count": 3,
        "total_tf": 4,
        "reason": "3/4 timeframes aligned BUY",
        "quality": "STRONG"/"MODERATE"/"WEAK"/"NO_TRADE"
    }
    """
    from data_stream.cache import get as cget, set as cset

    results = {}
    tf_configs = [
        ("1m",  "ONE_MINUTE",      1),
        ("3m",  "THREE_MINUTE",    1),
        ("5m",  "FIVE_MINUTE",     2),
        ("15m", "FIFTEEN_MINUTE",  3),
    ]

    for tf_label, api_interval, days in tf_configs:
        try:
            ckey = f"candles_{symbol}_{tf_label}"
            candles = cget(ckey)
            if not candles:
                candles = broker.get_candles(token, exchange, api_interval, days=days)
                if candles:
                    ttl = 30 if tf_label in ("1m","3m") else 60
                    cset(ckey, candles, ttl=ttl)
            results[tf_label] = _tf_bias(candles, tf_label)
        except Exception as e:
            logger.debug(f"MTF fetch {symbol} {tf_label}: {e}")
            results[tf_label] = {"tf": tf_label, "bias": "NEUTRAL", "strength": 0}

    # Count alignment
    buy_count  = sum(1 for r in results.values() if r["bias"] == "BUY")
    sell_count = sum(1 for r in results.values() if r["bias"] == "SELL")
    total_tf   = len(results)

    # Weighted score — 15m has highest weight
    weights = {"1m": 0.15, "3m": 0.20, "5m": 0.30, "15m": 0.35}
    weighted_score = 0
    direction = "NEUTRAL"

    if buy_count >= sell_count:
        direction = "BUY"
        for tf, w in weights.items():
            r = results.get(tf, {})
            if r.get("bias") == "BUY":
                weighted_score += r.get("strength", 0) * w
    else:
        direction = "SELL"
        for tf, w in weights.items():
            r = results.get(tf, {})
            if r.get("bias") == "SELL":
                weighted_score += r.get("strength", 0) * w

    score = round(weighted_score)
    aligned_count = max(buy_count, sell_count)
    aligned = aligned_count >= 3  # 3/4 minimum

    # Quality classification
    if aligned_count == 4 and score >= 70:
        quality = "STRONG"
    elif aligned_count >= 3 and score >= 55:
        quality = "MODERATE"
    elif aligned_count >= 3:
        quality = "WEAK"
    else:
        quality = "NO_TRADE"
        aligned = False

    reason = f"{aligned_count}/{total_tf} timeframes aligned {direction} | score={score}"

    logger.info(f"MTF {symbol}: {reason} [{quality}]")

    return {
        "aligned":       aligned,
        "direction":     direction,
        "score":         score,
        "timeframes":    results,
        "aligned_count": aligned_count,
        "total_tf":      total_tf,
        "reason":        reason,
        "quality":       quality,
        "buy_count":     buy_count,
        "sell_count":    sell_count,
    }


def mtf_score_boost(sig, mtf_result):
    """
    MTF result based score adjustment for existing signal.
    Call this from scanner._analyze or scan_all.
    """
    if not mtf_result:
        return sig

    direction   = sig.get("direction", "BUY")
    mtf_dir     = mtf_result.get("direction", "NEUTRAL")
    quality     = mtf_result.get("quality", "NO_TRADE")
    aligned_cnt = mtf_result.get("aligned_count", 0)

    sig["mtf_aligned"]  = mtf_result.get("aligned", False)
    sig["mtf_quality"]  = quality
    sig["mtf_count"]    = f"{aligned_cnt}/4"
    sig["mtf_score"]    = mtf_result.get("score", 0)
    sig["mtf_reason"]   = mtf_result.get("reason", "")
    sig["mtf_tf"]       = mtf_result.get("timeframes", {})

    if mtf_dir != direction:
        # MTF disagrees — penalize heavily
        sig["score"] = max(0, sig["score"] - 10)  # Reduced penalty
        sig["fake"]  = sig.get("fake", []) + ["MTF_CONFLICT"]
        return sig

    # MTF agrees — boost
    if quality == "STRONG":
        sig["score"] = min(100, sig["score"] + 25)
    elif quality == "MODERATE":
        sig["score"] = min(100, sig["score"] + 15)
    elif quality == "WEAK":
        sig["score"] = min(100, sig["score"] + 5)
    else:
        # NO_TRADE
        sig["score"] = max(0, sig["score"] - 5)  # Reduced penalty
        sig["fake"]  = sig.get("fake", []) + ["MTF_NO_ALIGN"]

    return sig
