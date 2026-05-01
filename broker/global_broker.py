"""
Global Broker for Subscription Management and Angel One SmartAPI Connection (Singleton Pattern).

This module acts as a central registry for subscription-related functions,
allowing access to subscription tier data and operations without direct
importing of the configuration module in every part of the application.
It also handles the initialization and access to the Angel One SmartAPI broker connection.
It follows a Singleton pattern for the broker instance.
"""

import datetime
import os
from typing import Dict, List, Optional, Any

# Import SmartApi for potential broker connection functionalities
try:
    from smartapi import SmartApi
    import pyotp # Import pyotp for TOTP handling
except ImportError:
    print("Warning: smartapi library or pyotp not found. SmartApi functionalities will not be available.")
    # Define a placeholder if SmartApi is not found, to avoid NameError
    class SmartApi:
        def __init__(self, *args, **kwargs):
            print("SmartApi placeholder initialized. Actual API connection not available.")
            self._is_connected = False # Placeholder for connection status
            pass
        def login(self, client_id, password, totp):
            print("SmartApi.login placeholder called.")
            self._is_connected = True # Simulate connection
            return {"status": "success"}
        def get_quotes(self, instruments):
            print("SmartApi.get_quotes placeholder called.")
            if not self._is_connected: return {"status": "error", "data": []}
            return {"status": "success", "data": [{"ltp": 100.0}]} # Mock LTP
        def get_candles(self, token, exchange, interval, from_date, to_date):
            print("SmartApi.get_candles placeholder called.")
            if not self._is_connected: return {"status": "error", "data": []}
            return {"status": "success", "data": [{"timestamp": "2023-01-01T09:15:00+05:30", "open": 100, "high": 105, "low": 98, "close": 102, "volume": 1000}]} # Mock candle
    # Define a placeholder for pyotp if not found
    class pyotp:
        class TOTP:
            def __init__(self, key):
                print("pyotp.TOTP placeholder initialized.")
                self.key = key
            def at(self, for_time=None):
                print("pyotp.TOTP.at placeholder called.")
                return "000000" # Default placeholder TOTP

# --- Singleton Instance Management ---
_broker_instance = None
_is_api_connected = False # Global flag to track connection status

class Broker:
    """
    The main Broker class implementing the Singleton pattern.
    Manages Angel One SmartAPI connection and subscription logic.
    """
    def __init__(self):
        """Initializes the Broker instance."""
        global _is_api_connected # Ensure we modify the global flag

        # --- Angel One SmartAPI Credentials ---
        self.ANGEL_API_KEY = os.environ.get("ANGEL_API_KEY")
        self.ANGEL_CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID")
        self.ANGEL_PASSWORD = os.environ.get("ANGEL_PASSWORD")
        self.ANGEL_TOTP_KEY = os.environ.get("ANGEL_TOTP_KEY")

        self.smart_api_instance = None
        self._is_api_connected = False

        if self.ANGEL_API_KEY and self.ANGEL_CLIENT_ID and self.ANGEL_PASSWORD and self.ANGEL_TOTP_KEY:
            try:
                self.smart_api_instance = SmartApi(
                    self.ANGEL_API_KEY,
                    self.ANGEL_CLIENT_ID,
                    self.ANGEL_PASSWORD,
                    self.ANGEL_TOTP_KEY
                )
                print("Angel One SmartAPI instance created.")
            except Exception as e:
                print(f"Error creating SmartApi instance: {e}")
                self.smart_api_instance = SmartApi() # Fallback to placeholder
        else:
            print("Warning: Missing Angel One API credentials in environment variables. SmartApi will use placeholder.")
            self.smart_api_instance = SmartApi()

        # --- Subscription Management Data ---
        self._initialize_subscription_tiers()

    def _initialize_subscription_tiers(self):
        """Sets up the default subscription tiers."""
        try:
            from config.subscriptions import PREDEFINED_TIERS
            self.SUBSCRIPTION_TIERS = PREDEFINED_TIERS.copy()
        except ImportError:
            print("Warning: config.subscriptions module not found. Using empty subscription tiers.")
            self.SUBSCRIPTION_TIERS = {}

    def get_smart_api_instance(self) -> SmartApi:
        """
        Returns the Angel One SmartApi instance.
        """
        return self.smart_api_instance

    def connect(self) -> bool:
        """
        Connects to the Angel One SmartAPI using TOTP.

        Retrieves credentials from environment variables and attempts to log in.
        Updates the connection status.

        Returns:
            True if the connection (login) is successful, False otherwise.
        """
        global _is_api_connected # Ensure we modify the global flag

        if not isinstance(self.smart_api_instance, SmartApi) or self.smart_api_instance.__class__.__name__ == 'SmartApi':
            print("Error: SmartApi instance is not properly initialized or is a placeholder.")
            self._is_api_connected = False
            _is_api_connected = False
            return False

        if not (self.ANGEL_API_KEY and self.ANGEL_CLIENT_ID and self.ANGEL_PASSWORD and self.ANGEL_TOTP_KEY):
            print("Error: Missing Angel One API credentials. Cannot connect.")
            self._is_api_connected = False
            _is_api_connected = False
            return False

        try:
            totp = pyotp.TOTP(self.ANGEL_TOTP_KEY)
            totp_value = totp.at()

            print("Attempting to connect to Angel One SmartAPI...")
            login_response = self.smart_api_instance.login(
                self.ANGEL_CLIENT_ID,
                self.ANGEL_PASSWORD,
                totp_value
            )

            if login_response and login_response.get("status") == "success":
                print("Successfully connected to Angel One SmartAPI.")
                self._is_api_connected = True
                _is_api_connected = True # Update global flag
                return True
            else:
                print(f"Failed to connect to Angel One SmartAPI. Response: {login_response}")
                self._is_api_connected = False
                _is_api_connected = False
                return False
        except Exception as e:
            print(f"An error occurred during Angel One SmartAPI connection: {e}")
            self._is_api_connected = False
            _is_api_connected = False
            return False

    def is_connected(self) -> bool:
        """
        Checks if the Angel One SmartAPI is currently connected.

        Returns:
            True if connected, False otherwise.
        """
        # If the instance is a placeholder, it's not truly connected.
        if isinstance(self.smart_api_instance, SmartApi) and self.smart_api_instance.__class__.__name__ != 'SmartApi':
            return self._is_api_connected
        else:
            return False

    def get_ltp(self, exchange: str, symbol: str, token: Optional[str] = None) -> Optional[float]:
        """
        Fetches the Last Traded Price (LTP) for a given symbol and exchange.
        """
        if not self.is_connected():
            print("Error: Not connected to Angel One SmartAPI. Cannot fetch LTP.")
            return None

        try:
            instrument = {
                "exchange": exchange,
                "symbol": symbol
            }
            if token:
                instrument["symboltoken"] = token
            else:
                print(f"Warning: Token not provided for {symbol} on {exchange}. LTP fetch might be less reliable.")

            quotes = self.smart_api_instance.get_quotes([instrument])

            if quotes and quotes.get("status") == "success":
                quote_data = quotes.get("data", [])
                if quote_data:
                    ltp = quote_data[0].get("ltp")
                    if ltp is not None:
                        return float(ltp)
                    else:
                        print(f"LTP not found in quote data for {symbol} on {exchange}.")
                        return None
                else:
                    print(f"No quote data received for {symbol} on {exchange}.")
                    return None
            else:
                print(f"Failed to fetch quotes for {symbol} on {exchange}. Response: {quotes}")
                return None
        except Exception as e:
            print(f"An error occurred while fetching LTP for {symbol} on {exchange}: {e}")
            return None

    def get_candles(self, token: str, exchange: str, interval: str, fromdate: datetime.date, todate: datetime.date) -> Optional[List[Dict[str, Any]]]:
        """
        Fetches historical candle data (OHLCV) for a given instrument.
        """
        if not self.is_connected():
            print("Error: Not connected to Angel One SmartAPI. Cannot fetch candles.")
            return None

        try:
            from_date_str = fromdate.strftime('%Y-%m-%d')
            to_date_str = todate.strftime('%Y-%m-%d')

            print(f"Fetching candles for token {token} on {exchange} ({interval}) from {from_date_str} to {to_date_str}...")
            
            candles_data = self.smart_api_instance.get_candles(
                token,
                exchange,
                interval,
                from_date_str,
                to_date_str
            )

            if candles_data and candles_data.get("status") == "success":
                return candles_data.get("data", [])
            else:
                print(f"Failed to fetch candles for token {token} on {exchange}. Response: {candles_data}")
                return None
        except Exception as e:
            print(f"An error occurred while fetching candles for token {token} on {exchange}: {e}")
            return None

    # --- Subscription Management Functions ---
    def get_tier_data(self, tier_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves the data for a specific subscription tier."""
        return self.SUBSCRIPTION_TIERS.get(tier_name)

    def has_feature(self, tier_name: str, feature_name: str) -> bool:
        """Checks if a given tier has a specific feature."""
        tier_data = self.get_tier_data(tier_name)
        if tier_data is None:
            return False
        return feature_name in tier_data.get("features", [])

    def check_feature_access(self, role: str, feature: str) -> bool:
        """Checks if a given role (tier) has access to a specific feature."""
        return self.has_feature(role, feature)

    def days_remaining(self, created_at: datetime.datetime, role: str) -> Optional[int]:
        """Calculates the number of days remaining for a given role (tier)."""
        tier_data = self.get_tier_data(role)
        if tier_data is None:
            return None

        expiry_days = tier_data.get("expiry_days")
        if expiry_days is None:
            return None

        expiry_date = created_at + datetime.timedelta(days=expiry_days)
        days_left = (expiry_date - datetime.datetime.now()).days
        return max(0, days_left)

    def add_or_update_tier(self, tier_name: str, expiry_days: Optional[int], features: List[str]):
        """Adds or updates a subscription tier."""
        if tier_name in self.SUBSCRIPTION_TIERS:
            print(f"Info: Tier '{tier_name}' already exists. Updating.")
        self.SUBSCRIPTION_TIERS[tier_name] = {"expiry_days": expiry_days, "features": features}

    def remove_tier(self, tier_name: str):
        """Removes a subscription tier."""
        if tier_name in self.SUBSCRIPTION_TIERS:
            del self.SUBSCRIPTION_TIERS[tier_name]
            print(f"Info: Tier '{tier_name}' removed.")
        else:
            print(f"Warning: Tier '{tier_name}' not found for removal.")

def get_broker_instance() -> Broker:
    """
    Returns the singleton instance of the Broker.
    Creates it if it doesn't exist.
    """
    global _broker_instance
    if _broker_instance is None:
        _broker_instance = Broker()
    return _broker_instance

# --- Global accessors for convenience ---
# These functions delegate to the singleton broker instance.

def get_smart_api_instance_global() -> SmartApi:
    """Global accessor for the SmartApi instance."""
    return get_broker_instance().get_smart_api_instance()

def connect_global() -> bool:
    """Global accessor to connect the broker."""
    return get_broker_instance().connect()

def is_connected_global() -> bool:
    """Global accessor to check broker connection status."""
    return get_broker_instance().is_connected()

def get_ltp_global(exchange: str, symbol: str, token: Optional[str] = None) -> Optional[float]:
    """Global accessor to get LTP."""
    return get_broker_instance().get_ltp(exchange, symbol, token)

def get_candles_global(token: str, exchange: str, interval: str, fromdate: datetime.date, todate: datetime.date) -> Optional[List[Dict[str, Any]]]:
    """Global accessor to get candles."""
    return get_broker_instance().get_candles(token, exchange, interval, fromdate, todate)

# Subscription Management Global Accessors
def get_subscription_tier_data_global(tier_name: str) -> Optional[Dict[str, Any]]:
    """Global accessor for subscription tier data."""
    return get_broker_instance().get_tier_data(tier_name)

def does_tier_have_feature_global(tier_name: str, feature_name: str) -> bool:
    """Global accessor to check if a tier has a feature."""
    return get_broker_instance().has_feature(tier_name, feature_name)

def check_user_feature_access_global(role: str, feature: str) -> bool:
    """Global accessor to check user feature access."""
    return get_broker_instance().check_feature_access(role, feature)

def get_days_remaining_for_tier_global(created_at: datetime.datetime, role: str) -> Optional[int]:
    """Global accessor to get remaining days for a tier."""
    return get_broker_instance().days_remaining(created_at, role)

def add_or_update_subscription_tier_global(tier_name: str, expiry_days: Optional[int], features: List[str]):
    """Global accessor to add or update a subscription tier."""
    get_broker_instance().add_or_update_tier(tier_name, expiry_days, features)

def remove_subscription_tier_global(tier_name: str):
    """Global accessor to remove a subscription tier."""
    get_broker_instance().remove_tier(tier_name)
