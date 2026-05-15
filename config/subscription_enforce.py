"""
Chanakya AI Mythos — Subscription Enforcement
Feature gating per subscription plan
"""
import functools
from flask import request, jsonify

PLAN_HIERARCHY = {
    "demo": 0, "premium": 1, "gold": 2,
    "platinum": 3, "enterprise": 4,
    "administrator": 5, "developer": 6
}

PLAN_FEATURES = {
    "nse_signals_view":   ["demo","premium","gold","platinum","enterprise","administrator","developer"],
    "nse_signals_buy":    ["premium","gold","platinum","enterprise","administrator","developer"],
    "mcx_signals":        ["gold","platinum","enterprise","administrator","developer"],
    "options_chain_nse":  ["gold","platinum","enterprise","administrator","developer"],
    "options_chain_mcx":  ["platinum","enterprise","administrator","developer"],
    "auto_trading":       ["platinum","enterprise","administrator","developer"],
    "backtesting":        ["gold","platinum","enterprise","administrator","developer"],
    "telegram_alerts":    ["premium","gold","platinum","enterprise","administrator","developer"],
    "ai_chat":            ["premium","gold","platinum","enterprise","administrator","developer"],
    "api_access":         ["enterprise","developer"],
    "admin_panel":        ["administrator","developer"],
    "system_config":      ["developer"],
}

DAILY_LIMITS = {
    "demo":       {"signal_views": 3, "buys": 0, "mcx": 0},
    "premium":    {"signal_views": 99, "buys": 10, "mcx": 0},
    "gold":       {"signal_views": 99, "buys": 99, "mcx": 5},
    "platinum":   {"signal_views": 999, "buys": 999, "mcx": 999},
    "enterprise": {"signal_views": 999, "buys": 999, "mcx": 999},
    "administrator": {"signal_views": 999, "buys": 999, "mcx": 999},
    "developer":  {"signal_views": 999, "buys": 999, "mcx": 999},
}

def get_user_plan():
    role = getattr(request, "role", "demo")
    return role.lower() if role else "demo"

def has_feature(feature):
    plan = get_user_plan()
    return plan in PLAN_FEATURES.get(feature, [])

def require_feature(feature):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            plan = get_user_plan()
            allowed = PLAN_FEATURES.get(feature, [])
            if plan not in allowed:
                min_plan = allowed[0] if allowed else "platinum"
                return jsonify({
                    "success": False,
                    "error": f"Upgrade required for {feature}",
                    "current_plan": plan,
                    "required_plan": min_plan,
                    "upgrade_url": "/v5/upgrade",
                    "plans": allowed
                }), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator

def get_daily_limit(limit_type):
    plan = get_user_plan()
    limits = DAILY_LIMITS.get(plan, DAILY_LIMITS["demo"])
    return limits.get(limit_type, 0)
