import threading,time,logging
logger=logging.getLogger(__name__)
class RateLimiter:
    def __init__(self,max_per_second=2,max_per_minute=100):
        self.mps=max_per_second; self.mpm=max_per_minute
        self._lock=threading.Lock(); self._tokens=float(max_per_second)
        self._last=time.time(); self._min_count=0; self._min_start=time.time()
    def acquire(self,timeout=10):
        dl=time.time()+timeout
        while time.time()<dl:
            with self._lock:
                now=time.time(); e=now-self._last
                self._tokens=min(self.mps,self._tokens+e*self.mps); self._last=now
                if now-self._min_start>=60: self._min_count=0; self._min_start=now
                if self._tokens>=1 and self._min_count<self.mpm:
                    self._tokens-=1; self._min_count+=1; return True
            time.sleep(0.1)
        return False
    def stats(self):
        with self._lock:
            return {"tokens":round(self._tokens,2),"calls_min":self._min_count}
_limiter=RateLimiter()
def acquire(timeout=10): return _limiter.acquire(timeout)
def stats(): return _limiter.stats()
def rate_limited(f):
    from functools import wraps
    @wraps(f)
    def w(*a,**k):
        if not acquire(5): return None
        return f(*a,**k)
    return w
