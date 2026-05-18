"""
Chanakya Scalping Engine — Main Runner
CLI Dashboard + Live Scanner
"""
import sys, time, os
sys.path.insert(0, '/app/chanakya')

from scalping_engine.strategy import generate_signal
from scalping_engine.risk_manager import RiskManager
from scalping_engine.ai_engine import (adaptive_confidence, get_performance_stats,
                                        get_strategy_weights)
from scalping_engine.execution import ExecutionEngine
from broker.global_broker import get_broker

SYMBOLS = [
    {"name":"NIFTY",    "token":"99926000","exchange":"NSE","lot":65,  "interval":50},
    {"name":"BANKNIFTY","token":"99926009","exchange":"NSE","lot":30,  "interval":100},
    {"name":"CRUDEOIL", "token":"488290",  "exchange":"MCX","lot":100, "interval":50},
    {"name":"NATURALGAS","token":"488505", "exchange":"MCX","lot":1250,"interval":10},
]

def fetch_candles(broker, sym, timeframe="FIVE_MINUTE", days=2):
    try:
        raw = broker.get_candles(sym["token"], sym["exchange"], timeframe, days)
        if not raw: return []
        return [{"o":float(c[1]),"h":float(c[2]),"l":float(c[3]),
                 "c":float(c[4]),"v":float(c[5]) if len(c)>5 else 0} for c in raw]
    except: return []

def scan_once(broker, rm, exe, paper=True):
    results = []
    for sym in SYMBOLS:
        try:
            candles = fetch_candles(broker, sym)
            if len(candles) < 22: continue
            sig = generate_signal(candles)
            if sig["signal"] == "NO_TRADE": continue
            conf = adaptive_confidence(sig["score"], sig["active_strategy"], sym["name"])
            sig["confidence"] = conf
            if conf < 65: continue
            can, reason = rm.can_trade()
            if not can:
                print(f"[SKIP] {reason}")
                continue
            tp = rm.calculate_trade(sig["signal"], sig["price"], sig["atr"], sym["lot"])
            results.append({
                "symbol": sym["name"],
                "signal": sig["signal"],
                "price":  sig["price"],
                "score":  conf,
                "strategy": sig["active_strategy"],
                "sl":    tp["sl"],
                "target":tp["target"],
                "qty":   tp["qty"],
                "rsi":   sig["rsi"],
                "trend": sig["trend"],
                "reasons": sig["reasons"],
                "trade_params": tp,
                "signal_data": sig,
            })
        except Exception as e:
            print(f"[ERROR] {sym['name']}: {e}")
    return results

def print_dashboard(results, stats, weights):
    os.system('clear')
    print("="*60)
    print("🔱 CHANAKYA SCALPING ENGINE™ — LIVE DASHBOARD")
    print("="*60)
    print(f"Total Trades: {stats['total_trades']} | "
          f"Win Rate: {stats['win_rate']}% | "
          f"Total PnL: ₹{stats['total_pnl']}")
    print()
    print("📊 STRATEGY WEIGHTS (Self-Learning):")
    for strat, w in weights.items():
        print(f"  {strat:15} Weight:{w['weight']:.2f} "
              f"WR:{w['win_rate']*100:.1f}% "
              f"PnL:₹{w['total_pnl']:.0f}")
    print()
    if results:
        print("⚡ LIVE SIGNALS:")
        for r in results:
            print(f"  {r['signal']:8} {r['symbol']:12} "
                  f"₹{r['price']} Score:{r['score']}% "
                  f"SL:₹{r['sl']} TGT:₹{r['target']}")
            print(f"    Strategy:{r['strategy']} Trend:{r['trend']} "
                  f"RSI:{r['rsi']}")
    else:
        print("⏳ No signals — Scanning...")
    print("="*60)

if __name__ == "__main__":
    print("🚀 Chanakya Scalping Engine starting...")
    broker = get_broker()
    if not broker.connected:
        print("Connecting broker...")
        broker.connect()
    rm  = RiskManager()
    exe = ExecutionEngine(paper_mode=True, broker=broker)
    print("✅ Ready! Scanning every 5 minutes...")
    while True:
        try:
            results = scan_once(broker, rm, exe)
            stats   = get_performance_stats()
            weights = get_strategy_weights()
            print_dashboard(results, stats, weights)
            time.sleep(300)  # 5 min
        except KeyboardInterrupt:
            print("\n🛑 Stopped")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(60)
