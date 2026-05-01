"""
Global Broker for Subscription Management.

This module acts as a central registry for subscription-related functions,
allowing access to subscription tier data and operations without direct
importing of the configuration module in every part of the application.
It follows a service locator pattern.
"""

import datetime
from typing import Dict, List, Optional, Any

# Import the core subscription logic from the configuration module.
# We assume config.subscriptions provides the necessary functions and data structures.
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
    # Provide mock implementations if config.subscriptions is not available
    # This allows the broker to be imported even if the config is missing,
    # though functions relying on it will fail or return defaults.
    print("Warning: config.subscriptions module not found. Using mock subscription functions.")
    CONFIG_SUBSCRIPTION_TIERS = {}
    def config_get_tier_data(tier_name: str) -> Optional[Dict[str, Any]]: return None
    def config_has_feature(tier_name: str, feature_name: str) -> bool: return False
    def config_check_feature_access(role: str, feature: str) -> bool: return False
    def config_days_remaining(created_at: datetime.datetime, role: str) -> Optional[int]: return None
    def config_add_or_update_tier(tier_name: str, expiry_days: Optional[int], features: List[str]): pass
    def config_remove_tier(tier_name: str): pass


# --- Global Access to Subscription Data and Functions ---

# Expose the raw tier data dictionary for inspection if needed.
# It's generally better to use the provided functions for interaction.
ALL_SUBSCRIPTION_TIERS: Dict[str, Dict[str, Any]] = CONFIG_SUBSCRIPTION_TIERS

def get_subscription_tier_data(tier_name: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the data dictionary for a specific subscription tier.

    Args:
        tier_name: The name of the tier to retrieve.

    Returns:
        A dictionary containing the tier's data (e.g., 'expiry_days', 'features')
        if the tier is found, otherwise None.
    """
    return config_get_tier_data(tier_name)

def does_tier_have_feature(tier_name: str, feature_name: str) -> bool:
    """
    Checks if a given subscription tier includes a specific feature.

    Args:
        tier_name: The name of the subscription tier.
        feature_name: The name of the feature to check for.

    Returns:
        True if the tier exists and has the feature, False otherwise.
    """
    return config_has_feature(tier_name, feature_name)

def check_user_feature_access(role: str, feature: str) -> bool:
    """
    Checks if a user's role (subscription tier) grants access to a specific feature.

    This is a convenience wrapper around the underlying check_feature_access function.

    Args:
        role: The name of the user's subscription tier (e.g., 'premium', 'free').
        feature: The name of the feature to check access for.

    Returns:
        True if the role has access to the feature, False otherwise.
    """
    return config_check_feature_access(role, feature)

def get_days_remaining_for_tier(created_at: datetime.datetime, role: str) -> Optional[int]:
    """
    Calculates the number of days remaining until a user's subscription tier expires.

    Args:
        created_at: The datetime when the user's current tier was assigned or activated.
        role: The name of the user's subscription tier.

    Returns:
        The number of days remaining until the tier expires.
        Returns None if the tier does not expire, the tier is not found, or an error occurs.
    """
    return config_days_remaining(created_at, role)

def add_or_update_subscription_tier(tier_name: str, expiry_days: Optional[int], features: List[str]):
    """
    Adds a new subscription tier or updates an existing one globally.

    This function modifies the underlying subscription tier configuration.

    Args:
        tier_name: The name of the tier to add or update.
        expiry_days: The number of days until the tier expires. Use None for no expiry.
        features: A list of strings representing the features included in this tier.
    """
    config_add_or_update_tier(tier_name, expiry_days, features)

def remove_subscription_tier(tier_name: str):
    """
    Removes a subscription tier from the global configuration.

    Args:
        tier_name: The name of the tier to remove.
    """
    config_remove_tier(tier_name)

# --- Example of adding another global service ---
# import logging
# global_logger = logging.getLogger("app_logger")
#
# def get_global_logger():
#     """Returns the globally configured logger instance."""
#     return global_logger
