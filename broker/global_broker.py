"""
Angel One SmartAPI Broker Connection.

This module provides a singleton ``AngelOneBroker`` class that encapsulates:
* Connection handling to the Angel One SmartAPI (login via TOTP).
* Helper methods to fetch LTP and historical candle data.
* Subscription tier management using the data defined in ``config.subscriptions``.
* Convenience global accessor functions for easy use throughout the codebase.

All potentially error‑prone operations are wrapped in ``try/except`` blocks to
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

    def __init__(self) -> None:
        if self.__class__._initialized:
            return  # Avoid re‑initialisation on subsequent calls
        self.__class__._initialized = True

        # --------------------------------------------------------------- #
        # Assign credentials from the module‑level environment variables
        # --------------------------------------------------------------- #
        self._api_key: Optional[str] = ANGEL_API_KEY
        self._client_id: Optional[str] = ANGEL_CLIENT_ID
        self._password: Optional[str] = ANGEL_PASSWORD
        self._totp_key: Optional[str] = ANGEL_TOTP_KEY

        # --------------------------------------------------------------- #
        # Initialise the SmartApi client
        # --------------------------------------------------------------- #
        try:
            if all([self._api_key, self._client_id, self._password, self._totp_key]):
                self._api = SmartApi(
                    self._api_key,
                    self._client_id,
                    self._password,
                    self._totp_key,
                )
                print("SmartApi instance created.")
            else:
                print(
                    "Warning: Incomplete Angel One credentials – SmartApi instance not fully configured."
                )
                self._api = SmartApi()
        except Exception as exc:  # pragma: no cover
            print(f"Error creating SmartApi instance: {exc}")
            self._api = SmartApi()

        self._connected: bool = False

        # --------------------------------------------------------------- #
        # Load subscription tier definitions
        # --------------------------------------------------------------- #
        try:
            from config.subscriptions import PREDEFINED_TIERS

            self._tiers: Dict[str, Dict[str, Any]] = PREDEFINED_TIERS.copy()
        except Exception as exc:  # pragma: no cover
            print(f"Error loading subscription tiers: {exc}")
            self._tiers = {}

    # ------------------------------------------------------------------- #
    # Connection handling
    # ------------------------------------------------------------------- #
    def connect(self) -> bool:
        """
        Perform a TOTP‑based login to Angel One.

        Returns ``True`` on successful login, ``False`` otherwise.
        """
        if not all(
            [
                self._api_key,
                self._client_id,
                self._password,
                self._totp_key,
                isinstance(self._api, SmartApi),
            ]
        ):
            print("Error: Missing credentials or invalid SmartApi instance.")
            self._connected = False
            return False

        try:
            totp = pyotp.TOTP(self._totp_key)  # type: ignore
            code = totp.at()
            response = self._api.login(self._client_id, self._password, code)
            if response.get("status") == "success":
                self._connected = True
                print("Successfully connected to Angel One SmartAPI.")
                return True
            print(f"Login failed: {response}")
        except Exception as exc:  # pragma: no cover
            print(f"Exception during SmartApi login: {exc}")

        self._connected = False
        return False

    def is_connected(self) -> bool:
        """Return ``True`` if a successful login has been performed."""
        return self._connected

    # ------------------------------------------------------------------- #
    # Market data helpers
    # ------------------------------------------------------------------- #
    def get_ltp(
        self, exchange: str, symbol: str, token: Optional[str] = None
    ) -> Optional[float]:
        """
        Retrieve the Last Traded Price (LTP) for a symbol.

        Returns ``None`` if the broker is not connected or the request fails.
        """
        if not self.is_connected():
            print("Error: Not connected – cannot fetch LTP.")
            return None

        try:
            instrument: Dict[str, str] = {"exchange": exchange, "symbol": symbol}
            if token:
                instrument["symboltoken"] = token
            else:
                print(
                    f"Warning: No token supplied for {symbol}@{exchange}; result may be unreliable."
                )

            resp = self._api.get_quotes([instrument])
            if resp.get("status") != "success":
                print(f"SmartApi get_quotes error: {resp}")
                return None

            data = resp.get("data", [])
            if not data:
                print(f"No quote data returned for {symbol}@{exchange}.")
                return None

            ltp = data[0].get("ltp")
            return float(ltp) if ltp is not None else None
        except Exception as exc:  # pragma: no cover
            print(f"Exception in get_ltp: {exc}")
            return None

    def get_candles(
        self,
        token: str,
        exchange: str,
        interval: str,
        fromdate: datetime.date,
        todate: datetime.date,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve historical OHLCV candles.

        Returns a list of candle dictionaries or ``None`` on failure.
        """
        if not self.is_connected():
            print("Error: Not connected – cannot fetch candles.")
            return None

        try:
            from_str = fromdate.strftime("%Y-%m-%d")
            to_str = todate.strftime("%Y-%m-%d")
            resp = self._api.get_candles(token, exchange, interval, from_str, to_str)
            if resp.get("status") != "success":
                print(f"SmartApi get_candles error: {resp}")
                return None
            return resp.get("data", [])
        except Exception as exc:  # pragma: no cover
            print(f"Exception in get_candles: {exc}")
            return None

    # ------------------------------------------------------------------- #
    # Subscription tier management
    # ------------------------------------------------------------------- #
    def get_tier_data(self, tier_name: str) -> Optional[Dict[str, Any]]:
        """Return the dictionary describing a tier, or ``None`` if unknown."""
        try:
            return self._tiers.get(tier_name)
        except Exception as exc:  # pragma: no cover
            print(f"Error retrieving tier '{tier_name}': {exc}")
            return None

    def has_feature(self, tier_name: str, feature_name: str) -> bool:
        """Return ``True`` if the tier includes the specified feature."""
        try:
            tier = self.get_tier_data(tier_name)
            if not tier:
                return False
            return feature_name in tier.get("features", [])
        except Exception as exc:  # pragma: no cover
            print(f"Error checking feature '{feature_name}' for tier '{tier_name}': {exc}")
            return False

    def check_feature_access(self, role: str, feature: str) -> bool:
        """Alias for ``has_feature`` – kept for backward compatibility."""
        return self.has_feature(role, feature)

    def days_remaining(
        self, created_at: datetime.datetime, role: str
    ) -> Optional[int]:
        """
        Compute days left before a tier expires.

        Returns ``None`` if the tier does not expire or is unknown.
        """
        try:
            tier = self.get_tier_data(role)
            if not tier:
                return None
            expiry = tier.get("expiry_days")
            if expiry is None:
                return None
            expiry_date = created_at + datetime.timedelta(days=expiry)
            remaining = (expiry_date - datetime.datetime.now()).days
            return max(0, remaining)
        except Exception as exc:  # pragma: no cover
            print(f"Error calculating days remaining for role '{role}': {exc}")
            return None

    def add_or_update_tier(
        self, tier_name: str, expiry_days: Optional[int], features: List[str]
    ) -> None:
        """Insert or replace a tier definition."""
        try:
            if tier_name in self._tiers:
                print(f"Info: Updating existing tier '{tier_name}'.")
            self._tiers[tier_name] = {"expiry_days": expiry_days, "features": features}
        except Exception as exc:  # pragma: no cover
            print(f"Error adding/updating tier '{tier_name}': {exc}")

    def remove_tier(self, tier_name: str) -> None:
        """Delete a tier from the internal dictionary."""
        try:
            if tier_name in self._tiers:
                del self._tiers[tier_name]
                print(f"Info: Tier '{tier_name}' removed.")
            else:
                print(f"Warning: Tier '{tier_name}' not found.")
        except Exception as exc:  # pragma: no cover
            print(f"Error removing tier '{tier_name}': {exc}")


# --------------------------------------------------------------------------- #
# Global accessor helpers – thin wrappers around the singleton instance.
# --------------------------------------------------------------------------- #
def _broker() -> AngelOneBroker:
    """Internal helper to obtain the singleton AngelOneBroker instance."""
    return AngelOneBroker()


def get_smart_api_instance_global() -> Optional[SmartApi]:
    """Return the underlying SmartApi client (may be a placeholder)."""
    try:
        return _broker()._api
    except Exception:  # pragma: no cover
        return None


def connect_global() -> bool:
    """Convenient wrapper to trigger a login."""
    return _broker().connect()


def is_connected_global() -> bool:
    """Return the connection status."""
    return _broker().is_connected()


def get_ltp_global(
    exchange: str, symbol: str, token: Optional[str] = None
) -> Optional[float]:
    """Global shortcut for ``AngelOneBroker.get_ltp``."""
    return _broker().get_ltp(exchange, symbol, token)


def get_candles_global(
    token: str,
    exchange: str,
    interval: str,
    fromdate: datetime.date,
    todate: datetime.date,
) -> Optional[List[Dict[str, Any]]]:
    """Global shortcut for ``AngelOneBroker.get_candles``."""
    return _broker().get_candles(token, exchange, interval, fromdate, todate)


# Subscription‑related global helpers
def get_subscription_tier_data_global(tier_name: str) -> Optional[Dict[str, Any]]:
    """Retrieve tier definition."""
    return _broker().get_tier_data(tier_name)


def does_tier_have_feature_global(tier_name: str, feature_name: str) -> bool:
    """Check if a tier includes a feature."""
    return _broker().has_feature(tier_name, feature_name)


def check_user_feature_access_global(role: str, feature: str) -> bool:
    """Alias for ``does_tier_have_feature_global``."""
    return _broker().check_feature_access(role, feature)


def get_days_remaining_for_tier_global(
    created_at: datetime.datetime, role: str
) -> Optional[int]:
    """Calculate remaining days for a tier."""
    return _broker().days_remaining(created_at, role)


def add_or_update_subscription_tier_global(
    tier_name: str, expiry_days: Optional[int], features: List[str]
) -> None:
    """Add or update a tier definition."""
    _broker().add_or_update_tier(tier_name, expiry_days, features)


def remove_subscription_tier_global(tier_name: str) -> None:
    """Remove a tier definition."""
    _broker().remove_tier(tier_name)


# --------------------------------------------------------------------------- #
# Top‑level convenience functions
# --------------------------------------------------------------------------- #
def connect() -> bool:
    """
    Connect to Angel One SmartAPI using TOTP.

    This is a thin wrapper around the singleton broker's ``connect`` method,
    providing a simple function‑level API.
    """
    return _broker().connect()


def get_ltp(exchange: str, symbol: str, token: Optional[str] = None) -> Optional[float]:
    """
    Top‑level convenience wrapper to fetch the Last Traded Price (LTP).

    Delegates to the singleton broker's ``get_ltp`` method.
    """
    return _broker().get_ltp(exchange, symbol, token)


def get_candles(
    token: str,
    exchange: str,
    interval: str,
    fromdate: datetime.date,
    todate: datetime.date,
) -> Optional[List[Dict[str, Any]]]:
    """
    Top‑level convenience wrapper to fetch historical candle data.

    Delegates to the singleton broker's ``get_candles`` method.
    """
    return _broker().get_candles(token, exchange, interval, fromdate, todate)
