import logging, requests, re, time
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

NEWS_SOURCES = [
    "https://feeds.feedburner.com/ndtvprofit-latest",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.livemint.com/rss/markets",
]

_cache = {"news": [], "sentiment": {}, "ts": 0}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_rss(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200: return []
        text = r.text
        items = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
        news = []
        for item in items[:15]:
            # Handle CDATA titles
            title = (re.search(r'<title><!\[CDATA\[(.*?)\]\]>', item) or
                     re.search(r'<title>(.*?)</title>', item))
            desc  = (re.search(r'<description><!\[CDATA\[(.*?)\]\]>', item) or
                     re.search(r'<description>(.*?)</description>', item))
            pub   = re.search(r'<pubDate>(.*?)</pubDate>', item)
            if title:
                t = re.sub(r'<[^>]+>','', title.group(1)).strip()
                d = re.sub(r'<[^>]+>','', desc.group(1) if desc else "").strip()[:200]
                if len(t) > 10:
                    news.append({"title": t, "desc": d, "time": pub.group(1).strip() if pub else ""})
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
        news = fetch_rss(url)
        all_news.extend(news)
        if len(all_news) >= 20: break
    # Filter market-related news
    keywords = ["nifty","sensex","market","stock","share","trade","bse","nse",
                "crude","gold","rupee","sebi","rbi","fii","dii","ipo","budget"]
    filtered = [n for n in all_news if any(k in n["title"].lower() or k in n["desc"].lower() for k in keywords)]
    final = filtered[:20] if filtered else all_news[:20]
    if final:
        _cache["news"] = final
        _cache["ts"] = now
    return _cache["news"]

def analyze_sentiment(news_list, symbol=None):
    try:
        if not news_list:
            return {"score": 50, "label": "NEUTRAL", "reason": "No news available", "key_news": ""}
        from ai.groq_client import get_client
        client = get_client()
        if not client:
            return {"score": 50, "label": "NEUTRAL", "reason": "AI unavailable", "key_news": ""}
        headlines = "\n".join([f"- {n['title']}" for n in news_list[:10]])
        sym_filter = f"Focus on news related to {symbol}." if symbol else "Analyze overall Indian market sentiment."
        prompt = (
            f"Analyze these Indian market news headlines for sentiment.\n"
            f"{sym_filter}\n\n"
            f"HEADLINES:\n{headlines}\n\n"
            f"Respond ONLY in this exact JSON-like format:\n"
            f"SCORE: [number 0-100]\n"
            f"LABEL: [STRONGLY_BULLISH or BULLISH or NEUTRAL or BEARISH or STRONGLY_BEARISH]\n"
            f"REASON: [one line max 15 words]\n"
            f"KEY_NEWS: [most impactful headline max 10 words]\n"
        )
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=150, temperature=0.1
        )
        text = r.choices[0].message.content.strip()
        def extract(pattern, default):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else default
        score = int(extract(r'SCORE:\s*(\d+)', "50"))
        label = extract(r'LABEL:\s*(\S+)', "NEUTRAL")
        reason = extract(r'REASON:\s*(.+)', "")
        key = extract(r'KEY_NEWS:\s*(.+)', "")
        return {"score": score, "label": label, "reason": reason, "key_news": key, "count": len(news_list)}
    except Exception as e:
        logger.error("analyze_sentiment: %s", e)
        return {"score": 50, "label": "NEUTRAL", "reason": str(e), "key_news": ""}

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
                sym_news = [n for n in news if sym.upper() in n["title"].upper() or sym.upper() in n.get("desc","").upper()]
                if sym_news:
                    result["stocks"][sym] = analyze_sentiment(sym_news, sym)
                    time.sleep(0.5)
        _cache["sentiment"][cache_key] = {"data": result, "ts": now}
        return result
    except Exception as e:
        logger.error("get_market_sentiment: %s", e)
        return {"overall": {"score": 50, "label": "NEUTRAL"}, "error": str(e)}
