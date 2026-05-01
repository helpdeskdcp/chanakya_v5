from typing import Optional, List
import config
import datetime

def add_or_update_subscription_tier_global(self, tier_name: str, expiry_days: Optional[int], features: List[str]):
    try:
        if tier_name in config.subscriptions:
            print(f"Info: Tier '{tier_name}' already exists. Updating.")
        if expiry_days is None:
            raise ValueError("Expiry days cannot be None")
        config.subscriptions[tier_name] = {"expiry_days": expiry_days, "features": features}
    except Exception as e:
        print(f"Error updating tier: {e}")

def get_ltp_global(exchange: str, symbol: str, token: Optional[str] = None) -> Optional[float]:
    try:
        # Your code to get LTP global
        ltp_value = 123.45  # Replace with actual value
        return ltp_value
    except Exception as e:
        print(f"Error getting LTP global: {e}")
        return None

def does_tier_have_feature_global(tier_name: str, feature_name: str) -> bool:
    try:
        tier_data = config.subscriptions.get(tier_name)
        if tier_data is None:
            return False
        return feature_name in tier_data.get("features", [])
    except Exception as e:
        print(f"Error checking feature access: {e}")
        return False

def check_user_feature_access_global(role: str, feature: str) -> bool:
    try:
        tier_data = config.subscriptions.get(role)
        if tier_data is None:
            return False
        return feature in tier_data.get("features", [])
    except Exception as e:
        print(f"Error checking feature access: {e}")
        return False

def get_days_remaining_for_tier_global(created_at: datetime.datetime, role: str) -> Optional[int]:
    try:
        tier_data = config.subscriptions.get(role)
        if tier_data is None:
            return None
        expiry_days = tier_data.get("expiry_days")
        if expiry_days is None:
            return None
        days_left = (datetime.datetime.now() - created_at).days
        return max(0, expiry_days - days_left)
    except Exception as e:
        print(f"Error calculating days remaining: {e}")
        return None

def remove_subscription_tier_global(self, tier_name: str):
    try:
        if tier_name in config.subscriptions:
            del config.subscriptions[tier_name]
            print(f"Info: Tier '{tier_name}' removed.")
        else:
            print(f"Warning: Tier '{tier_name}' not found for removal.")
    except Exception as e:
        print(f"Error removing tier: {e}")
