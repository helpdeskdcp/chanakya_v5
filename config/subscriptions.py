import datetime

# --- Data Structure for Tiers ---
# Tiers will be stored in a dictionary where:
# key: tier_name (str)
# value: dict with keys:
#   'expiry_days': int | None (number of days until expiry, None for no expiry)
#   'features': list[str] (list of feature names)

# --- Predefined Tiers ---
# This dictionary will be initialized when the module is loaded or when SubscriptionSystem is instantiated.
# For simplicity and to avoid class instantiation, we'll define the initial tiers here.
# In a real application, this might be loaded from a config file or database.

PREDEFINED_TIERS = {
    "developer": {"expiry_days": None, "features": [
        "basic_analytics", "advanced_analytics", "email_support",
        "phone_support", "api_access", "custom_branding",
        "unlimited_storage", "priority_support", "dedicated_account_manager"
    ]},
    "administrator": {"expiry_days": None, "features": [
        "basic_analytics", "advanced_analytics", "email_support",
        "phone_support", "api_access", "custom_branding",
        "unlimited_storage", "priority_support", "dedicated_account_manager"
    ]},
    "free": {"expiry_days": 30, "features": ["basic_analytics", "email_support"]},
    "basic": {"expiry_days": 30, "features": ["basic_analytics", "email_support", "api_access"]},
    "silver": {"expiry_days": 90, "features": ["advanced_analytics", "email_support", "api_access", "custom_branding"]},
    "premium": {"expiry_days": 30, "features": ["advanced_analytics", "phone_support", "api_access", "custom_branding", "unlimited_storage"]},
    "platinum": {"expiry_days": 365, "features": ["advanced_analytics", "phone_support", "api_access", "custom_branding", "unlimited_storage", "priority_support"]},
    "gold": {"expiry_days": 180, "features": ["advanced_analytics", "phone_support", "api_access", "custom_branding", "unlimited_storage"]},
    "enterprise": {"expiry_days": 365, "features": [
        "advanced_analytics", "phone_support", "api_access", "custom_branding",
        "unlimited_storage", "priority_support", "dedicated_account_manager"
    ]},
    "trial": {"expiry_days": 7, "features": ["basic_analytics", "email_support", "api_access"]},
    "demo": {"expiry_days": 15, "features": ["basic_analytics", "email_support", "api_access"]},
}

# --- Global state for tiers ---
# In a system without classes, we might use a global dictionary to hold the tiers.
# This mimics the behavior of SubscriptionSystem.tiers.
# If you need to dynamically add/modify tiers, you'd need functions to manage this global dict.
SUBSCRIPTION_TIERS = PREDEFINED_TIERS.copy()

# --- Functions ---

def get_tier_data(tier_name: str) -> dict | None:
    """
    Retrieves the data for a specific subscription tier.

    Args:
        tier_name: The name of the tier to retrieve.

    Returns:
        A dictionary containing the tier's data (expiry_days, features) if found, otherwise None.
    """
    return SUBSCRIPTION_TIERS.get(tier_name)

def has_feature(tier_name: str, feature_name: str) -> bool:
    """
    Checks if a given tier has a specific feature.

    Args:
        tier_name: The name of the tier to check.
        feature_name: The name of the feature to look for.

    Returns:
        True if the tier exists and has the feature, False otherwise.
    """
    tier_data = get_tier_data(tier_name)
    if tier_data is None:
        return False
    return feature_name in tier_data.get("features", [])

def check_feature_access(role: str, feature: str) -> bool:
    """
    Checks if a given role (tier) has access to a specific feature.

    Args:
        role: The name of the subscription tier (e.g., 'premium', 'free').
        feature: The name of the feature to check access for.

    Returns:
        True if the role has access to the feature, False otherwise.
    """
    return has_feature(role, feature)

def days_remaining(created_at: datetime.datetime, role: str) -> int | None:
    """
    Calculates the number of days remaining for a given role (tier).

    Args:
        created_at: The datetime when the role was created or assigned.
        role: The name of the subscription tier (e.g., 'premium', 'free').

    Returns:
        The number of days remaining until the tier expires.
        Returns None if the tier does not expire or if the tier is not found.
    """
    tier_data = get_tier_data(role)
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

# --- Optional: Functions to manage tiers dynamically ---
# If you need to add or modify tiers after initialization, you would add functions like these:

def add_or_update_tier(tier_name: str, expiry_days: int | None, features: list[str]):
    """
    Adds or updates a subscription tier in the global SUBSCRIPTION_TIERS dictionary.

    Args:
        tier_name: The name of the tier (e.g., 'free', 'premium').
        expiry_days: The number of days until the tier expires. If None, the tier does not expire.
        features: A list of strings representing the features included in this tier.
    """
    if tier_name in SUBSCRIPTION_TIERS:
        print(f"Info: Tier '{tier_name}' already exists. Updating.")
    SUBSCRIPTION_TIERS[tier_name] = {"expiry_days": expiry_days, "features": features}

def remove_tier(tier_name: str):
    """
    Removes a subscription tier from the global SUBSCRIPTION_TIERS dictionary.

    Args:
        tier_name: The name of the tier to remove.
    """
    if tier_name in SUBSCRIPTION_TIERS:
        del SUBSCRIPTION_TIERS[tier_name]
        print(f"Info: Tier '{tier_name}' removed.")
    else:
        print(f"Warning: Tier '{tier_name}' not found for removal.")

