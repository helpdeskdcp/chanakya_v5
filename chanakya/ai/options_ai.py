import logging, requests
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

def get_nse_chain(symbol="NIFTY"):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://www.nseindia.com/option-chain",
        }
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=headers, timeout=8)
        s.get("https://www.nseindia.com/option-chain", headers=headers, timeout=8)
        r = s.get(f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}",
                  headers=headers, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug("NSE chain: %s", e)
    return None

def analyze_chain(symbol="NIFTY", broker=None):
    try:
        data = get_nse_chain(symbol)
        if not data:
            return {"error": "NSE data unavailable", "symbol": symbol}
        records = data.get("records", {})
        filtered = data.get("filtered", {})
        atm = records.get("underlyingValue", 0)
        ce_oi = filtered.get("CE", {}).get("totOI", 0)
        pe_oi = filtered.get("PE", {}).get("totOI", 0)
        pcr = round(pe_oi/ce_oi, 2) if ce_oi > 0 else 1.0
        # Max pain
        strikes = {}
        for r in records.get("data", []):
            strike = r.get("strikePrice", 0)
            ce = r.get("CE", {}).get("openInterest", 0)
            pe = r.get("PE", {}).get("openInterest", 0)
            strikes[strike] = ce + pe
        max_pain = min(strikes, key=strikes.get) if strikes else 0
        # Top OI strikes
        ce_list = sorted([(r.get("strikePrice",0), r.get("CE",{}).get("openInterest",0))
                          for r in records.get("data",[]) if r.get("CE")], key=lambda x:-x[1])
        pe_list = sorted([(r.get("strikePrice",0), r.get("PE",{}).get("openInterest",0))
                          for r in records.get("data",[]) if r.get("PE")], key=lambda x:-x[1])
        resistance = ce_list[0][0] if ce_list else 0
        support    = pe_list[0][0] if pe_list else 0
        # Bias
        if pcr > 1.3: bias = "BULLISH"
        elif pcr < 0.7: bias = "BEARISH"
        else: bias = "NEUTRAL"
        # ATM options
        atm_strike = round(atm/50)*50
        atm_ce = next((r.get("CE",{}) for r in records.get("data",[]) if r.get("strikePrice")==atm_strike), {})
        atm_pe = next((r.get("PE",{}) for r in records.get("data",[]) if r.get("strikePrice")==atm_strike), {})
        return {
            "symbol": symbol, "atm": atm, "atm_strike": atm_strike,
            "pcr": pcr, "bias": bias, "max_pain": max_pain,
            "support_oi": support, "resistance_oi": resistance,
            "ce_oi": ce_oi, "pe_oi": pe_oi,
            "atm_ce_ltp": atm_ce.get("lastPrice", 0),
            "atm_pe_ltp": atm_pe.get("lastPrice", 0),
            "atm_ce_iv": round(atm_ce.get("impliedVolatility", 0), 1),
            "atm_pe_iv": round(atm_pe.get("impliedVolatility", 0), 1),
        }
    except Exception as e:
        logger.error("analyze_chain: %s", e)
        return {"error": str(e), "symbol": symbol}

def get_option_signal(symbol="NIFTY", broker=None):
    try:
        chain = analyze_chain(symbol, broker)
        if "error" in chain: return chain
        from ai.groq_client import get_client
        client = get_client()
        if not client: return chain
        prompt = (
            f"Options chain analysis for {symbol}:\n"
            f"ATM={chain['atm']} Strike={chain['atm_strike']}\n"
            f"PCR={chain['pcr']} Bias={chain['bias']}\n"
            f"Max Pain={chain['max_pain']}\n"
            f"Support(PE OI)={chain['support_oi']} Resistance(CE OI)={chain['resistance_oi']}\n"
            f"ATM CE LTP={chain['atm_ce_ltp']} IV={chain['atm_ce_iv']}%\n"
            f"ATM PE LTP={chain['atm_pe_ltp']} IV={chain['atm_pe_iv']}%\n"
            f"Give: 1) CE ya PE kharede? 2) ATM/ITM/OTM? 3) Entry/Target/SL 4) Risk level"
        )
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            max_tokens=200, temperature=0.2)
        chain["ai_signal"] = r.choices[0].message.content.strip()
        return chain
    except Exception as e:
        logger.error("option_signal: %s", e)
        return {"error": str(e)}
