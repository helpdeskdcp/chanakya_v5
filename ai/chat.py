import os, logging, re
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

SYMBOLS = [
    ("NIFTY","99926000","NSE"),
    ("BANKNIFTY","99926009","NSE"),
    ("FINNIFTY","99926037","NSE"),
    ("CRUDEOIL","488290","MCX"),
    ("NATURALGAS","488505","MCX"),
    ("GOLD","67694","MCX"),
]

_scrip = None

def load_scrip():
    global _scrip
    if _scrip is None:
        try:
            import json
            data = json.load(open("/root/chanakya_v5/data/scrip_master.json"))
            _scrip = {}
            for s in data:
                sym = s.get("symbol","").upper().replace("-EQ","")
                if sym not in _scrip:
                    _scrip[sym] = {"token":s.get("token",""),"exch":s.get("exch_seg","NSE"),"name":s.get("symbol","")}
        except: _scrip = {}
    return _scrip

def get_context(broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        now = datetime.now(IST)
        h,mn = now.hour, now.minute
        nse = (9,15)<=(h,mn)<=(15,30) and now.weekday()<5
        mcx = ((9,0)<=(h,mn) or (h,mn)<=(23,30)) and now.weekday()<5
        parts = []
        parts.append("Time:" + now.strftime("%H:%M IST"))
        parts.append("NSE:" + ("OPEN" if nse else "CLOSED") + " MCX:" + ("OPEN" if mcx else "CLOSED"))
        if broker and broker.is_connected():
            from data_stream.cache import get as cget, set as cset
            ltps = []
            for name,token,exch in SYMBOLS:
                ltp = cget("ltp_"+name)
                if not ltp:
                    ltp = broker.get_ltp(exch, name, token)
                    if ltp: cset("ltp_"+name, ltp, ttl=5)
                if ltp: ltps.append(name+"="+str(int(ltp)))
            if ltps: parts.append("LTP:" + " | ".join(ltps))
        return "
".join(parts)
    except Exception as e:
        logger.error("get_context: %s", e)
        return "Market data unavailable"

def get_stock_ltp(symbol, broker=None):
    try:
        if broker is None:
            from broker.global_broker import get_broker
            broker = get_broker()
        for name,token,exch in SYMBOLS:
            if name.upper() == symbol.upper():
                return broker.get_ltp(exch, name, token)
        info = load_scrip().get(symbol.upper())
        if info:
            return broker.get_ltp(info["exch"], info["name"], info["token"])
    except: pass
    return None

def smart_chat(message, broker=None):
    try:
        from ai.groq_client import get_client
        client = get_client()
        if not client: return "AI unavailable"
        ctx = get_context(broker)
        words = re.findall(r"[A-Z]{3,}", message.upper())
        skip = {"LTP","LIVE","NSE","MCX","BSE","BUY","SELL","SIGNAL","AANI","KAAY","AAHE"}
        extra = []
        if broker and broker.is_connected():
            for w in words[:3]:
                if w not in skip:
                    ltp = get_stock_ltp(w, broker)
                    if ltp: extra.append(w+"="+str(ltp))
        if extra: ctx += "
STOCKS:" + " | ".join(extra)
        system = ("You are Chanakya AI, expert Indian trading assistant.
"
                  "LIVE DATA:
" + ctx + "
"
                  "Rules: Use live data, give Entry/Target/SL, "
                  "always answer, reply in user language, max 4 lines.")
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":system},{"role":"user","content":message}],
            max_tokens=300, temperature=0.3)
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error("smart_chat: %s", e)
        return "AI error: " + str(e)
