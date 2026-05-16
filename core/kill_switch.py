import time
import threading
import logging

logger = logging.getLogger("kill_switch")

_LOCK = threading.Lock()

STATE = {
    "enabled": False,
    "reason": "",
    "time": 0,
}

def activate(reason):
    with _LOCK:
        STATE["enabled"] = True
        STATE["reason"] = reason
        STATE["time"] = time.time()

    logger.critical(f"🛑 KILL SWITCH ACTIVATED: {reason}")

def deactivate():
    with _LOCK:
        STATE["enabled"] = False
        STATE["reason"] = ""
        STATE["time"] = 0

    logger.warning("✅ Kill switch reset")

def active():
    return STATE["enabled"]

def status():
    return dict(STATE)
