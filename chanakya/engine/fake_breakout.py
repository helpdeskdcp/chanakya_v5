# engine/fake_breakout.py
# Fake Breakout & Trap Detector
# Detects: Bull Trap, Bear Trap, Weak Breakout, Exhaustion, Stop Hunt

import logging
logger = logging.getLogger("fake_breakout")

def detect(candles, direction, ltp, atr, vol_ratio, rsi_val, vwap_val=None):
    """
    Returns:
    {
        "is_fake": True/False,
        "confidence": 0-100,
        "traps": ["BullTrap","WeakBreakout",...],
        "penalty": 0-50   (score penalty)
    }
    """
    traps   = []
    penalty = 0

    if not candles or len(candles) < 5:
        return {"is_fake": False, "confidence": 0, "traps": [], "penalty": 0}

    closes = [float(c[4]) for c in candles]
    highs  = [float(c[2]) for c in candles]
    lows   = [float(c[3]) for c in candles]
    vols   = [float(c[5]) for c in candles]
    opens  = [float(c[1]) for c in candles]

    c0, c1, c2 = closes[-1], closes[-2], closes[-3]
    h0, h1, h2 = highs[-1],  highs[-2],  highs[-3]
    l0, l1, l2 = lows[-1],   lows[-2],   lows[-3]
    o0, o1     = opens[-1],  opens[-2]
    v0, v1, v2 = vols[-1],   vols[-2],   vols[-3]

    avg_vol = sum(vols[-10:-1]) / 9 if len(vols) >= 10 else sum(vols) / len(vols)
    candle_range = h0 - l0
    avg_range = sum(highs[i] - lows[i] for i in range(-6, -1)) / 5 if len(candles) >= 6 else atr

    # ── 1. Bull Trap Detection ─────────────────────────────────────
    # Price breaks recent high but closes back below it
    if direction == "BUY":
        recent_high = max(highs[-6:-1]) if len(highs) >= 6 else h1
        if h0 > recent_high and c0 < recent_high:
            traps.append("BullTrap")
            penalty += 25
        # Wick rejection — long upper wick (>60% of candle range)
        upper_wick = h0 - max(c0, o0)
        if candle_range > 0 and upper_wick / candle_range > 0.6:
            traps.append("UpperWickRejection")
            penalty += 15

    # ── 2. Bear Trap Detection ─────────────────────────────────────
    if direction == "SELL":
        recent_low = min(lows[-6:-1]) if len(lows) >= 6 else l1
        if l0 < recent_low and c0 > recent_low:
            traps.append("BearTrap")
            penalty += 25
        # Long lower wick rejection
        lower_wick = min(c0, o0) - l0
        if candle_range > 0 and lower_wick / candle_range > 0.6:
            traps.append("LowerWickRejection")
            penalty += 15

    # ── 3. Weak Breakout ──────────────────────────────────────────
    # Breakout candle volume < average (no institutional participation)
    if vol_ratio < 0.8:
        traps.append("WeakVolBreakout")
        penalty += 20
    elif vol_ratio < 1.0:
        traps.append("BelowAvgVol")
        penalty += 10

    # ── 4. Exhaustion Move ────────────────────────────────────────
    # 3+ consecutive same-direction candles + RSI extreme
    if direction == "BUY":
        consec_up = sum(1 for i in range(-4, 0) if closes[i] > closes[i-1])
        if consec_up >= 3 and rsi_val > 72:
            traps.append("BuyExhaustion")
            penalty += 20
        if rsi_val > 80:
            traps.append("RSIOverbought")
            penalty += 15
    else:
        consec_dn = sum(1 for i in range(-4, 0) if closes[i] < closes[i-1])
        if consec_dn >= 3 and rsi_val < 28:
            traps.append("SellExhaustion")
            penalty += 20
        if rsi_val < 20:
            traps.append("RSIOversold")
            penalty += 15

    # ── 5. Stop Hunt / Liquidity Grab ────────────────────────────
    # Candle spikes below/above key level and snaps back
    if direction == "BUY":
        # StopHunt DOWN = Smart money trap → actually bullish, no penalty
        if l0 < l1 and c0 > l1:
            traps.append("StopHuntDown_Bullish")  # informational only
    else:
        # StopHunt UP = Smart money trap → actually bearish, no penalty
        if h0 > h1 and c0 < h1:
            traps.append("StopHuntUp_Bearish")  # informational only

    # ── 6. Overextended Entry ─────────────────────────────────────
    # Price too far from VWAP
    if vwap_val and vwap_val > 0:
        vwap_dist = abs(ltp - vwap_val) / vwap_val * 100
        if vwap_dist > 1.5:
            traps.append("OverextendedVWAP")
            penalty += 15
        elif vwap_dist > 1.0:
            traps.append("FarFromVWAP")
            penalty += 8

    # ── 7. Candle Size Anomaly ────────────────────────────────────
    # Abnormally large candle = chasing move
    if avg_range > 0 and candle_range > avg_range * 2.5:
        traps.append("AbnormalCandleSize")
        penalty += 10

    # ── 8. Doji / Indecision at breakout ─────────────────────────
    body = abs(c0 - o0)
    if candle_range > 0 and body / candle_range < 0.2:
        traps.append("DojiIndecision")
        penalty += 12

    # ── 9. Gap & Trap ─────────────────────────────────────────────
    # Price gapped up/down but immediately reversed
    if direction == "BUY":
        gap_up = o0 > c1 * 1.003
        if gap_up and c0 < o0:
            traps.append("GapAndTrap")
            penalty += 18
    else:
        gap_dn = o0 < c1 * 0.997
        if gap_dn and c0 > o0:
            traps.append("GapAndTrap")
            penalty += 18

    # ── Final scoring ──────────────────────────────────────────────
    penalty    = min(penalty, 60)  # cap at 60
    confidence = min(penalty * 2, 100)
    is_fake    = penalty >= 30     # 30+ penalty = likely fake

    if traps:
        logger.debug(f"FakeDetect [{direction}]: {traps} | penalty={penalty}")

    return {
        "is_fake":    is_fake,
        "confidence": confidence,
        "traps":      traps,
        "penalty":    penalty,
    }


def apply_fake_filter(sig, candles):
    """
    Apply fake breakout detection to existing signal.
    Updates sig["score"], sig["fake"], sig["fake_detail"]
    """
    try:
        result = detect(
            candles    = candles,
            direction  = sig.get("direction", "BUY"),
            ltp        = sig.get("ltp", 0),
            atr        = sig.get("atr", 0),
            vol_ratio  = sig.get("vol_ratio", 1.0),
            rsi_val    = sig.get("rsi", 50),
            vwap_val   = sig.get("vwap", 0),
        )

        sig["fake"]        = sig.get("fake", []) + result["traps"]
        sig["fake_detail"] = result
        sig["score"]       = max(0, sig["score"] - result["penalty"])

        if result["is_fake"]:
            sig["fake_breakout"] = True
            logger.info(f"🚫 FakeBreakout {sig.get('symbol','')} {sig.get('direction','')} "
                       f"penalty={result['penalty']} traps={result['traps']}")
        else:
            sig["fake_breakout"] = False

    except Exception as e:
        logger.debug(f"apply_fake_filter error: {e}")

    return sig
