import threading, time
_lock = threading.Lock()
_state = {
    "broker_connected":False,"broker_session":None,"broker_client_id":None,
    "last_connect_at":0,"connect_count":0,"reconnect_count":0,
    "api_calls_total":0,"api_calls_minute":0,"api_window_start":time.time(),
    "market_open":False,"ltp_cache":{},"open_trades":0,"today_pnl":0.0,
    "startup_at":time.time(),"last_heartbeat":time.time(),"errors_today":0,
}
def get(key,default=None):
    with _lock: return _state.get(key,default)
def set(key,value):
    with _lock: _state[key]=value
def update(d):
    with _lock: _state.update(d)
def snapshot():
    with _lock: return dict(_state)
def increment(key,by=1):
    with _lock: _state[key]=_state.get(key,0)+by; return _state[key]
