import os
from dotenv import load_dotenv

# Load .env file
try:
    load_dotenv()
except Exception as e:
    print(f"Error loading .env file: {e}")

# Backend
FLASK_PORT = int(os.getenv('FLASK_PORT', 5002))
BACKEND_PORT = int(os.getenv('BACKEND_PORT', 5002))
BACKEND_URL = os.getenv('BACKEND_URL', 'bramha.cloud/v5')

# Auth
AUTH_METHOD = 'Firebase Gmail login'

# Database
DB_FIRESTORE = 'Firebase Firestore'
DB_SQLITE = 'SQLite local'
DB_SQLITE_PATH = 'data/db.sqlite3'

# Cache
CACHE_METHOD = 'File-based cache'
CACHE_PATH = 'data/cache'

# AI
AI_MODEL = 'Groq LLaMA 3.3 70B'
AI_XGBOOST = 'XGBoost'

# Broker
BROKER = 'Angel One SmartAPI'
BROKER_API_KEY = os.getenv('BROKER_API_KEY', 'default_api_key')
BROKER_API_SECRET = os.getenv('BROKER_API_SECRET', 'default_api_secret')
BROKER_USER_ID = os.getenv('BROKER_USER_ID', 'default_user_id')
BROKER_PASSWORD = os.getenv('BROKER_PASSWORD', 'default_password')

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
LOGS_PATH = 'data/logs'
RATE_LIMITER_ENABLED = True
RATE_LIMITER_MAX_REQUESTS = 100
RATE_LIMITER_TIME_WINDOW = 60  # in seconds
