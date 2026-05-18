import time
import threading

_LOCK = threading.Lock()

LAST_TRADE = {}

def can_trade(symbol, side, cooldown=60):
    key = f"{symbol}:{side}"

    with _LOCK:
        now = time.time()

        last = LAST_TRADE.get(key, 0)

        if now - last < cooldown:
            return False

        LAST_TRADE[key] = now
        return True
