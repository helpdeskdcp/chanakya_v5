import numpy as np
import logging
logger = logging.getLogger(__name__)

_model = None
_trained = False

def build_features(candles):
    try:
        from engine.indicators import ema, rsi, macd, vwap, atr
        if len(candles) < 30: return None
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        vols   = [float(c[5]) for c in candles]
        ltp = closes[-1]
        r   = rsi(closes)
        e9  = ema(closes,9); e21 = ema(closes,21); e50 = ema(closes[-50:] if len(closes)>=50 else closes,50)
        m,mh = macd(closes)
        vw   = vwap(candles[-50:] if len(candles)>=50 else candles)
        at   = atr(candles)
        vol_avg = sum(vols)/len(vols)
        vol_ratio = vols[-1]/vol_avg if vol_avg>0 else 1
        price_change = (closes[-1]-closes[-5])/closes[-5] if len(closes)>=5 else 0
        high_low_ratio = (highs[-1]-lows[-1])/ltp if ltp>0 else 0
        return [
            r/100,
            (e9-e21)/e21 if e21>0 else 0,
            (e9-e50)/e50 if e50>0 else 0,
            mh/ltp if ltp>0 else 0,
            (ltp-vw)/vw if vw>0 else 0,
            at/ltp if ltp>0 else 0,
            min(vol_ratio,5)/5,
            price_change,
            high_low_ratio,
            1 if e9>e21 else 0,
            1 if ltp>vw else 0,
            1 if mh>0 else 0,
        ]
    except Exception as e:
        logger.debug("build_features: %s", e)
        return None

def get_model():
    global _model, _trained
    if _model is None:
        try:
            from xgboost import XGBClassifier
            _model = XGBClassifier(
                n_estimators=100, max_depth=4,
                learning_rate=0.1, random_state=42,
                eval_metric="logloss", verbosity=0
            )
            _trained = False
        except Exception as e:
            logger.error("XGBoost init: %s", e)
    return _model

MODEL_PATH = "data/ml_model.pkl"

def save_model():
    try:
        import pickle, os
        os.makedirs("data", exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(_model, f)
    except Exception as e:
        logger.error("save_model: %s", e)

def load_model():
    global _model, _trained
    try:
        import pickle, os
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                _model = pickle.load(f)
            _trained = True
            logger.info("ML model loaded from disk ✅")
            return True
    except Exception as e:
        logger.error("load_model: %s", e)
    return False

# Auto-load on import
load_model()

def train_model(broker, symbols=None):
    global _trained
    try:
        if symbols is None:
            symbols = [
                ("CRUDEOIL","488290","MCX"),
                ("NATURALGAS","488505","MCX"),
                ("NIFTY","99926000","NSE"),
                ("RELIANCE","2885","NSE"),
                ("TCS","11536","NSE"),
            ]
        X, y = [], []
        for sym,token,exch in symbols:
            try:
                candles = broker.get_candles(token, exch, "FIVE_MINUTE", days=5)
                if not candles or len(candles)<50: continue
                for i in range(30, len(candles)-5):
                    chunk = candles[max(0,i-50):i]
                    feats = build_features(chunk)
                    if not feats: continue
                    future_close = float(candles[i+5][4])
                    current_close = float(candles[i][4])
                    label = 1 if future_close > current_close*1.002 else 0
                    X.append(feats); y.append(label)
            except Exception as e:
                logger.debug("train %s: %s", sym, e)
        if len(X) < 50:
            logger.warning("Not enough training data: %d samples", len(X))
            return False
        model = get_model()
        model.fit(np.array(X), np.array(y))
        _trained = True
        logger.info("XGBoost trained: %d samples", len(X))
        save_model()
        return True
    except Exception as e:
        logger.error("train_model: %s", e)
        return False

def predict_confidence(candles):
    global _trained
    try:
        if not _trained: return 0.5
        feats = build_features(candles)
        if not feats: return 0.5
        model = get_model()
        prob = model.predict_proba(np.array([feats]))[0][1]
        return round(float(prob), 3)
    except Exception as e:
        logger.debug("predict: %s", e)
        return 0.5

def get_status():
    return {"trained": _trained, "model": "XGBoost 3.2.0"}
