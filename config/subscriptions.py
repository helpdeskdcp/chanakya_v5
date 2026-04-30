# Subscription Tier System

import datetime

class Feature:
    def __init__(self, name):
        self.name = name
        self.access_time = None

class SubscriptionTier:
    def __init__(self, expiry, features):
        for feature in features:
            f = Feature(feature)
            subscription_system.add_tier(f)
        self.expiry = datetime.timedelta(days=expiry) if isinstance(expiry, int) else None

class SubscriptionSystem:
    def __init__(self):
        self.tiers = {}

    def add_tier(self, tier):
        self.tiers[tier.name] = tier

    def get_tier(self, name):
        return self.tiers.get(name)

    def check_feature_access(self, role, feature):
        for tier in self.tiers.values():
            if not tier.expiry or datetime.datetime.now() < tier.expiry:
                continue  # Skip expired tiers and return False on first access attempt after expiration
            elif f := next((f for f in tier.features if f.name == feature), None):
                self.tiers[tier.name].access_time = datetime.datetime.now()
                return True  # Feature is accessible within this role and timeframe
        return False  # No access to the requested feature for any roles after expiration or if not found in current tiers

    def days_remaining(self, created_at, tier):
        remaining = (tier.expiry - datetime.datetime.now()).days + 1 if tier.expiry else None
        return f"{remaining} day{'s' if not remaining == 1 else ''}"
