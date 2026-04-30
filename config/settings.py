import os

# Backend
BACKEND_PORT = 5002
BACKEND_URL = 'bramha.cloud/v5'

# Auth
AUTH_METHOD = 'Firebase Gmail login'

# Database
DB_FIRESTORE = 'Firebase Firestore'
DB_SQLITE = 'SQLite local'

# Cache
CACHE_METHOD = 'File-based cache'

# AI
AI_MODEL = 'Groq LLaMA 3.3 70B'
AI_XGBOOST = 'XGBoost'

# Broker
BROKER = 'Angel One SmartAPI'

# Real-time
REALTIME_METHOD = 'SSE (Server-Sent Events)'

# Frontend
FRONTEND_TYPE = 'Single HTML file (SPA)'

# Subscription Tiers
SUBSCRIPTION_TIERS = {
    'developer': {'expiry': None, 'features': 'ALL'},
    'administrator': {'expiry': None, 'features': 'ALL'},
    'platinum': {'expiry': 365, 'features': 'all features'},
    'gold': {'expiry': 180, 'features': 'live trading'},
    'silver': {'expiry': 90, 'features': 'paper only'},
    'premium': {'expiry': 30, 'features': 'basic'},
    'demo': {'expiry': 15, 'features': 'paper + global broker'}
}

# Key Principles
KEY_PRINCIPLES = [
    'Global broker always connected (24x7)',
    'One data fetch → cached → all engines use',
    'Paper and Live completely separate',
    'No duplicate API calls',
    'Rate limit safe',
    'Crash proof — try/except everywhere'
]
