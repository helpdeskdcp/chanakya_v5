from core.system_state import get_state

def fuse(
    regime="UNKNOWN",
    volatility=0,
    trend_strength=0,
    ws_health="GOOD",
    tick_age=0,
    hour_score=0,
    symbol_score=0
):

    threat = 0
    confidence = 50

    # ── Websocket / infra health ──
    if ws_health != "GOOD":
        threat += 40
        confidence -= 25

    # ── Tick starvation ──
    if tick_age > 15:
        threat += 30
        confidence -= 20

    # ── Regime analysis ──
    if regime == "TRENDING":
        confidence += 20

    elif regime == "VOLATILE":
        threat += 15
        confidence -= 5

    elif regime == "CHOPPY":
        threat += 20
        confidence -= 15

    elif regime == "DEAD":
        threat += 35
        confidence -= 30

    # ── Trend quality ──
    if trend_strength > 100:
        confidence += 10

    # ── Statistical memory ──
    if hour_score < 0:
        threat += 10

    if symbol_score < 0:
        threat += 15

    # ── State awareness ──
    s = get_state()

    losses = s.get("consecutive_loss", 0)

    if losses >= 3:
        threat += 20
        confidence -= 10

    # ── Clamp ──
    threat = max(0, min(100, threat))
    confidence = max(0, min(100, confidence))

    # ── Execution mode ──
    if threat >= 80:
        mode = "HIBERNATE"

    elif threat >= 60:
        mode = "SURVIVAL"

    elif confidence >= 75:
        mode = "ATTACK"

    else:
        mode = "NORMAL"

    return {
        "confidence": confidence,
        "threat": threat,
        "execution_mode": mode
    }
