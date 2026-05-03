import logging, requests, re
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

NEWS_SOURCES = [
    {
        "name": "Economic Times Markets",
        "url": "https://economictimes.indiatimes.com/markets/rss.cms",
        "type": "rss"
    },
    {
        "name": "Moneycontrol",
        "url": "https://www.moneycontrol.com/rss/latestnews.xml",
        "type": "rss"
    },
    {
        "name": "NSE India",
        "url": "https://www.nseindia.com/api/news",
        "type": "json"
    },
]

_cache = {"news": [], "sentiment": {}, "ts": 0}

def fetch_rss(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200: return []
        items = re.findall(r'<item>(.*?)</item>', r.text, re.DOTALL)
        news = []
        for item in items[:15]:
            title = re.search(r'<title>(.*?)</title>', item)
            desc  = re.search(r'<description>(.*?)</description>', item)
            pub   = re.search(r'<pubDate>(.*?)</pubDate>', item)
            if title:
                news.append({
                    "title": re.sub(r'<[^>]+>','', title.group(1)).strip(),
                    "desc":  re.sub(r'<[^>]+>','', desc.group(1) if desc else "").strip()[:200],
                    "time":  pub.group(1).strip() if pub else "",
                })
        return news
    except Exception as e:
        logger.debug("RSS fetch %s: %s", url, e)
        return []

def get_live_news():
    import time
    now = time.time()
    if _cache["news"] and now - _cache["ts"] < 300:
        return _cache["news"]
    all_news = []
    for src in NEWS_SOURCES[:2]:
        if src["type"] == "rss":
            news = fetch_rss(src["url"])
            all_news.extend(news)
    if all_news:
        _cache["news"] = all_news[:20]
        _cache["ts"] = now
    return _cache["news"]

def analyze_sentiment(news_list, symbol=None):
    try:
        if not news_list: return {"score": 50, "label": "NEUTRAL", "reason": "No news available"}
        from ai.groq_client import get_client
        client = get_client()
        if not client: return {"score": 50, "label": "NEUTRAL", "reason": "AI unavailable"}
        headlines = "\n".join([f"- {n['title']}" for n in news_list[:10]])
        sym_filter = f"Focus on news related to {symbol}." if symbol else "Analyze overall market sentiment."
        prompt = (
            f"Analyze these Indian market news headlines for sentiment.\n"
            f"{sym_filter}\n\n"
            f"HEADLINES:\n{headlines}\n\n"
            f"Respond ONLY in this exact format:\n"
            f"SCORE: [0-100]\n"
            f"LABEL: [STRONGLY_BULLISH/BULLISH/NEUTRAL/BEARISH/STRONGLY_BEARISH]\n"
            f"REASON: [one line reason in simple English]\n"
            f"KEY_NEWS: [most impactful headline in 10 words]\n"
        )
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=150, temperature=0.1
        )
        text = r.choices[0].message.content.strip()
        score  = int(re.search(r'SCORE:\s*(\d+)', text).group(1)) if re.search(r'SCORE:\s*(\d+)', text) else 50
        label  = re.search(r'LABEL:\s*(\S+)', text).group(1) if re.search(r'LABEL:\s*(\S+)', text) else "NEUTRAL"
        reason = re.search(r'REASON:\s*(.+)', text).group(1).strip() if re.search(r'REASON:\s*(.+)', text) else ""
        key    = re.search(r'KEY_NEWS:\s*(.+)', text).group(1).strip() if re.search(r'KEY_NEWS:\s*(.+)', text) else ""
        return {"score": score, "label": label, "reason": reason, "key_news": key, "headlines_count": len(news_list)}
    except Exception as e:
        logger.error("analyze_sentiment: %s", e)
        return {"score": 50, "label": "NEUTRAL", "reason": str(e)}

def get_market_sentiment(symbols=None):
    import time
    try:
        cache_key = "market"
        now = time.time()
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
