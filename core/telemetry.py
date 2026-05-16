import time

STATE = {
    "started_at": time.time(),

    "heartbeat": time.time(),

    "ws_health": "UNKNOWN",

    "organism_mode": "NORMAL",

    "execution_mode": "NORMAL",

    "threat": 0,

    "confidence": 0,

    "anomaly": "NONE",

    "adaptive_risk": 1.0,

    "adaptive_score": 65,

    "open_trades": 0,

    "daily_pnl": 0,

    "wins": 0,

    "losses": 0,

    "last_symbol": None,

    "shadow_expectancy": 0
}

def set_metric(key, value):

    STATE[key] = value

def get_metric(key, default=None):

    return STATE.get(key, default)

def update(data):

    if not isinstance(data, dict):
        return

    STATE.update(data)

def snapshot():

    uptime = int(
        time.time() - STATE["started_at"]
    )

    return {
        **STATE,
        "uptime_sec": uptime
    }

def heartbeat():

    STATE["heartbeat"] = time.time()
