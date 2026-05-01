import os, logging
logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_API_KEY","")
MODEL = "llama-3.3-70b-versatile"
_client = None

def get_client():
    global _client
    if not _client:
        try:
            from groq import Groq
            _client = Groq(api_key=GROQ_KEY)
        except Exception as e:
            logger.error(f"Groq init: {e}")
    return _client

def ask(prompt, system="You are Chanakya AI, expert Indian trading assistant.", max_tokens=300, temperature=0.3):
    try:
        client = get_client()
        if not client: return ""
        msgs = []
        if system: msgs.append({"role":"system","content":system})
        msgs.append({"role":"user","content":prompt})
        r = client.chat.completions.create(model=MODEL, messages=msgs,
            max_tokens=max_tokens, temperature=temperature)
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq ask: {e}"); return ""

def analyze_signal(signal_dict, market_context=""):
    try:
        sym = signal_dict.get("symbol","")
        entry = signal_dict.get("entry",0)
        sl = signal_dict.get("sl",0)
        target = signal_dict.get("target",0)
        rsi = signal_dict.get("rsi",50)
        score = signal_dict.get("score",0)
        rr = round((target-entry)/(entry-sl),1) if entry>sl else 0
        prompt = f"{market_context}\nSignal: {sym} BUY Rs{entry} SL={sl} T={target} RSI={rsi} Score={score} RR={rr}\nGive 1-line verdict: STRONG/MODERATE/WEAK + reason"
        return ask(prompt, max_tokens=80, temperature=0.1)
    except: return "MODERATE signal"

def chat_with_context(message, live_data={}):
    try:
        ctx_parts = []
        for k,v in live_data.items():
            ctx_parts.append(f"{k}={v}")
        ctx = " | ".join(ctx_parts)
        system = f"""You are Chanakya AI, expert Indian trading assistant.
LIVE DATA: {ctx}
Reply in same language as user. Max 4 lines. Give Entry/Target/SL for signals."""
        return ask(message, system=system, max_tokens=300)
    except Exception as e:
        return f"AI error: {e}"
