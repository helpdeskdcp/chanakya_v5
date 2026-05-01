"""
Global Broker for Subscription Management and Angel One SmartAPI Connection.

This module acts as a central registry for subscription-related functions,
allowing access to subscription tier data and operations without direct
importing of the configuration module in every part of the application.
It also handles the initialization and access to the Angel One SmartAPI broker connection.
It follows a service locator pattern.
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

# --- Angel One SmartAPI Credentials ---
# Retrieve credentials from environment variables
ANGEL_API_KEY = os.environ.get("ANGEL_API_KEY")
ANGEL_CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID")
ANGEL_PASSWORD = os.environ.get("ANGEL_PASSWORD")
ANGEL_TOTP_KEY = os.environ.get("ANGEL_TOTP_KEY")

# Initialize SmartApi instance (or placeholder)
# This instance can be accessed globally.
smart_api_instance = None
_is_api_connected = False # Global flag to track connection status

if ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PASSWORD and ANGEL_TOTP_KEY:
    try:
        smart_api_instance = SmartApi(
            ANGEL_API_KEY,
            ANGEL_CLIENT_ID,
            ANGEL_PASSWORD,
            ANGEL_TOTP_KEY
        )
        print("Angel One SmartAPI instance created.")
        # Note: The actual connection happens in the connect() function.
        # We initialize the instance here, but it's not connected yet.
    except Exception as e:
        print(f"Error creating SmartApi instance: {e}")
        smart_api_instance = SmartApi() # Fallback to placeholder
else:
    print("Warning: Missing Angel One API credentials in environment variables. SmartApi will use placeholder.")
    smart_api_instance = SmartApi()

def get_smart_api_instance() -> SmartApi:
    """
    Returns the globally accessible Angel One SmartApi instance.

    Returns:
        The initialized SmartApi instance.
    """
    return smart_api_instance

def connect() -> bool:
    """
    Connects to the Angel One SmartAPI using TOTP.

    Retrieves credentials from environment variables and attempts to log in.
    Updates the global connection status flag.

    Returns:
        True if the connection (login) is successful, False otherwise.
    """
    global _is_api_connected # Declare intent to modify the global flag

    if not isinstance(smart_api_instance, SmartApi) or smart_api_instance.__class__.__name__ == 'SmartApi':
        print("Error: SmartApi instance is not properly initialized or is a placeholder.")
        _is_api_connected = False
        return False

    if not (ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PASSWORD and ANGEL_TOTP_KEY):
        print("Error: Missing Angel One API credentials. Cannot connect.")
        _is_api_connected = False
        return False

    try:
        # Generate TOTP
        totp = pyotp.TOTP(ANGEL_TOTP_KEY)
        totp_value = totp.at()

        # Attempt to login
        print("Attempting to connect to Angel One SmartAPI...")
        login_response = smart_api_instance.login(
            ANGEL_CLIENT_ID,
            ANGEL_PASSWORD,
            totp_value
        )

        if login_response and login_response.get("status") == "success":
            print("Successfully connected to Angel One SmartAPI.")
            _is_api_connected = True # Set connection status
            # You might want to store session tokens or other relevant info here
            # For example: smart_api_instance.session_token = login_response.get("jwtToken")
            return True
        else:
            print(f"Failed to connect to Angel One SmartAPI. Response: {login_response}")
            _is_api_connected = False
            return False
    except Exception as e:
        print(f"An error occurred during Angel One SmartAPI connection: {e}")
        _is_api_connected = False
        return False

def is_connected() -> bool:
    """
    Checks if the Angel One SmartAPI is currently connected.

    Returns:
        True if connected, False otherwise.
    """
    # If the instance is a placeholder, it's not truly connected.
    if isinstance(smart_api_instance, SmartApi) and smart_api_instance.__class__.__name__ != 'SmartApi':
        # If the actual SmartApi instance exists, rely on the global connection flag
        return _is_api_connected
    else:
        # If it's a placeholder or not initialized, it's not connected.
        return False

def get_ltp(exchange: str, symbol: str, token: Optional[str] = None) -> Optional[float]:
    """
    Fetches the Last Traded Price (LTP) for a given symbol and exchange.

    Args:
        exchange: The exchange code (e.g., 'NSE', 'BSE', 'NFO', 'MCX').
        symbol: The trading symbol (e.g., 'RELIANCE', 'INFY').
        token: The unique token for the instrument (optional, but recommended for accuracy).

    Returns:
        The LTP as a float, or None if it cannot be fetched or an error occurs.
    """
    if not is_connected():
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

        quotes = smart_api_instance.get_quotes([instrument])

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

def get_candles(token: str, exchange: str, interval: str, fromdate: datetime.date, todate: datetime.date) -> Optional[List[Dict[str, Any]]]:
    """
    Fetches historical candle data (OHLCV) for a given instrument.

    Args:
        token: The unique token for the instrument.
        exchange: The exchange code (e.g., 'NSE', 'BSE', 'NFO', 'MCX').
        interval: The candle interval (e.g., '1minute', '5minute', '1day').
        fromdate: The start date for fetching candles.
        todate: The end date for fetching candles.

    Returns:
        A list of dictionaries, where each dictionary represents a candle's data (e.g., 'open', 'high', 'low', 'close', 'volume', 'timestamp'),
        or None if data cannot be fetched or an error occurs.
    """
    if not is_connected():
        print("Error: Not connected to Angel One SmartAPI. Cannot fetch candles.")
        return None

    try:
        from_date_str = fromdate.strftime('%Y-%m-%d')
        to_date_str = todate.strftime('%Y-%m-%d')

        print(f"Fetching candles for token {token} on {exchange} ({interval}) from {from_date_str} to {to_date_str}...")
        
        candles_data = smart_api_instance.get_candles(
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


# --- Subscription Management Logic ---
# Import the core subscription logic from the configuration module.
try:
    from config.subscriptions import (
        SUBSCRIPTION_TIERS as CONFIG_SUBSCRIPTION_TIERS,
        get_tier_data as config_get_tier_data,
        has_feature as config_has_feature,
        check_feature_access as config_check_feature_access,
        days_remaining as config_days_remaining,
        add_or_update_tier as config_add_or_update_tier,
        remove_tier as config_remove_tier
    )
except ImportError:
    print("Warning: config.subscriptions module not found. Using mock subscription functions.")
    CONFIG_SUBSCRIPTION_TIERS = {}
    def config_get_tier_data(tier_name: str) -> Optional[Dict[str, Any]]: return None
    def config_has_feature(tier_name: str, feature_name: str) -> bool: return False
    def config_check_feature_access(role: str, feature: str) -> bool: return False
    def config_days_remaining(created_at: datetime.datetime, role: str) -> Optional[int]: return None
    def config_add_or_update_tier(tier_name: str, expiry_days: Optional[int], features: List[str]): pass
    def config_remove_tier(tier_name: str): pass


# Expose the raw tier data dictionary for inspection if needed.
ALL_SUBSCRIPTION_TIERS: Dict[str, Dict[str, Any]] = CONFIG_SUBSCRIPTION_TIERS

def get_subscription_tier_data(tier_name: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the data dictionary for a specific subscription tier.
    """
    return config_get_tier_data(tier_name)

def does_tier_have_feature(tier_name: str, feature_name: str) -> bool:
    """
    Checks if a given subscription tier includes a specific feature.
    """
    return config_has_feature(tier_name, feature_name)

def check_user_feature_access(role: str, feature: str) -> bool:
    """
    Checks if a user's role (subscription tier) grants access to a specific feature.
    """
    return config_check_feature_access(role, feature)

def get_days_remaining_for_tier(created_at: datetime.datetime, role: str) -> Optional[int]:
    """
    Calculates the number of days remaining until a user's subscription tier expires.
    """
    return config_days_remaining(created_at, role)

def add_or_update_subscription_tier(tier_name: str, expiry_days: Optional[int], features: List[str]):
    """
    Adds a new subscription tier or updates an existing one globally.
    """
    config_add_or_update_tier(tier_name, expiry_days, features)

def remove_subscription_tier(tier_name: str):
    """
    Removes a subscription tier from the global configuration.
    """
    config_remove_tier(tier_name)
