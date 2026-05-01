# Subscription Tier System

import datetime
from collections import defaultdict

class Feature:
    def __init__(self, name):
        self.name = name
        self.access_time = None

class SubscriptionTier:
    def __init__(self, expiry, features):
        self.features = {}
        for feature_name in features:
            self.features[feature_name] = Feature(feature_name)
        self.expiry = datetime.timedelta(days=expiry) if isinstance(expiry, int) else None

class SubscriptionSystem:
    def __init__(self):
        self.tiers = defaultdict(SubscriptionTier)  # Initialize with a dictionary of Tier objects for each tier name

    def add_tier(self, tier_name, expiry, features):
        self.tiers[tier_name] = SubscriptionTier(expiry, features)
