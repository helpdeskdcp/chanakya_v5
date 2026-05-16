import time

LAST_REFRESH = 0

FAIL_COUNT = 0

BASE_COOLDOWN = 30

MAX_COOLDOWN = 300

def can_refresh():

    global LAST_REFRESH
    global FAIL_COUNT

    now = time.time()

    cooldown = min(
        BASE_COOLDOWN * (2 ** FAIL_COUNT),
        MAX_COOLDOWN
    )

    wait_left = cooldown - (now - LAST_REFRESH)

    if wait_left > 0:

        return {
            "allowed": False,
            "wait": round(wait_left, 1),
            "cooldown": cooldown,
            "fails": FAIL_COUNT
        }

    return {
        "allowed": True,
        "wait": 0,
        "cooldown": cooldown,
        "fails": FAIL_COUNT
    }

def mark_attempt():

    global LAST_REFRESH

    LAST_REFRESH = time.time()

def mark_success():

    global FAIL_COUNT

    FAIL_COUNT = 0

def mark_failure():

    global FAIL_COUNT

    FAIL_COUNT += 1

def stats():

    return {
        "last_refresh": LAST_REFRESH,
        "fail_count": FAIL_COUNT
    }
