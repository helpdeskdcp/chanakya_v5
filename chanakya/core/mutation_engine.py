from core.system_state import get_state

BASE = {
    "min_score": 65,
    "risk_mult": 1.0,
    "cooldown": 60,
    "sl_mult": 1.5,
    "target_mult": 3.0
}

def mutate():
    st = get_state()

    cfg = BASE.copy()

    loss = st.get("consecutive_loss", 0)
    win  = st.get("consecutive_win", 0)
    regime = st.get("market_mode", "NORMAL")

    # ── Survival mutations ──

    if loss >= 2:
        cfg["min_score"] += 5
        cfg["risk_mult"] *= 0.7
        cfg["cooldown"] += 30

    if loss >= 4:
        cfg["min_score"] += 10
        cfg["risk_mult"] *= 0.5
        cfg["cooldown"] += 60

    # ── Confidence expansion ──

    if win >= 3:
        cfg["risk_mult"] *= 1.2

    if win >= 5:
        cfg["risk_mult"] *= 1.5

    # ── Regime adaptation ──

    if regime == "VOLATILE":
        cfg["sl_mult"] = 2.5
        cfg["target_mult"] = 4.0
        cfg["risk_mult"] *= 0.6

    elif regime == "CHOPPY":
        cfg["min_score"] += 10
        cfg["cooldown"] += 20

    elif regime == "DEAD":
        cfg["risk_mult"] = 0

    elif regime == "TRENDING":
        cfg["risk_mult"] *= 1.3
        cfg["target_mult"] = 5.0

    return cfg
