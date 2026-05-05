"""
Chanakya AI v5 — Smart Money Concepts Engine
Level 1: Volume Profile, Market Structure, Order Blocks, Liquidity, BOS/CHOCH
"""
import logging
logger = logging.getLogger(__name__)

# ── 1. Volume Profile ─────────────────────────────────
def volume_profile(candles, bins=20):
    """POC, VAH, VAL calculate करतो"""
    try:
        if len(candles) < 10: return {}
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        total_high = max(highs); total_low = min(lows)
        if total_high == total_low: return {}
        bin_size = (total_high - total_low) / bins
        profile = {}
        for i, c in enumerate(candles):
            h,l,v = float(c[2]),float(c[3]),float(c[5])
            # distribute volume across price bins
            for b in range(bins):
                bin_low  = total_low + b * bin_size
                bin_high = bin_low + bin_size
                overlap = max(0, min(h, bin_high) - max(l, bin_low))
                if overlap > 0 and (h - l) > 0:
                    profile[b] = profile.get(b, 0) + v * overlap / (h - l)
        if not profile: return {}
        poc_bin  = max(profile, key=profile.get)
        poc      = round(total_low + (poc_bin + 0.5) * bin_size, 2)
        # Value Area = 70% of total volume
        total_vol = sum(profile.values())
        va_target = total_vol * 0.70
        sorted_bins = sorted(profile.items(), key=lambda x: -x[1])
        va_vol = 0; va_bins = []
        for b, v in sorted_bins:
            va_vol += v; va_bins.append(b)
            if va_vol >= va_target: break
        vah = round(total_low + (max(va_bins) + 1) * bin_size, 2)
        val = round(total_low + min(va_bins) * bin_size, 2)
        ltp = float(candles[-1][4])
        return {
            "poc": poc, "vah": vah, "val": val,
            "position": "ABOVE_POC" if ltp > poc else "BELOW_POC",
            "in_value": val <= ltp <= vah,
        }
    except Exception as e:
        logger.debug("volume_profile: %s", e); return {}

# ── 2. Market Structure ───────────────────────────────
def market_structure(candles, lookback=20):
    """HH, HL, LH, LL detect करतो → trend"""
    try:
        if len(candles) < lookback: return "UNKNOWN"
        highs = [float(c[2]) for c in candles[-lookback:]]
        lows  = [float(c[3]) for c in candles[-lookback:]]
        n = len(highs)
        # Find swing highs/lows (simplified)
        swing_highs = []
        swing_lows  = []
        for i in range(2, n-2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append(lows[i])
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1] > swing_highs[-2]  # Higher High
            hl = swing_lows[-1]  > swing_lows[-2]   # Higher Low
            lh = swing_highs[-1] < swing_highs[-2]  # Lower High
            ll = swing_lows[-1]  < swing_lows[-2]   # Lower Low
            if hh and hl: return "UPTREND"    # HH + HL
            if lh and ll: return "DOWNTREND"  # LH + LL
            if hh and ll: return "CHOPPY"
            if lh and hl: return "RANGING"
        # Fallback: simple comparison
        if highs[-1] > highs[0] and lows[-1] > lows[0]: return "UPTREND"
        if highs[-1] < highs[0] and lows[-1] < lows[0]: return "DOWNTREND"
        return "RANGING"
    except Exception as e:
        logger.debug("market_structure: %s", e); return "UNKNOWN"

# ── 3. Order Blocks ───────────────────────────────────
def find_order_blocks(candles, lookback=30):
    """Institutional order blocks शोधतो"""
    try:
        if len(candles) < 10: return {}
        recent = candles[-lookback:] if len(candles) >= lookback else candles
        ltp = float(candles[-1][4])
        bull_ob = None  # Bullish OB: last bearish candle before big up move
        bear_ob = None  # Bearish OB: last bullish candle before big down move
        for i in range(len(recent)-3, 1, -1):
            o = float(recent[i][1]); c = float(recent[i][4])
            h = float(recent[i][2]); l = float(recent[i][3])
            # Next candle size
            nc = float(recent[i+1][4]); no = float(recent[i+1][1])
            move = abs(nc - no)
            avg_candle = sum(abs(float(recent[j][4])-float(recent[j][1]))
                           for j in range(len(recent))) / len(recent)
            # Bullish OB: bearish candle followed by large bullish candle
            if c < o and nc > no and move > avg_candle * 1.5:
                if bull_ob is None and ltp > h:  # Price above OB
                    bull_ob = {"high": h, "low": l, "strength": round(move/avg_candle,1)}
            # Bearish OB: bullish candle followed by large bearish candle
            if c > o and nc < no and move > avg_candle * 1.5:
                if bear_ob is None and ltp < l:  # Price below OB
                    bear_ob = {"high": h, "low": l, "strength": round(move/avg_candle,1)}
        return {"bull_ob": bull_ob, "bear_ob": bear_ob}
    except Exception as e:
        logger.debug("order_blocks: %s", e); return {}

# ── 4. Break of Structure ─────────────────────────────
def detect_bos(candles, lookback=20):
    """BOS (Break of Structure) / CHOCH (Change of Character)"""
    try:
        if len(candles) < lookback: return "NONE"
        recent = candles[-lookback:]
        highs = [float(c[2]) for c in recent]
        lows  = [float(c[3]) for c in recent]
        ltp   = float(candles[-1][4])
        prev_high = max(highs[:-3])
        prev_low  = min(lows[:-3])
        curr_high = float(candles[-1][2])
        curr_low  = float(candles[-1][3])
        if curr_high > prev_high: return "BOS_BULL"   # Bullish BOS
        if curr_low  < prev_low:  return "BOS_BEAR"   # Bearish BOS
        return "NONE"
    except Exception as e:
        logger.debug("detect_bos: %s", e); return "NONE"

# ── 5. Liquidity Zones ────────────────────────────────
def liquidity_zones(candles, lookback=50):
    """Equal highs/lows = liquidity (stop hunts होतात)"""
    try:
        if len(candles) < 10: return {}
        recent = candles[-lookback:] if len(candles) >= lookback else candles
        highs = [float(c[2]) for c in recent]
        lows  = [float(c[3]) for c in recent]
        ltp   = float(candles[-1][4])
        atr_val = sum(h-l for h,l in zip(highs,lows)) / len(highs)
        tolerance = atr_val * 0.1
        # Find equal highs (sell-side liquidity)
        eq_highs = []
        for i in range(len(highs)):
            for j in range(i+1, len(highs)):
                if abs(highs[i] - highs[j]) < tolerance:
                    eq_highs.append(round((highs[i]+highs[j])/2, 2))
        # Find equal lows (buy-side liquidity)
        eq_lows = []
        for i in range(len(lows)):
            for j in range(i+1, len(lows)):
                if abs(lows[i] - lows[j]) < tolerance:
                    eq_lows.append(round((lows[i]+lows[j])/2, 2))
        # Nearest zones
        sell_liq = sorted(set(eq_highs), key=lambda x: abs(x-ltp))[:2]
        buy_liq  = sorted(set(eq_lows),  key=lambda x: abs(x-ltp))[:2]
        return {"sell_liquidity": sell_liq, "buy_liquidity": buy_liq}
    except Exception as e:
        logger.debug("liquidity: %s", e); return {}

# ── 6. Master SMC Score ───────────────────────────────
def smc_score(candles, direction):
    """Smart Money Confluence Score (0-100)"""
    try:
        score = 0
        details = {}
        # Market Structure
        ms = market_structure(candles)
        details["structure"] = ms
        if direction == "BUY"  and ms == "UPTREND":   score += 30
        if direction == "SELL" and ms == "DOWNTREND":  score += 30
        if ms in ["RANGING", "CHOPPY"]:                score += 5
        # BOS
        bos = detect_bos(candles)
        details["bos"] = bos
        if direction == "BUY"  and bos == "BOS_BULL": score += 25
        if direction == "SELL" and bos == "BOS_BEAR":  score += 25
        # Volume Profile
        vp = volume_profile(candles)
        details["vp"] = vp
        if vp:
            if direction == "BUY"  and vp.get("position") == "ABOVE_POC": score += 20
            if direction == "SELL" and vp.get("position") == "BELOW_POC":  score += 20
            if not vp.get("in_value"): score += 10  # Outside value = momentum
        # Order Blocks
        ob = find_order_blocks(candles)
        details["ob"] = ob
        if direction == "BUY"  and ob.get("bull_ob"): score += 15
        if direction == "SELL" and ob.get("bear_ob"):  score += 15
        return min(score, 100), details
    except Exception as e:
        logger.debug("smc_score: %s", e); return 0, {}
