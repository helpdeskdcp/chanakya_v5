import json
import datetime
from pathlib import Path

FILE = "data/meta_brain.json"

DEFAULT = {
    "hours": {},
    "weekdays": {},
    "symbols": {},
    "regimes": {},
    "infra": {
        "ws_disconnects": 0,
        "jwt_failures": 0
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

def _update_bucket(section, key, pnl):
    if key not in section:
        section[key] = {
            "wins": 0,
            "losses": 0,
            "pnl": 0,
            "trades": 0
        }

    row = section[key]

    row["trades"] += 1
    row["pnl"] += pnl

    if pnl > 0:
        row["wins"] += 1
    else:
        row["losses"] += 1

def remember(symbol, regime, pnl):
    data = _load()

    now = datetime.datetime.now()

    hour = str(now.hour)
    weekday = now.strftime("%A")

    _update_bucket(data["hours"], hour, pnl)
    _update_bucket(data["weekdays"], weekday, pnl)
    _update_bucket(data["symbols"], symbol, pnl)
    _update_bucket(data["regimes"], regime, pnl)

    _save(data)

def score_hour():
    data = _load()

    hour = str(datetime.datetime.now().hour)

    row = data["hours"].get(hour)

    if not row:
        return 0

    return row.get("pnl", 0)

def score_symbol(symbol):
    data = _load()

    row = data["symbols"].get(symbol)

    if not row:
        return 0

    return row.get("pnl", 0)

def infra_event(name):
    data = _load()

    infra = data.get("infra", {})

    infra[name] = infra.get(name, 0) + 1

    data["infra"] = infra

    _save(data)

def stats():
    return _load()
