"""
Chanakya Scalping Engine — Backtesting Engine
"""
from scalping_engine.strategy import generate_signal
from scalping_engine.risk_manager import RiskManager
from scalping_engine.indicators import expectancy

def run_backtest(candles_by_symbol, capital=100000):
    """
    candles_by_symbol: dict of {symbol: [candle_list]}
    Returns: backtest report
    """
    results = {}
    for symbol, candles in candles_by_symbol.items():
        rm = RiskManager()
        trades = []
        equity = [capital]
        current_capital = capital

        for i in range(21, len(candles)):
            window = candles[:i+1]
            sig = generate_signal(window)
            if sig["signal"] == "NO_TRADE" or sig["score"] < 65:
                continue

            entry = candles[i]["c"]
            atr_val = sig["atr"] or entry * 0.01
            tp = rm.calculate_trade(sig["signal"], entry, atr_val)

            # Simulate next N candles
            result = "TIMEOUT"
            exit_price = entry
            for j in range(i+1, min(i+20, len(candles))):
                c = candles[j]
                if sig["signal"] == "BUY_CE":
                    if c["l"] <= tp["sl"]:   result="LOSS"; exit_price=tp["sl"]; break
                    if c["h"] >= tp["target"]: result="WIN"; exit_price=tp["target"]; break
                else:
                    if c["h"] >= tp["sl"]:   result="LOSS"; exit_price=tp["sl"]; break
                    if c["l"] <= tp["target"]: result="WIN"; exit_price=tp["target"]; break

            pnl = (exit_price-entry)*tp["qty"] if sig["signal"]=="BUY_CE" else (entry-exit_price)*tp["qty"]
            current_capital += pnl
            equity.append(current_capital)
            trades.append({"result":result,"pnl":round(pnl,2),"strategy":sig["active_strategy"],"score":sig["score"]})

        wins   = sum(1 for t in trades if t["result"]=="WIN")
        losses = sum(1 for t in trades if t["result"]=="LOSS")
        total  = len(trades)
        total_pnl = sum(t["pnl"] for t in trades)
        wr = wins/total if total > 0 else 0
        avg_win  = sum(t["pnl"] for t in trades if t["pnl"]>0)/(wins or 1)
        avg_loss = abs(sum(t["pnl"] for t in trades if t["pnl"]<0))/(losses or 1)

        # Max drawdown
        peak = capital; max_dd = 0
        for e in equity:
            if e > peak: peak = e
            dd = (peak - e) / peak * 100
            if dd > max_dd: max_dd = dd

        results[symbol] = {
            "total_trades": total,
            "wins": wins, "losses": losses,
            "win_rate": round(wr*100,1),
            "total_pnl": round(total_pnl,2),
            "max_drawdown_pct": round(max_dd,2),
            "expectancy": expectancy(wr, avg_win, avg_loss),
            "final_capital": round(current_capital,2),
            "return_pct": round((current_capital-capital)/capital*100,2),
        }
    return results
