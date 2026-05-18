from core.system_state import get_state

def current_mode():

    s = get_state()

    pnl    = s.get("daily_pnl", 0)
    losses = s.get("consecutive_loss", 0)
    wins   = s.get("consecutive_win", 0)
    ws     = s.get("ws_health", "GOOD")
    risk   = s.get("risk_mode", "NORMAL")

    # ── Infrastructure survival first ──
    if ws != "GOOD":
        return "SURVIVAL"

    # ── Hard drawdown protection ──
    if pnl <= -5000:
        return "DORMANT"

    # ── Recovery mode ──
    if losses >= 3:
        return "RECOVERY"

    # ── Aggressive expansion ──
    if wins >= 4 and pnl > 3000:
        return "AGGRESSIVE"

    # ── Defensive posture ──
    if risk == "HIGH":
        return "DEFENSIVE"

    return "HUNTING"


def config(mode):

    cfg = {
        "min_score": 65,
        "risk_mult": 1.0,
        "trade_cooldown": 60,
        "max_trades": 3
    }

    if mode == "DEFENSIVE":
        cfg["min_score"] = 75
        cfg["risk_mult"] = 0.7

    elif mode == "RECOVERY":
        cfg["min_score"] = 80
        cfg["risk_mult"] = 0.5
        cfg["trade_cooldown"] = 180

    elif mode == "AGGRESSIVE":
        cfg["risk_mult"] = 1.5
        cfg["max_trades"] = 5

    elif mode == "SURVIVAL":
        cfg["min_score"] = 85
        cfg["risk_mult"] = 0.3
        cfg["trade_cooldown"] = 300
        cfg["max_trades"] = 1

    elif mode == "DORMANT":
        cfg["min_score"] = 999

    return cfg
