import json
import sqlite3
import datetime
from pathlib import Path

DB_PATH = "data/chanakya_v5.db"

STATE_FILE = "data/organism_state.json"

DEFAULT_STATE = {
    "last_restart": None,
    "recoveries": 0,
    "last_recovery": None,
    "stale_detected": 0
}

def _load_state():

    p = Path(STATE_FILE)

    if not p.exists():

        p.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        p.write_text(
            json.dumps(DEFAULT_STATE, indent=2)
        )

    try:
        return json.loads(
            p.read_text()
        )

    except:
        return DEFAULT_STATE.copy()

def _save_state(data):

    Path(STATE_FILE).write_text(
        json.dumps(data, indent=2)
    )

def recover_open_trades():

    state = _load_state()

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT *
        FROM trades
        WHERE status='OPEN'
        """
    ).fetchall()

    recovered = []

    now = datetime.datetime.now()

    for r in rows:

        trade = dict(r)

        recovered.append({
            "id": trade.get("id"),
            "symbol": trade.get("symbol"),
            "direction": trade.get("direction"),
            "entry": trade.get("entry_price")
        })

    state["recoveries"] += len(recovered)

    state["last_restart"] = str(now)

    state["last_recovery"] = str(now)

    _save_state(state)

    conn.close()

    return {
        "recovered": recovered,
        "count": len(recovered)
    }

def detect_stale_trades(max_minutes=180):

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT *
        FROM trades
        WHERE status='OPEN'
        """
    ).fetchall()

    stale = []

    now = datetime.datetime.now()

    for r in rows:

        t = dict(r)

        created = t.get("created_at")

        try:

            dt = datetime.datetime.strptime(
                created,
                "%Y-%m-%d %H:%M:%S"
            )

            age = (
                now - dt
            ).total_seconds() / 60

            if age > max_minutes:

                stale.append({
                    "id": t.get("id"),
                    "symbol": t.get("symbol"),
                    "age_min": round(age, 1)
                })

        except:
            pass

    conn.close()

    state = _load_state()

    state["stale_detected"] = len(stale)

    _save_state(state)

    return stale

def recovery_stats():

    return _load_state()
