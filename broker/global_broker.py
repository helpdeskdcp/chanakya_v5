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

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# SmartApi import – direct import from the smartapi library.
# --------------------------------------------------------------------------- #
from smartapi import SmartApi  # type: ignore
import pyotp  # type: ignore

# --------------------------------------------------------------------------- #
# Read Angel One credentials from environment variables
# --------------------------------------------------------------------------- #
ANGEL_API_KEY = os.environ.get("ANGEL_API_KEY")
ANGEL_CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID")
ANGEL_PASSWORD = os.environ.get("ANGEL_PASSWORD")
ANGEL_TOTP_KEY = os.environ.get("ANGEL_TOTP_KEY")

# --------------------------------------------------------------------------- #
# AngelOneBroker singleton implementation
# --------------------------------------------------------------------------- #
class AngelOneBroker:
    """
    Singleton class that manages the SmartAPI connection and subscription tiers.

    The first call to ``AngelOneBroker()`` creates the instance; subsequent calls
    return the same object.  The class lazily loads subscription data from
    ``config.subscriptions`` and provides a small API for the rest of the
    application.
    """

    _instance: Optional["AngelOneBroker"] = None
    _initialized: bool = False

    def __new__(cls) -> "AngelOneBroker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init(self) -> None:
        if self.__class__._initialized:
            return  # Avoid re-initialisation on subsequent calls
        self.__class__._initialized = True

        # --------------------------------------------------------------- #
        # Assign credentials from the module-level environment variables
        # --------------------------------------------------------------- #
        self._api_key: Optional[str] = ANGEL_API_KEY
        self._client_id: Optional[str] = ANGEL_CLIENT_ID
        self._password: Optional[str] = ANGEL_PASSWORD
        self._totp_key: Optional[str] = ANGEL_TOTP_KEY

    def get_tier_data(self, tier_name: str) -> Optional[Dict[str, Any]]:
        try:
            return config.subscriptions[tier_name]
        except KeyError:
            return None

    def has_feature(self, tier_name: str, feature_name: str) -> bool:
        try:
            tier_data = self.get_tier_data(tier_name)
            if tier_data is None:
                return False
            return feature_name in tier_data.get("features", [])
        except Exception as e:
            print(f"Error checking feature access: {e}")
            return False

    def days_remaining(self, created_at: datetime.datetime, role: str) -> int | None:
        try:
            tier_data = self.get_tier_data(role)
            if tier_data is None:
                return None  # Tier not found

            expiry_days = tier_data.get("expiry_days")
            if expiry_days is None:
                return None  # Tier does not expire

            # Calculate the expiry date
            expiry_date = created_at + datetime.timedelta(days=expiry_days)

            # Calculate the difference in days
            days_left = (expiry_date - datetime.datetime.now()).days

            # Ensure we don't return a negative number of days if already expired
            return max(0, days_left)
        except Exception as e:
            print(f"Error calculating days remaining: {e}")
            return None

    # --- Optional: Functions to manage tiers dynamically ---
    # If you need to add or modify tiers after initialization, you would add functions like these:

    def add_or_update_tier(self, tier_name: str, expiry_days: int | None, features: list[str]):
        try:
            if tier_name in config.subscriptions:
                print(f"Info: Tier '{tier_name}' already exists. Updating.")
            config.subscriptions[tier_name] = {"expiry_days": expiry_days, "features": features}
        except Exception as e:
            print(f"Error updating tier: {e}")

    def remove_tier(self, tier_name: str):
        try:
            if tier_name in config.subscriptions:
                del config.subscriptions[tier_name]
                print(f"Info: Tier '{tier_name}' removed.")
            else:
                print(f"Warning: Tier '{tier_name}' not found for removal.")
        except Exception as e:
            print(f"Error removing tier: {e}")
