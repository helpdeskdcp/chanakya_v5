import logging, requests, re, time, os
from dotenv import load_dotenv
load_dotenv("/root/chanakya_v5/.env")
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
NEWS_SOURCES = [
    "https://feeds.feedburner.com/ndtvprofit-latest",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
]
ALIASES = {
    "CRUDEOIL":   ["CRUDE","OIL","BRENT","WTI","CRUDE OIL","PETROLEUM"],
    "NATURALGAS": ["NATURAL GAS","NATGAS","GAS","LNG","NG"],
    "GOLD":       ["GOLD","YELLOW METAL","MCX GOLD","BULLION"],
    "SILVER":     ["SILVER","MCX SILVER"],
    "NIFTY":      ["NIFTY","NIFTY50","SENSEX","MARKET","NSE","INDICES"],
    "BANKNIFTY":  ["BANK NIFTY","BANKNIFTY","BANKING","BANK INDEX","BANKEX"],
    "FINNIFTY":   ["FINNIFTY","FINANCIAL","FIN NIFTY"],
}
_cache = {"news": [], "sentiment": {}, "ts": 0}

def fetch_rss(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200: return []
        items = re.findall(r'<item>(.*?)</item>', r.text, re.DOTALL)
        news = []
        for item in items[:15]:
            title = (re.search(r'<title><!\[CDATA\[(.*?)\]\]>', item) or
                     re.search(r'<title>(.*?)</title>', item))
            desc  = (re.search(r'<description><!\[CDATA\[(.*?)\]\]>', item) or
                     re.search(r'<description>(.*?)</description>', item))
            pub   = re.search(r'<pubDate>(.*?)</pubDate>', item)
            if title:
                t = re.sub(r'<[^>]+>','', title.group(1)).strip()
                d = re.sub(r'<[^>]+>','', desc.group(1) if desc else "").strip()[:200]
                if len(t) > 10:
                    news.append({"title":t,"desc":d,"time":pub.group(1).strip() if pub else ""})
        return news
    except Exception as e:
        logger.debug("RSS %s: %s", url, e)
        return []

def get_live_news():
    now = time.time()
    if _cache["news"] and now - _cache["ts"] < 300:
        return _cache["news"]
    all_news = []
    for url in NEWS_SOURCES:
        all_news.extend(fetch_rss(url))
        if len(all_news) >= 20: break
    keywords = ["nifty","sensex","market","stock","share","trade","bse","nse",
                "crude","gold","rupee","sebi","rbi","fii","dii","gas","oil","silver"]
    filtered = [n for n in all_news if any(k in n["title"].lower() or k in n["desc"].lower() for k in keywords)]
    final = filtered[:20] if filtered else all_news[:20]
    if final:
        _cache["news"] = final
        _cache["ts"] = now
    return _cache["news"]

def search_news(news, symbol):
    terms = ALIASES.get(symbol.upper(), [symbol.upper()])
    return [n for n in news if any(t in n["title"].upper() or t in n.get("desc","").upper() for t in terms)]

def analyze_sentiment(news_list, symbol=None):
    try:
        if not news_list:
            return {"score":50,"label":"NEUTRAL","reason":"No news available","key_news":""}
        from ai.groq_client import get_client
        client = get_client()
        if not client:
            return {"score":50,"label":"NEUTRAL","reason":"AI unavailable","key_news":""}
        headlines = "\n".join([f"- {n['title']}" for n in news_list[:10]])
        sym_filter = f"Focus on news related to {symbol}." if symbol else "Analyze overall Indian market sentiment."
        prompt = (f"Analyze these Indian market news headlines for sentiment.\n{sym_filter}\n\n"
                  f"HEADLINES:\n{headlines}\n\n"
                  f"Respond ONLY in this format:\n"
                  f"SCORE: [0-100]\nLABEL: [STRONGLY_BULLISH/BULLISH/NEUTRAL/BEARISH/STRONGLY_BEARISH]\n"
                  f"REASON: [one line max 15 words]\nKEY_NEWS: [most impactful headline max 10 words]\n")
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=150, temperature=0.1)
        text = r.choices[0].message.content.strip()
        def ex(pat, default):
            m = re.search(pat, text, re.IGNORECASE)
            return m.group(1).strip() if m else default
        return {
            "score":   int(ex(r'SCORE:\s*(\d+)', "50")),
            "label":   ex(r'LABEL:\s*(\S+)', "NEUTRAL"),
            "reason":  ex(r'REASON:\s*(.+)', ""),
            "key_news":ex(r'KEY_NEWS:\s*(.+)', ""),
            "count":   len(news_list),
        }
    except Exception as e:
        logger.error("analyze_sentiment: %s", e)
        return {"score":50,"label":"NEUTRAL","reason":str(e),"key_news":""}

def get_market_sentiment(symbols=None):
    try:
        now = time.time()
        cache_key = "market_" + (symbols[0] if symbols else "all")
        if cache_key in _cache["sentiment"]:
            entry = _cache["sentiment"][cache_key]
            if now - entry.get("ts",0) < 300:
                return entry["data"]
        news = get_live_news()
        overall = analyze_sentiment(news)
        result = {
            "overall": overall,
            "news_count": len(news),
            "latest_headlines": [n["title"] for n in news[:5]],
            "timestamp": datetime.now(IST).strftime("%H:%M IST"),
        }
        if symbols:
            result["stocks"] = {}
            for sym in symbols[:3]:
                sym_news = search_news(news, sym)
                if sym_news:
                    result["stocks"][sym] = analyze_sentiment(sym_news, sym)
                    time.sleep(0.5)
        _cache["sentiment"][cache_key] = {"data":result,"ts":now}
        return result
    except Exception as e:
        logger.error("get_market_sentiment: %s", e)
        return {"overall":{"score":50,"label":"NEUTRAL"},"error":str(e)}
