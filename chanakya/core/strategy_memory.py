import json
from pathlib import Path

MEMORY_FILE = "data/strategy_memory.json"

DEFAULT = {
    "regime_stats": {},
    "symbol_stats": {},
    "strategy_stats": {}
}

def _load():
    p = Path(MEMORY_FILE)

    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT, indent=2))

    try:
        return json.loads(p.read_text())
    except:
        return DEFAULT.copy()

def _save(data):
    Path(MEMORY_FILE).write_text(
        json.dumps(data, indent=2)
    )

def remember_trade(symbol, regime, strategy, pnl):
    data = _load()

    for section, key in [
        ("symbol_stats", symbol),
        ("regime_stats", regime),
        ("strategy_stats", strategy)
    ]:

        if key not in data[section]:
            data[section][key] = {
                "wins": 0,
                "losses": 0,
                "pnl": 0
            }

        row = data[section][key]

        if pnl > 0:
            row["wins"] += 1
        else:
            row["losses"] += 1

        row["pnl"] += pnl

    _save(data)

def score(symbol=None, regime=None, strategy=None):
    data = _load()

    total = 0

    for section, key in [
        ("symbol_stats", symbol),
        ("regime_stats", regime),
        ("strategy_stats", strategy)
    ]:

        if not key:
            continue

        row = data.get(section, {}).get(key)

        if not row:
            continue

        total += row.get("pnl", 0)

    return total

def stats():
    return _load()
