# Subscription Tier System

import datetime
from collections import defaultdict

class SubscriptionTier:
    def __init__(self, expiry, features):
        self.features = features  # features is now a list of strings
        self.expiry = datetime.timedelta(days=expiry) if isinstance(expiry, int) else None

class SubscriptionSystem:
    def __init__(self):
        self.tiers = defaultdict(SubscriptionTier)

    def add_tier(self, tier_name, expiry, features):
        self.tiers[tier_name] = SubscriptionTier(expiry, features)
