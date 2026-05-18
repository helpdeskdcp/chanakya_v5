import datetime

TIERS = {
    "developer":     {"expiry": None, "features": ["all"]},
    "administrator": {"expiry": None, "features": ["all"]},
    "platinum":      {"expiry": 365,  "features": ["live_trading","paper_trading","ai_chat","prediction","options_chain","equity_scanner","auto_trade","telegram","backtesting","analytics","admin"]},
    "gold":          {"expiry": 180,  "features": ["live_trading","paper_trading","ai_chat","prediction","equity_scanner","telegram","analytics"]},
    "silver":        {"expiry": 90,   "features": ["paper_trading","ai_chat","equity_scanner","basic_signals"]},
    "premium":       {"expiry": 30,   "features": ["paper_trading","basic_signals","ai_chat_basic"]},
    "demo":          {"expiry": 15,   "features": ["paper_trading","basic_signals"]},
}

def check_feature_access(role, feature):
    try:
        tier = TIERS.get(role, TIERS["demo"])
        features = tier.get("features", [])
        if "all" in features: return True
        return feature in features
    except: return False

def days_remaining(created_at, role):
    try:
        tier = TIERS.get(role, TIERS["demo"])
        expiry_days = tier.get("expiry")
        if expiry_days is None: return 99999
        if isinstance(created_at, str):
            created_at = datetime.datetime.strptime(created_at[:19], "%Y-%m-%d %H:%M:%S")
        return max(0, expiry_days - (datetime.datetime.now() - created_at).days)
    except: return 0

def is_active(created_at, role):
    try: return days_remaining(created_at, role) > 0
    except: return False

def get_tier_info(role):
    try:
        tier = TIERS.get(role, TIERS["demo"])
        return {"role":role,"expiry_days":tier.get("expiry"),"features":tier.get("features",[]),"is_lifetime":tier.get("expiry") is None}
    except: return {"role":"demo","expiry_days":15,"features":[],"is_lifetime":False}

def get_allowed_features(role):
    try:
        tier = TIERS.get(role, TIERS["demo"])
        if "all" in tier.get("features",[]): return ["all"]
        return tier.get("features",[])
    except: return []
