"""
Chanakya Groq Client™ — Multi-model rotation + cache
Auto-fallback when rate limit hit
"""
import os, logging, time, hashlib
from dotenv import load_dotenv
load_dotenv("/app/chanakya/.env")
logger = logging.getLogger(__name__)

# Model rotation — fallback order
MODELS = [
    "llama-3.3-70b-versatile",     # Primary
    "llama-3.1-8b-instant",        # Fast fallback
    "gemma2-9b-it",                # Backup 1
    "mixtral-8x7b-32768",          # Backup 2
]

_client = None
_cache = {}           # Simple response cache
_cache_ttl = {}       # Cache TTL
_current_model_idx = 0
_model_errors = {}    # Track errors per model

class _RotatingClient:
    """Wrapper that auto-rotates models on rate limit"""
    def __init__(self, groq_client):
        self._c = groq_client
        self.chat = self
        self.completions = self
        self._model_idx = 0
        self._errors = {}

    def create(self, model=None, messages=None, max_tokens=300, temperature=0.3, **kwargs):
        import time
        MODELS = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it",
        ]
        for m in MODELS:
            if self._errors.get(m,0) >= 2: continue
            try:
                r = self._c.chat.completions.create(
                    model=m, messages=messages,
                    max_tokens=max_tokens, temperature=temperature
                )
                self._errors[m] = 0
                return r
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    self._errors[m] = self._errors.get(m,0) + 1
                    continue
                raise
        raise Exception("All models rate limited — try again in 15 min")

def get_client():
    global _client
    if _client: return _client
    try:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key: return None
        _client = _RotatingClient(Groq(api_key=api_key))
        return _client
    except Exception as e:
        logger.error("Groq init: %s", e)
        return None

def get_best_model():
    """Get model with least errors"""
    global _current_model_idx
    for i, model in enumerate(MODELS):
        if _model_errors.get(model, 0) < 3:
            _current_model_idx = i
            return model
    # Reset after 30 min
    _model_errors.clear()
    return MODELS[0]

def cache_key(prompt, model):
    return hashlib.md5((prompt+model).encode()).hexdigest()[:16]

def ask(prompt, max_tokens=400, use_cache=True, temperature=0.3):
    """
    Smart ask with:
    - Model rotation on rate limit
    - Response caching (5 min)
    - Shorter prompts for efficiency
    """
    client = get_client()
    if not client: return "AI unavailable"

    # Check cache
    ck = cache_key(prompt[:100], "any")
    now = time.time()
    if use_cache and ck in _cache:
        if now - _cache_ttl.get(ck, 0) < 300:  # 5 min cache
            return _cache[ck]

    # Try each model
    for model in MODELS:
        if _model_errors.get(model, 0) >= 3:
            continue
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role":"user","content":prompt}],
                max_tokens=max_tokens,
                temperature=temperature
            )
            resp = r.choices[0].message.content.strip()
            # Cache successful response
            _cache[ck] = resp
            _cache_ttl[ck] = now
            # Reset error count on success
            _model_errors[model] = 0
            return resp
        except Exception as e:
            err = str(e)
            if '429' in err or 'rate_limit' in err:
                _model_errors[model] = _model_errors.get(model, 0) + 1
                logger.warning("Rate limit %s, trying next model", model)
                continue
            else:
                logger.error("Groq %s: %s", model, err)
                return f"AI error: {err[:100]}"

    return "Rate limit on all models — please wait 15 minutes"

def ask_short(prompt, max_tokens=150):
    """Short response — token efficient"""
    return ask(prompt, max_tokens=max_tokens, temperature=0.1)

def get_signal_analysis(symbol, ltp, rsi, ema_trend, vwap_dist):
    """
    Efficient signal analysis — minimal tokens
    """
    prompt = (
        f"Indian trading AI. Symbol:{symbol} LTP:₹{ltp} RSI:{rsi} "
        f"EMA:{ema_trend} VWAP_Gap:{vwap_dist}%\n"
        f"Give: SIGNAL(BUY_CE/BUY_PE/HOLD) SCORE(0-100) REASON(10 words max)"
    )
    return ask_short(prompt, max_tokens=60)

