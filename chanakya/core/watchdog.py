import time
import logging

from core.heartbeat import age
from broker.websocket_mgr import (
    is_connected,
    start as ws_start
)

from core.thread_registry import start_singleton

logger = logging.getLogger("watchdog")

_last_restart = 0


def safe_restart_ws():
    global _last_restart

    now = time.time()

    # cooldown protection
    if now - _last_restart < 30:
        return

    _last_restart = now

    logger.warning("♻ Restarting WebSocket Manager")

    try:
        start_singleton("WSManager", ws_start)
    except Exception as e:
        logger.error(f"WS restart failed: {e}")


def run_watchdog():


    while True:

        try:
            tick_age = age()

            from datetime import datetime
            now = datetime.now()

            market_open = (
                now.weekday() < 5 and
                (
                    (now.hour > 9 or (now.hour == 9 and now.minute >= 15))
                    and
                    (now.hour < 15 or (now.hour == 15 and now.minute <= 30))
                )
            )

            if not market_open:
                time.sleep(5)
                continue

            if is_connected() and tick_age > 10:

                logger.warning(
                    f"⚠ STALE DATA DETECTED | age={tick_age:.1f}s"
                )

                safe_restart_ws()

            elif not is_connected():

                logger.warning(
                    "⚠ WEBSOCKET DISCONNECTED"
                )

                safe_restart_ws()

        except Exception as e:

            logger.error(
                f"Watchdog error: {e}"
            )

        time.sleep(5)
