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
BROKER_API_KEY = 'YOUR_API_KEY'
BROKER_API_SECRET = 'YOUR_API_SECRET'
BROKER_USER_ID = 'YOUR_USER_ID'
BROKER_PASSWORD = 'YOUR_PASSWORD'

# Real-time
REALTIME_METHOD = 'SSE (Server-Sent Events)'

# Frontend
FRONTEND_TYPE = 'Single HTML file (SPA)'

# Subscription Tiers
SUBSCRIPTION_TIERS = {
    'developer': {'expiry': None, 'features': ['live_trading', 'paper_trading', 'global_broker', 'ai_model', 'xgboost', 'realtime_data']},
    'administrator': {'expiry': None, 'features': ['live_trading', 'paper_trading', 'global_broker', 'ai_model', 'xgboost', 'realtime_data']},
    'platinum': {'expiry': 365, 'features': ['live_trading', 'paper_trading', 'global_broker', 'ai_model', 'xgboost', 'realtime_data']},
    'gold': {'expiry': 180, 'features': ['live_trading', 'paper_trading', 'global_broker']},
    'silver': {'expiry': 90, 'features': ['paper_trading', 'global_broker']},
    'premium': {'expiry': 30, 'features': ['paper_trading']},
    'demo': {'expiry': 15, 'features': ['paper_trading', 'global_broker']}
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
