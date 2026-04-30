# Subscription Tier System

class SubscriptionTier:
    def __init__(self, name, expiry, features):
        self.name = name
        self.expiry = expiry
        self.features = features

class SubscriptionSystem:
    def __init__(self):
        self.tiers = {}

    def add_tier(self, tier):
        self.tiers[tier.name] = tier

    def get_tier(self, name):
        return self.tiers.get(name)

    def get_all_tiers(self):
        return list(self.tiers.values())

# Define subscription tiers
subscription_system = SubscriptionSystem()

subscription_system.add_tier(
    SubscriptionTier(
        'developer',
        None,
        ['live_trading', 'paper_trading', 'global_broker', 'ai_model', 'xgboost', 'realtime_data']
    )
)

subscription_system.add_tier(
    SubscriptionTier(
        'administrator',
        None,
        ['live_trading', 'paper_trading', 'global_broker', 'ai_model', 'xgboost', 'realtime_data'],
        max_users=100
    )
)

subscription_system.add_tier(
    SubscriptionTier(
        'platinum',
        365,
        [
            'live_trading',
            'paper_trading',
            'ai_chat',
            'prediction',
            'options_chain',
            'equity_scanner',
            'auto_trade',
            'telegram_alerts',
            'backtesting',
            'advanced_analytics'
        ]
    )
)

subscription_system.add_tier(
    SubscriptionTier(
        'gold',
        180,
        ['live_trading', 'paper_trading', 'global_broker']
    )
)

subscription_system.add_tier(
    SubscriptionTier(
        'silver',
        90,
        ['paper_trading', 'global_broker']
    )
)

subscription_system.add_tier(
    SubscriptionTier(
        'premium',
        30,
        ['paper_trading']
    )
)

subscription_system.add_tier(
    SubscriptionTier(
        'demo',
        15,
        ['paper_trading', 'global_broker']
    )
)
