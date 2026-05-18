import json
from pathlib import Path

FILE = "data/evolution_state.json"

DEFAULT = {
    "min_score": 65,
    "sl_mult": 1.5,
    "target_mult": 3.0,
    "cooldown": 60,
    "risk_mult": 1.0,

    "stats": {
        "wins": 0,
        "losses": 0,
        "total_pnl": 0
    }
}

def _load():

    p = Path(FILE)

    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT, indent=2))

    try:
        return json.loads(p.read_text())
    except:
        return DEFAULT.copy()

def _save(data):

    Path(FILE).write_text(
        json.dumps(data, indent=2)
    )

def remember_trade(pnl):

    data = _load()

    stats = data["stats"]

    stats["total_pnl"] += pnl

    if pnl > 0:
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    wins   = stats["wins"]
    losses = stats["losses"]

    total = wins + losses

    if total < 10:
        _save(data)
        return

    winrate = wins / total

    # ── Evolution Logic ──

    if winrate < 0.40:

        data["min_score"] += 2
        data["cooldown"] += 15

        data["risk_mult"] *= 0.90

        data["sl_mult"] += 0.1

    elif winrate > 0.65:

        data["target_mult"] += 0.2

        data["risk_mult"] *= 1.05

        if data["min_score"] > 55:
            data["min_score"] -= 1

    # ── Safety bounds ──

    data["min_score"] = min(
        max(data["min_score"], 55),
        95
    )

    data["risk_mult"] = min(
        max(data["risk_mult"], 0.2),
        2.0
    )

    data["sl_mult"] = min(
        max(data["sl_mult"], 1.0),
        5.0
    )

    data["target_mult"] = min(
        max(data["target_mult"], 1.5),
        10.0
    )

    _save(data)

def evolve():

    return _load()
