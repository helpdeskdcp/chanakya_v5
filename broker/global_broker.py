"""
Angel One SmartAPI Broker Connection.

This module provides a singleton ``AngelOneBroker`` class that encapsulates:
* Connection handling to the Angel One SmartAPI (login via TOTP).
* Helper methods to fetch LTP and historical candle data.
* Subscription tier management using the data defined in ``config.subscriptions``.
* Convenience global accessor functions for easy use throughout the codebase.

All potentially error-prone operations are wrapped in ``try/except`` blocks to
ensure the broker never raises unexpected exceptions during normal operation.
"""

from __future...