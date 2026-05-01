# This module will act as a central point for managing global objects or services
# that need to be accessible throughout the application without direct dependency injection.
# It's a simple form of a service locator pattern.

# Example: A global instance of the subscription system
# In a more complex application, this could be initialized with configuration.
import datetime
from config.subscriptions import SUBSCRIPTION_TIERS, get_tier_data, has_feature, check_feature_access, days_remaining, add_or_update_tier, remove_tier

# We can expose the functions directly or wrap them if needed.
# For now, let's expose the core functions and the tier data.

# Expose the tier data dictionary
ALL_SUBSCRIPTION_TIERS = SUBSCRIPTION_TIERS

# Expose the functions for interacting with subscription tiers
def get_subscription_tier_data(tier_name: str):
    """Retrieves data for a specific subscription tier."""
    return get_tier_data(tier_name)

def does_tier_have_feature(tier_name: str, feature_name: str) -> bool:
    """Checks if a tier has a specific feature."""
    return has_feature(tier_name, feature_name)

def check_user_feature_access(role: str, feature: str) -> bool:
    """Checks if a user's role (tier) grants access to a feature."""
    return check_feature_access(role, feature)

def get_days_remaining_for_tier(created_at: datetime.datetime, role: str) -> int | None:
    """Calculates remaining days for a user's tier."""
    return days_remaining(created_at, role)

def add_or_update_subscription_tier(tier_name: str, expiry_days: int | None, features: list[str]):
    """Adds or updates a subscription tier globally."""
    add_or_update_tier(tier_name, expiry_days, features)

def remove_subscription_tier(tier_name: str):
    """Removes a subscription tier globally."""
    remove_tier(tier_name)

# You can add more global objects or functions here as needed.
# For example:
#
# import logging
# global_logger = logging.getLogger("app_logger")
#
# def get_global_logger():
#     return global_logger
