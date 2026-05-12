import threading,logging,time
from collections import defaultdict
logger=logging.getLogger(__name__)
_subscribers=defaultdict(list)
_lock=threading.Lock()
_history=[]
BROKER_CONNECTED="broker.connected"
BROKER_DISCONNECTED="broker.disconnected"
SIGNAL_GENERATED="signal.generated"
TRADE_OPENED="trade.opened"
TRADE_CLOSED="trade.closed"
MARKET_OPEN="market.open"
MARKET_CLOSED="market.closed"
def subscribe(event,cb):
    with _lock: _subscribers[event].append(cb)
def publish(event,data=None):
    data=data or {}
    with _lock:
        callbacks=list(_subscribers.get(event,[]))
        _history.append({"event":event,"data":data,"ts":time.time()})
        if len(_history)>50: _history.pop(0)
    for cb in callbacks:
        threading.Thread(target=_safe,args=(cb,event,data),daemon=True).start()
def _safe(cb,event,data):
    try: cb(data)
    except Exception as e: logger.error(f"EventBus [{event}] {cb.__name__}: {e}")
def get_history():
    with _lock: return list(_history)

def get_subscribers():
    with _lock:
        return {k:[c.__name__ for c in v] for k,v in _subscribers.items()}
