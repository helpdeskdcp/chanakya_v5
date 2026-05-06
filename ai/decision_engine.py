"""
Chanakya Decision Fusion Engine™
Combines: Rule-based + XGBoost + LLM → Final Signal
Mythos-style multi-layer validation
"""
import logging, json, time
logger = logging.getLogger(__name__)

class ChanakyaDecisionEngine:
    def __init__(self):
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3
        self.daily_trades = 0
        self.max_daily_trades = 5
        self.trade_results = []

    def can_trade(self):
        """Safety checks before any trade"""
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, f"🛑 {self.consecutive_losses} consecutive losses — cooling off"
        if self.daily_trades >= self.max_daily_trades:
            return False, f"🛑 Max {self.max_daily_trades} trades/day reached"
        return True, "OK"

    def rule_based_score(self, features):
        """Layer 1: Rule-based signal scoring"""
        score = 0
        reasons = []
        direction = None

        rsi = features.get('rsi14', 50)
        vwap_side = features.get('vwap_side', 0)
        ema_trend = features.get('ema_trend', 0)
        vol_spike = features.get('vol_spike', 0)
        structure = features.get('structure', 0)
        mom5 = features.get('mom5', 0)
        body_pct = features.get('body_pct', 0)
        vwap_dist = features.get('vwap_dist_pct', 0)

        # BULLISH conditions
        bull_score = 0
        if rsi < 35:           bull_score += 25; reasons.append(f"RSI_Oversold={rsi}")
        elif rsi < 45:         bull_score += 15; reasons.append(f"RSI_Low={rsi}")
        if vwap_side == 1:     bull_score += 20; reasons.append("Above_VWAP")
        if vwap_dist < -1.5:   bull_score += 25; reasons.append(f"VWAP_Gap={vwap_dist:.1f}%")
        if ema_trend == 1:     bull_score += 15; reasons.append("EMA_Bullish")
        if vol_spike:          bull_score += 15; reasons.append("Vol_Spike")
        if structure >= 1:     bull_score += 10; reasons.append("HH_HL")
        if mom5 > 0.002:       bull_score += 10; reasons.append("Momentum+")

        # BEARISH conditions
        bear_score = 0
        if rsi > 65:           bear_score += 25; reasons.append(f"RSI_Overbought={rsi}")
        elif rsi > 55:         bear_score += 15
        if vwap_side == -1:    bear_score += 20; reasons.append("Below_VWAP")
        if vwap_dist > 1.5:    bear_score += 25; reasons.append(f"VWAP_Gap+={vwap_dist:.1f}%")
        if ema_trend == -1:    bear_score += 15; reasons.append("EMA_Bearish")
        if structure <= -1:    bear_score += 10; reasons.append("LH_LL")
        if mom5 < -0.002:      bear_score += 10; reasons.append("Momentum-")

        if bull_score > bear_score and bull_score >= 35:
            direction = "BUY_CE"; score = bull_score
        elif bear_score > bull_score and bear_score >= 35:
            direction = "BUY_PE"; score = bear_score
        else:
            direction = "NO_TRADE"; score = max(bull_score, bear_score)

        return {"signal": direction, "score": score, "reasons": reasons,
                "bull_score": bull_score, "bear_score": bear_score}

    def ml_score(self, features):
        """Layer 2: XGBoost ML prediction"""
        try:
            import pickle, numpy as np, os
            model_path = "data/ml_model.pkl"
            if not os.path.exists(model_path):
                return {"signal":"NO_TRADE","confidence":50,"ml_available":False}

            with open(model_path,'rb') as f: model = pickle.load(f)
            # Feature vector (must match training)
            fv = np.array([[
                features.get('rsi14',50),
                features.get('rsi7',50),
                features.get('ema_cross_pct',0),
                features.get('vwap_dist_pct',0),
                features.get('vol_ratio',1),
                features.get('atr_pct',1),
                features.get('mom5',0),
                features.get('mom10',0),
                features.get('structure',0),
                features.get('body_pct',50),
                features.get('is_bull',0),
                features.get('bull_streak',0),
                features.get('bear_streak',0),
                features.get('time_sin',0),
                features.get('time_cos',0),
                features.get('is_morning',0),
                features.get('price_vs_ema9',0),
                features.get('price_vs_ema21',0),
            ]])
            pred = model.predict(fv)[0]
            proba = model.predict_proba(fv)[0]
            confidence = int(max(proba)*100)
            label_map = {0:"NO_TRADE",1:"BUY_CE",2:"BUY_PE"}
            return {"signal":label_map.get(pred,"NO_TRADE"),
                    "confidence":confidence,"ml_available":True}
        except Exception as e:
            return {"signal":"NO_TRADE","confidence":50,"ml_available":False,"error":str(e)}

    def llm_validate(self, features, rule_signal, ml_signal):
        """Layer 3: LLM validation via Groq"""
        try:
            from ai.groq_client import get_client
            from ai.feature_engine import features_to_prompt
            client = get_client()
            if not client: return {"approved":True,"confidence":70,"reason":"LLM unavailable"}

            ctx = features_to_prompt(features)
            prompt = f"""You are CHANAKYA — India's most advanced trading AI.

{ctx}

RULE ENGINE: {rule_signal['signal']} (Score:{rule_signal['score']})
ML ENGINE: {ml_signal['signal']} (Confidence:{ml_signal['confidence']}%)

Your job: Validate this trade signal. Check for:
1. Fake breakout / bull trap / bear trap?
2. Low volume manipulation?
3. News/event risk (expiry day)?
4. Overall market structure alignment?

Respond ONLY in this format:
DECISION: [APPROVE/REJECT/HOLD]
CONFIDENCE: [0-100]
REASON: [one line explanation]
RISK: [LOW/MEDIUM/HIGH]
ADJUSTMENT: [+10/-10/0] (confidence adjustment)"""

            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role":"user","content":prompt}],
                max_tokens=120, temperature=0.1
            )
            text = r.choices[0].message.content.strip()
            import re
            decision = re.search(r'DECISION:\s*(\w+)', text)
            conf = re.search(r'CONFIDENCE:\s*(\d+)', text)
            reason = re.search(r'REASON:\s*(.+)', text)
            risk = re.search(r'RISK:\s*(\w+)', text)
            adj = re.search(r'ADJUSTMENT:\s*([+-]?\d+)', text)
            return {
                "approved": decision.group(1).upper() == "APPROVE" if decision else True,
                "confidence": int(conf.group(1)) if conf else 70,
                "reason": reason.group(1).strip() if reason else "",
                "risk": risk.group(1) if risk else "MEDIUM",
                "adjustment": int(adj.group(1)) if adj else 0,
            }
        except Exception as e:
            err = str(e)
            # Rate limit — approve with reduced confidence
            if '429' in err or 'rate' in err.lower():
                return {"approved":True,"confidence":60,"reason":"LLM_RateLimit_Bypassed","risk":"MEDIUM","adjustment":-5}
            return {"approved":True,"confidence":60,"reason":err,"risk":"MEDIUM","adjustment":0}

    def fuse(self, features, candles=None):
        """
        MAIN FUSION ENGINE
        Combines all 3 layers → Final signal
        """
        can, reason = self.can_trade()
        if not can:
            return {"signal":"NO_TRADE","score":0,"reason":reason,"blocked":True}

        # Layer 1: Rule-based
        rule = self.rule_based_score(features)

        # Layer 2: ML
        ml = self.ml_score(features)

        # Layer 3: LLM (only if rule or ML shows signal)
        llm = {"approved":True,"confidence":70,"reason":"","adjustment":0,"risk":"MEDIUM"}
        if rule['signal'] != "NO_TRADE" or ml['signal'] != "NO_TRADE":
            llm = self.llm_validate(features, rule, ml)

        # === FUSION LOGIC ===
        # Weights: Rule=40%, ML=30%, LLM=30%
        rule_w = 0.40
        ml_w   = 0.30
        llm_w  = 0.30

        rule_score = rule['score'] if rule['signal'] != "NO_TRADE" else 0
        ml_score   = ml['confidence'] if ml['signal'] != "NO_TRADE" else 0
        llm_score  = llm['confidence'] if llm['approved'] else 0

        # Adjust weights if ML unavailable
        if not ml.get('ml_available', False):
            rule_w = 0.55; ml_w = 0.10; llm_w = 0.35
        fused_score = int(
            rule_score * rule_w +
            ml_score   * ml_w   +
            llm_score  * llm_w  +
            llm.get('adjustment', 0)
        )
        fused_score = max(0, min(100, fused_score))

        # Signal agreement
        signals = [rule['signal'], ml['signal']]
        agree_buy  = signals.count("BUY_CE")
        agree_sell = signals.count("BUY_PE")

        # LLM: only block if rule is WEAK (<40) AND LLM rejects
        if not llm["approved"] and rule["score"] < 40:
            fused_score = max(0, fused_score - 5)
        if agree_buy >= 1 and fused_score >= 30:
            final_signal = 'BUY_CE'
        elif agree_sell >= 1 and fused_score >= 30:
            final_signal = 'BUY_PE'
        elif rule['signal'] != 'NO_TRADE' and fused_score >= 25:
            final_signal = rule['signal']
        else:
            final_signal = "NO_TRADE"

        return {
            "signal": final_signal,
            "score":  fused_score,
            "rule":   rule,
            "ml":     ml,
            "llm":    llm,
            "reasons": rule['reasons'],
            "risk":   llm.get('risk','MEDIUM'),
            "agree":  max(agree_buy, agree_sell),
            "features": features,
        }

    def record_result(self, pnl):
        """Update consecutive loss counter"""
        self.trade_results.append(pnl)
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self.daily_trades += 1

# Singleton
_engine = None
def get_engine():
    global _engine
    if not _engine: _engine = ChanakyaDecisionEngine()
    return _engine
