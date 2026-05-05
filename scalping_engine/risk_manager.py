"""
Chanakya Scalping Engine — Risk Management
SEBI: 2% risk/trade, ATR-based SL, trailing stop
"""
import json, os
from scalping_engine.indicators import position_size, expectancy

def load_config():
    path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(path) as f: return json.load(f)

class RiskManager:
    def __init__(self):
        self.cfg = load_config()
        self.daily_pnl = 0
        self.trades_today = 0
        self.max_loss = self.cfg['capital'] * self.cfg['max_daily_loss_pct'] / 100

    def can_trade(self):
        if self.trades_today >= self.cfg['max_trades_per_day']:
            return False, f"Max trades ({self.cfg['max_trades_per_day']}) reached"
        if self.daily_pnl <= -self.max_loss:
            return False, f"Max daily loss ₹{self.max_loss:.0f} hit"
        return True, "OK"

    def calculate_trade(self, signal, entry_price, atr_val, lot_size=1):
        """Calculate SL, Target, Qty using SEBI math"""
        cfg = self.cfg
        sl_pts  = atr_val * cfg['atr_sl_multiplier']
        tgt_pts = sl_pts  * cfg['rr_target']
        is_buy  = signal == "BUY_CE"

        sl     = entry_price - sl_pts if is_buy else entry_price + sl_pts
        target = entry_price + tgt_pts if is_buy else entry_price - tgt_pts
        qty    = position_size(cfg['capital'], cfg['risk_per_trade_pct'],
                               entry_price, sl, lot_size)
        exp = expectancy(0.60, tgt_pts, sl_pts)  # assuming 60% WR

        return {
            "entry": round(entry_price, 2),
            "sl":    round(sl, 2),
            "target":round(target, 2),
            "qty":   qty,
            "sl_pts":round(sl_pts, 2),
            "tgt_pts":round(tgt_pts, 2),
            "rr":    round(cfg['rr_target'], 2),
            "max_loss_trade": round(sl_pts * qty, 2),
            "max_profit_trade": round(tgt_pts * qty, 2),
            "expectancy_r": round(exp, 4),
        }

    def trail_stop(self, entry, current_price, sl, signal, atr_val):
        """Trailing stop loss logic"""
        is_buy = signal == "BUY_CE"
        profit_pts = (current_price - entry) if is_buy else (entry - current_price)
        if profit_pts >= atr_val:
            new_sl = (current_price - atr_val * 0.5) if is_buy else (current_price + atr_val * 0.5)
            return round(max(new_sl, sl) if is_buy else min(new_sl, sl), 2)
        return sl

    def should_exit(self, trade, current_price, opposite_signal=False):
        """Exit conditions"""
        is_buy = trade['signal'] == "BUY_CE"
        if is_buy:
            if current_price <= trade['sl']:     return True, "SL_HIT"
            if current_price >= trade['target']: return True, "TARGET_HIT"
        else:
            if current_price >= trade['sl']:     return True, "SL_HIT"
            if current_price <= trade['target']: return True, "TARGET_HIT"
        if opposite_signal:                      return True, "OPPOSITE_SIGNAL"
        return False, "HOLD"

    def update_pnl(self, pnl):
        self.daily_pnl += pnl
        self.trades_today += 1
