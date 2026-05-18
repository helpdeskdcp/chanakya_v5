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
            data = json.load(open("/app/chanakya/data/scrip_master.json"))
            _scrip = {}
            for s in data:
                sym = s.get("symbol","").upper().replace("-EQ","")
                if sym not in _scrip:
                    _scrip[sym] = {"token":s.get("token",""),"exch":s.get("exch_seg","NSE"),"name":s.get("symbol","")}
        except:
            _scrip = {}
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
        return "\n".join(parts)
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
    except:
        pass
    return None

def get_options_ctx(message):
    try:
        from ai.options_ai import analyze_chain
        msg_up = message.upper()
        if not any(x in msg_up for x in ["NIFTY","BANKNIFTY","OPTION","CE","PE","OTM","ATM","ITM"]):
            return ""
        sym = "BANKNIFTY" if "BANKNIFTY" in msg_up else "NIFTY"
        chain = analyze_chain(sym)
        if not chain or "error" in chain:
            return ""
        return ("OPTIONS " + sym + ":"
                + " PCR=" + str(chain.get("pcr",""))
                + " Bias=" + str(chain.get("bias",""))
                + " MaxPain=" + str(chain.get("max_pain",""))
                + " Support=" + str(chain.get("support_oi",""))
                + " Resistance=" + str(chain.get("resistance_oi",""))
                + " ATM_CE=" + str(chain.get("atm_ce_ltp",""))
                + " ATM_PE=" + str(chain.get("atm_pe_ltp",""))
                + " ATM_CE_IV=" + str(chain.get("atm_ce_iv","")) + "%"
                + " ATM_PE_IV=" + str(chain.get("atm_pe_iv","")) + "%")
    except:
        return ""

def smart_chat(message, broker=None):
    try:
        from ai.groq_client import get_client
        client = get_client()
        if not client: return "AI unavailable"
        ctx = get_context(broker)
        # Stock LTP lookup
        words = re.findall(r"[A-Z]{3,}", message.upper())
        skip = {"LTP","LIVE","NSE","MCX","BSE","BUY","SELL","SIGNAL","AANI","KAAY","AAHE","CE","PE","ATM","OTM","ITM"}
        extra = []
        if broker and broker.is_connected():
            for w in words[:3]:
                if w not in skip:
                    ltp = get_stock_ltp(w, broker)
                    if ltp: extra.append(w+"="+str(ltp))
        if extra: ctx += "\nSTOCKS:" + " | ".join(extra)
        # Options context
        opt_ctx = get_options_ctx(message)
        if opt_ctx: ctx += "\n" + opt_ctx
        sys_msg = ("You are Chanakya AI, expert Indian trading assistant.\n"
                   "LIVE DATA:\n" + ctx + "\n"
                   "Rules:\n"
                   "- Use live data above\n"
                   "- For options: suggest CE/PE, ATM/ITM/OTM with entry/target/SL\n"
                   "- PCR>1.2=bullish(buy CE), PCR<0.8=bearish(buy PE)\n"
                   "- Max Pain = strong support/resistance\n"
                   "- Give specific Entry/Target/SL always\n"
                   "- Reply in user language (Marathi/Hindi/English)\n"
                   "- Max 4 lines")
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":sys_msg},{"role":"user","content":message}],
            max_tokens=300, temperature=0.3)
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error("smart_chat: %s", e)
        return "AI error: " + str(e)
