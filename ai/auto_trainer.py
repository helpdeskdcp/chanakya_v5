"""
Chanakya Auto-Trainer™
XGBoost periodic retrain from trade history
"""
import sqlite3, pickle, logging
import numpy as np
logger = logging.getLogger(__name__)

def retrain_from_trades(db_path="data/chanakya_v5.db", model_path="data/ml_model.pkl"):
    """Retrain XGBoost from closed trade history"""
    try:
        conn = sqlite3.connect(db_path)
        # Get closed trades with features
        trades = conn.execute("""
            SELECT pnl, strategy, entry_price, sl_price, target_price, quantity
            FROM trades WHERE status='CLOSED' AND pnl IS NOT NULL
            ORDER BY id DESC LIMIT 500
        """).fetchall()
        conn.close()

        if len(trades) < 20:
            return {"success":False,"reason":f"Need 20+ trades, have {len(trades)}"}

        # Synthetic features from trade data
        X = []
        y = []
        for t in trades:
            pnl, strat, entry, sl, target, qty = t
            if not all([entry, sl, target]): continue
            sl_pct = abs(entry-sl)/entry*100 if entry else 1
            tgt_pct = abs(target-entry)/entry*100 if entry else 2
            rr = tgt_pct/sl_pct if sl_pct>0 else 2
            label = 1 if pnl and pnl>0 else 0  # 1=WIN, 0=LOSS
            X.append([sl_pct, tgt_pct, rr, 1 if strat=="BREAKOUT" else 0,
                      1 if strat=="REVERSAL" else 0, 1 if strat=="RANGE_BOUND" else 0])
            y.append(label)

        if len(X) < 10:
            return {"success":False,"reason":"Insufficient valid data"}

        from xgboost import XGBClassifier
        model = XGBClassifier(n_estimators=100, max_depth=4,
                              learning_rate=0.1, use_label_encoder=False,
                              eval_metric='logloss')
        model.fit(np.array(X), np.array(y))

        with open(model_path,'wb') as f: pickle.dump(model,f)
        wins = sum(y); total = len(y)
        return {"success":True,"trades":total,"win_rate":round(wins/total*100,1),
                "message":f"Retrained on {total} trades, WR={wins/total*100:.1f}%"}
    except Exception as e:
        logger.error("retrain: %s", e)
        return {"success":False,"error":str(e)}
