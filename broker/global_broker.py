from typing import Optional, List
import config

def add_or_update_tier(self, tier_name: str, expiry_days: Optional[int], features: List[str]):
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
        return ltp
    except Exception as e:
        print(f"Error getting LTP global: {e}")
        return None
