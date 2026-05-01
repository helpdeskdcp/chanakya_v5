# Subscription Tier System

import datetime

class SubscriptionTier:
    """Represents a subscription tier with an expiry duration and a list of features."""
    def __init__(self, expiry_days: int | None, features: list[str]):
        """
        Initializes a SubscriptionTier.

        Args:
            expiry_days: The number of days until the tier expires. If None, the tier does not expire.
            features: A list of strings, where each string is a feature name.
        """
        self.features = features
        self.expiry = datetime.timedelta(days=expiry_days) if expiry_days is not None else None

class SubscriptionSystem:
    """Manages different subscription tiers."""
    def __init__(self):
        """Initializes the SubscriptionSystem with predefined tiers."""
        self.tiers: dict[str, SubscriptionTier] = {}
        self._initialize_tiers()

    def _initialize_tiers(self):
        """Sets up the default subscription tiers."""
        # Define a comprehensive list of all possible features
        all_features = [
            "basic_analytics", "advanced_analytics", "email_support",
            "phone_support", "api_access", "custom_branding",
            "unlimited_storage", "priority_support", "dedicated_account_manager"
        ]

        # Define the tiers
        self.add_tier("developer", None, all_features)  # No expiry, all features
        self.add_tier("administrator", None, all_features) # No expiry, all features
        self.add_tier("free", 30, ["basic_analytics", "email_support"])
        self.add_tier("basic", 30, ["basic_analytics", "email_support", "api_access"])
        self.add_tier("standard", 30, ["advanced_analytics", "email_support", "api_access", "custom_branding"])
        self.add_tier("premium", 30, ["advanced_analytics", "phone_support", "api_access", "custom_branding", "unlimited_storage"])
        self.add_tier("enterprise", 365, ["advanced_analytics", "phone_support", "api_access", "custom_branding", "unlimited_storage", "priority_support", "dedicated_account_manager"])
        self.add_tier("trial", 7, ["basic_analytics", "email_support", "api_access"]) # Example trial tier

    def add_tier(self, tier_name: str, expiry_days: int | None, features: list[str]):
        """
        Adds or updates a subscription tier in the system.

        Args:
            tier_name: The name of the tier (e.g., 'free', 'premium').
            expiry_days: The number of days until the tier expires. If None, the tier does not expire.
            features: A list of strings representing the features included in this tier.
        """
        if tier_name in self.tiers:
            print(f"Info: Tier '{tier_name}' already exists. Updating.")
        self.tiers[tier_name] = SubscriptionTier(expiry_days, features)

    def get_tier(self, tier_name: str) -> SubscriptionTier | None:
        """
        Retrieves a subscription tier by its name.

        Args:
            tier_name: The name of the tier to retrieve.

        Returns:
            The SubscriptionTier object if found, otherwise None.
        """
        return self.tiers.get(tier_name)

    def has_feature(self, tier_name: str, feature_name: str) -> bool:
        """
        Checks if a given tier has a specific feature.

        Args:
            tier_name: The name of the tier to check.
            feature_name: The name of the feature to look for.

        Returns:
            True if the tier exists and has the feature, False otherwise.
        """
        tier = self.get_tier(tier_name)
        return tier is not None and feature_name in tier.features
