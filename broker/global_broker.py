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
except ImportError:
    print("Warning: smartapi library not found. SmartApi functionalities will not be available.")
    # Define a placeholder if SmartApi is not found, to avoid NameError
    class SmartApi:
        def __init__(self, *args, **kwargs):
            print("SmartApi placeholder initialized. Actual API connection not available.")
            pass

# --- Angel One SmartAPI Credentials ---
# Retrieve credentials from environment variables
ANGEL_API_KEY = os.environ.get("ANGEL_API_KEY")
ANGEL_CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID")
ANGEL_PASSWORD = os.environ.get("ANGEL_PASSWORD")
ANGEL_TOTP_KEY = os.environ.get("ANGEL_TOTP_KEY")

# Initialize SmartApi instance (or placeholder)
# This instance can be accessed globally.
# In a real application, you might want to add error handling if credentials are missing.
if ANGEL_API_KEY and ANGEL_CLIENT_ID and ANGEL_PASSWORD and ANGEL_TOTP_KEY:
    try:
        # Attempt to initialize SmartApi with credentials
        # Note: The actual login/session management might happen elsewhere or on first use.
        # For now, we just instantiate it.
        smart_api_instance = SmartApi(
            ANGEL_API_KEY,
            ANGEL_CLIENT_ID,
            ANGEL_PASSWORD,
            ANGEL_TOTP_KEY
        )
        print("Angel One SmartAPI instance initialized successfully.")
    except Exception as e:
        print(f"Error initializing SmartApi instance: {e}")
        # Fallback to placeholder if initialization fails
        smart_api_instance = SmartApi()
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
