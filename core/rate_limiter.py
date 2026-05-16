import time

LAST_CALL = {}

def allow(key, cooldown=10):
    now = time.time()

    last = LAST_CALL.get(key, 0)

    if now - last < cooldown:
        return False

    LAST_CALL[key] = now
    return True
