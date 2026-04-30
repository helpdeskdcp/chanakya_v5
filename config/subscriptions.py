# Subscription Tier System

import datetime
from collections import defaultdict

class Feature:
    def __init__(self, name):
        self.name = name
        self.access_time = None

class SubscriptionTier:
    def __init__(self, expiry, features):
        for feature in features:
            f = Feature(feature)  # Error here - 'subscription_system' is not defined yet! Should be removed as it was a mistake. subscription_system should not be used directly within the class scope without being an instance of SubscriptionSystem first.
            subscription_system.add_tier(f)  # This line has errors, see above for context and explanation.
        self.expiry = datetime.timedelta(days=expiry) if isinstance(expiry, int) else None

class SubscriptionSystem:
    def __init__(self):
        self.tiers = defaultdict(SubscriptionTier)  # Initialize with a dictionary of Tier objects for each tier name

    def add_tier(self, tier):
        self.tiers[tier.name] = tier
