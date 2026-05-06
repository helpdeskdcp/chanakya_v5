"""
Chanakya AI v5 — Capital Manager
Angel One live capital fetch + Smart Position Sizing
"""
import logging, requests
logger = logging.getLogger(__name__)

# Risk Management Settings (Mythos-level)
RISK_PER_TRADE_PCT  = 2.0   # Capital चा 2% per trade
MAX_DAILY_LOSS_PCT  = 5.0   # Capital चा 5% daily loss limit
MAX_TRADES_PER_DAY  = 5     # Max 5 trades per day
MIN_RR_RATIO        = 1.8   # Minimum Risk:Reward

# Paper Trading Virtual Capital
PAPER_CAPITAL       = 500000.0  # ₹5,00,000 virtual capital for paper trading

# MCX Lot Sizes
MCX_LOT_SIZES = {
    "CRUDEOIL":   100,
    "NATURALGAS": 1250,
    "GOLD":       100,
    "SILVER":     30000,
    "COPPER":     2500,
}

# NSE F&O Lot Sizes
FNO_LOT_SIZES = {
    "NIFTY":     75,
    "BANKNIFTY": 30,
    "FINNIFTY":  40,
    "SENSEX":    20,
}

def get_paper_capital():
    """Paper trading virtual capital"""
    return {
        "available":  PAPER_CAPITAL,
        "net":        PAPER_CAPITAL,
        "collateral": 0.0,
        "utilized":   0.0,
        "total":      PAPER_CAPITAL,
        "mode":       "PAPER_VIRTUAL",
    }

def get_capital(mode="PAPER"):
    """Mode based capital fetch"""
    if mode == "LIVE":
        cap = get_live_capital()
        return cap if cap else get_paper_capital()
    return get_paper_capital()

def get_live_capital():
    """Angel One से live capital fetch करतो"""
    try:
        from broker.global_broker import get_broker
        broker = get_broker()
        if not broker or not broker.is_connected():
            return None

        headers = {
            "Authorization": f"Bearer {broker.api.access_token}",
            "Content-Type":  "application/json",
            "X-UserType":    "USER",
            "X-SourceID":    "WEB",
            "X-ClientLocalIP":  "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress":     "00:00:00:00:00:00",
            "X-PrivateKey":     broker.api.api_key,
        }
        r = requests.get(
            "https://apiconnect.angelbroking.com/rest/secure/angelbroking/user/v1/getRMS",
            headers=headers, timeout=5
        )
        data = r.json()
        if data.get("status") and data.get("data"):
            d = data["data"]
            return {
                "available":    float(d.get("availablecash", 0)),
                "net":          float(d.get("net", 0)),
                "collateral":   float(d.get("collateral", 0)),
                "utilized":     float(d.get("utiliseddebits", 0)),
                "total":        float(d.get("net", 0)) + float(d.get("collateral", 0)),
            }
    except Exception as e:
        logger.error("get_live_capital: %s", e)
    return None

def calculate_position_size(symbol, exchange, entry, sl, capital=None):
    """
    Smart position sizing:
    Qty = (Capital × Risk%) / (Entry - SL)
    """
    try:
        if capital is None:
            cap_data = get_live_capital()
            capital  = cap_data["available"] if cap_data else 10000

        # Risk amount per trade
        risk_amount = capital * (RISK_PER_TRADE_PCT / 100)
        point_risk  = abs(entry - sl)

        if point_risk <= 0:
            return 1, {"error": "Invalid SL"}

        # Raw quantity
        raw_qty = risk_amount / point_risk

        # Lot size logic
        lot_size = 1
        if exchange == "MCX":
            lot_size = MCX_LOT_SIZES.get(symbol, 1)
        elif symbol in FNO_LOT_SIZES:
            lot_size = FNO_LOT_SIZES[symbol]

        # Number of lots
        if lot_size > 1:
            lots = max(1, round(raw_qty / lot_size))
            qty  = lots * lot_size
        else:
            # Equity — min 1 share, max based on capital
            qty = max(1, int(raw_qty))
            # Capital check: don't use more than 20% per trade
            max_qty = int((capital * 0.20) / entry) if entry > 0 else 1
            qty = min(qty, max(1, max_qty))
            lots = qty

        margin_required = qty * entry * 0.20  # 20% margin estimate

        return qty, {
            "capital":          round(capital, 2),
            "risk_amount":      round(risk_amount, 2),
            "point_risk":       round(point_risk, 2),
            "qty":              qty,
            "lots":             lots,
            "lot_size":         lot_size,
            "margin_est":       round(margin_required, 2),
            "can_trade":        capital >= margin_required,
            "risk_pct":         RISK_PER_TRADE_PCT,
        }
    except Exception as e:
        logger.error("position_size: %s", e)
        return 1, {"error": str(e)}

def get_daily_pnl():
    """आजचा realized PnL"""
    try:
        import sqlite3, datetime
        conn = sqlite3.connect("data/chanakya_v5.db")
        today = datetime.date.today().strftime("%Y-%m-%d")
        r = conn.execute(f"""
            SELECT 
                COUNT(*) trades,
                SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
                SUM(CASE WHEN pnl<=0 AND status='CLOSED' THEN 1 ELSE 0 END) losses,
                ROUND(SUM(CASE WHEN status='CLOSED' 
                    THEN pnl * COALESCE(NULLIF(lot_size,0),1) 
                    ELSE 0 END), 2) total_pnl,
                SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open
            FROM trades
            WHERE created_at >= '{today} 00:00:00'
        """).fetchone()
        conn.close()
        return {
            "trades": r[0], "wins": r[1] or 0,
            "losses": r[2] or 0, "total_pnl": r[3] or 0,
            "open": r[4] or 0
        }
    except Exception as e:
        logger.error("daily_pnl: %s", e)
        return {}

def check_daily_limit(capital=None):
    """Daily loss limit circuit breaker"""
    try:
        if capital is None:
            cap = get_live_capital()
            capital = cap["available"] if cap else 10000
        pnl_data = get_daily_pnl()
        daily_pnl = pnl_data.get("total_pnl", 0)
        max_loss  = capital * (MAX_DAILY_LOSS_PCT / 100)
        trades    = pnl_data.get("trades", 0)
        return {
            "can_trade":      daily_pnl > -max_loss and trades < MAX_TRADES_PER_DAY,
            "daily_pnl":      round(daily_pnl, 2),
            "max_loss":       round(-max_loss, 2),
            "trades_today":   trades,
            "max_trades":     MAX_TRADES_PER_DAY,
            "reason":         "OK" if daily_pnl > -max_loss else "DAILY_LOSS_LIMIT_HIT"
        }
    except Exception as e:
        logger.error("check_daily_limit: %s", e)
        return {"can_trade": True}

def get_full_analysis():
    """Complete capital + position analysis"""
    capital_data = get_live_capital()
    daily        = get_daily_pnl()
    limit        = check_daily_limit(capital_data["available"] if capital_data else None)
    return {
        "capital":    capital_data,
        "daily":      daily,
        "limit":      limit,
        "settings": {
            "risk_per_trade": f"{RISK_PER_TRADE_PCT}%",
            "max_daily_loss": f"{MAX_DAILY_LOSS_PCT}%",
            "max_trades":     MAX_TRADES_PER_DAY,
            "min_rr":         MIN_RR_RATIO,
        }
    }
