STATE = {
    "market_mode": "NORMAL",
    "ws_health": "GOOD",
    "risk_mode": "NORMAL",
    "daily_pnl": 0,
    "consecutive_loss": 0,
    "consecutive_win": 0,
    "last_trade_time": 0,
}

def get_state():
    return dict(STATE)

def set_state(key, value):
    STATE[key] = value

def inc(key, step=1):
    STATE[key] = STATE.get(key, 0) + step

def reset(key):
    STATE[key] = 0
