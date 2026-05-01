import time, threading

_cache = {}
_lock = threading.Lock()

def set(key, value, ttl=60):
    try:
        with _lock:
            _cache[key] = {"v": value, "exp": time.time() + ttl}
    except: pass

def get(key):
    try:
        with _lock:
            item = _cache.get(key)
            if item and time.time() < item["exp"]:
                return item["v"]
            if item: del _cache[key]
    except: pass
    return None

def delete(key):
    try:
        with _lock:
            _cache.pop(key, None)
    except: pass

def clear_expired():
    try:
        with _lock:
            now = time.time()
            expired = [k for k,v in _cache.items() if v["exp"] < now]
            for k in expired: del _cache[k]
    except: pass
