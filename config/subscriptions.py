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
            f = Feature(feature)
            subscription_system.add_tier(f)  # Error here - 'subscription_system' is not defined yet!
        self.expiry = datetime.timedelta(days=expiry) if isinstance(expiry, int) else None

class SubscriptionSystem:
    def __init__(self):
        self.tiers = defaultdict(SubscriptionTier)  # Initialize with a dictionary of Tier objects for each tier name

    def add_tier(self, tier):
        self.tiers[tier.name] = tier

# Rest of the code remains unchanged...
