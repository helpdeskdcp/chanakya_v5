"""
Chanakya Scalping Engine — Execution Engine
Paper + Live mode with Angel One integration
"""
import sqlite3, json
from datetime import datetime
from scalping_engine.ai_engine import log_trade

DB_PATH = 'data/scalping_ai.db'

class ExecutionEngine:
    def __init__(self, paper_mode=True, broker=None):
        self.paper_mode = paper_mode
        self.broker = broker
        self.open_trades = []

    def place_order(self, signal_data, trade_params, symbol, option_symbol=None):
        trade = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "symbol": symbol,
            "option": option_symbol,
            "signal": signal_data["signal"],
            "strategy": signal_data["active_strategy"],
            "entry": trade_params["entry"],
            "sl": trade_params["sl"],
            "target": trade_params["target"],
            "qty": trade_params["qty"],
            "rsi": signal_data["rsi"],
            "ema9": signal_data["ema9"],
            "ema21": signal_data["ema21"],
            "vwap": signal_data["vwap"],
            "atr": signal_data["atr"],
            "vol_regime": signal_data["vol_regime"],
            "trend": signal_data["trend"],
            "score": signal_data["score"],
            "paper": self.paper_mode,
            "status": "OPEN",
            "timestamp": datetime.now().isoformat()
        }
        if self.paper_mode:
            self.open_trades.append(trade)
            print(f"[PAPER] {signal_data['signal']} {symbol} @ ₹{trade_params['entry']} "
                  f"SL=₹{trade_params['sl']} TGT=₹{trade_params['target']}")
        else:
            # Live Angel One order
            if self.broker and self.broker.connected:
                try:
                    direction = "BUY"
                    order_id = self.broker.place_order(
                        symbol=option_symbol or symbol,
                        qty=trade_params['qty'],
                        direction=direction,
                        order_type="MARKET"
                    )
                    trade["order_id"] = order_id
                    self.open_trades.append(trade)
                    print(f"[LIVE] Order placed: {order_id}")
                except Exception as e:
                    print(f"[ERROR] Order failed: {e}")
                    return None
        return trade

    def close_trade(self, trade, exit_price, reason):
        trade["exit"] = exit_price
        trade["result"] = "WIN" if (
            (trade["signal"]=="BUY_CE" and exit_price > trade["entry"]) or
            (trade["signal"]=="BUY_PE" and exit_price < trade["entry"])
        ) else "LOSS"
        trade["pnl"] = round(
            (exit_price - trade["entry"]) * trade["qty"] if trade["signal"]=="BUY_CE"
            else (trade["entry"] - exit_price) * trade["qty"], 2)
        trade["exit_reason"] = reason
        trade["status"] = "CLOSED"
        self.open_trades = [t for t in self.open_trades if t["id"] != trade["id"]]
        log_trade(trade)
        print(f"[CLOSE] {reason} {trade['symbol']} PnL=₹{trade['pnl']}")
        return trade
