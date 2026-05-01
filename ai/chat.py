import os, logging, sqlite3
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

SYMBOLS = [
    ("NIFTY","99926000","NSE","index"),
    ("BANKNIFTY","99926009","NSE","index"),
    ("FINNIFTY","99926037","NSE","index"),
    ("CRUDEOIL","488290","MCX","commodity"),
    ("NATURALGAS","488505","MCX","commodity"),
    ("GOLD","67694","MCX","commodity"),
]

_scrip_master = None

def load_scrip_master():
    global _scrip_master
    if _scrip_master is None:
        try:
            import json
            path = "/root/chanakya_v5/data/scrip_master.json"
            if os.path.exists(path):
                data = json.load(open(path))
                _scrip_master = {}
                for s in data:
                    sym = s.get("symbol","").upper().replace("-EQ","")
                    if sym not in _scrip_master:
                        _scrip_master[sym] = {"token":s.get("token",""),"exch":s.get("exch_seg","NSE"),"name":s.get("symbol","")}
            else:
                _scrip_master = {}
        except: _scrip_master = {}
    return _scrip_master

def get_live_context(broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        data = {}
        if broker and broker.is_connected():
            from data_stream.cache import get as cget, set as cset
            for name,token,exch,typ in SYMBOLS:
                ckey = f"ltp_{name}"
                ltp = cget(ckey)
                if not ltp:
                    ltp = broker.get_ltp(exch, name, token)
                    if ltp: cset(ckey, ltp, ttl=5)
                if ltp: data[name] = ltp
        now = datetime.now(IST)
        h,mn = now.hour, now.minute
        nse = (9,15)<=(h,mn)<=(15,30) and now.weekday()<5
        mcx = ((9,0)<=(h,mn) or (h,mn)<=(23,30)) and now.weekday()<5
        lines = [f"Time:{now.strftime('%H:%M IST')}"]
        lines.append(f"NSE:{'OPEN' if nse else 'CLOSED'} MCX:{'OPEN' if mcx else 'CLOSED'}")
        if data:
            idx = [(k,v) for k,v in data.items() if k in ["NIFTY","BANKNIFTY","FINNIFTY"]]
            mcx_d = [(k,v) for k,v in data.items() if k in ["CRUDEOIL","NATURALGAS","GOLD"]]
            if idx: lines.append("INDEX:"+" | ".join([f"{k}={int(v)}" for k,v in idx]))
            if mcx_d: lines.append("MCX:"+" | ".join([f"{k}={int(v)}" for k,v in mcx_d]))
        return 'Market data unavailable'  #
".join(lines)
    except Exception as e:
        logger.error(f"live_context: {e}")
        return 'Market data unavailable'  #Market data unavailable"

def get_any_ltp(symbol, broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        # Check known symbols
        for name,token,exch,typ in SYMBOLS:
            if name.upper()==symbol.upper():
                return broker.get_ltp(exch, name, token)
        # Search scrip master
        master = load_scrip_master()
        info = master.get(symbol.upper())
        if info and broker:
            return broker.get_ltp(info["exch"], info["name"], info["token"])
    except: pass
    return None

def smart_chat(message, broker=None):
    try:
        from ai.groq_client import get_client
        client = get_client()
        if not client: return 'Market data unavailable'  #AI unavailable"
        ctx = get_live_context(broker)
        # Detect stock mentions
        import re
        words = re.findall(r"[A-Z]{3,}", message.upper())
        skip = {"LTP","LIVE","AANI","KAAY","AAHE","NSE","MCX","BSE",
                "BUY","SELL","SIGNAL","KAY","NAI","HAI","KAR","DIL"}
        extra_ltp = []
        if broker and broker.is_connected():
            for w in words[:3]:
                if w not in skip:
                    ltp = get_any_ltp(w, broker)
                    if ltp: extra_ltp.append(f"{w}={ltp}")
        if extra_ltp:
            ctx += "
STOCKS:" + " | ".join(extra_ltp)
        system = f"""You are Chanakya AI — expert Indian trading assistant.
LIVE DATA:
{ctx}
RULES:
- Use only live data for prices
- Give Entry/Target/SL for signals
- Always answer — never say data not available
- If market closed use prev close estimate
- Reply in same language as user (Marathi/Hindi/English)
- Max 4 lines"""
        from groq import Groq
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":system},{"role":"user","content":message}],
            max_tokens=300, temperature=0.3)
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"smart_chat: {e}")
        return f"AI error: {e}"
