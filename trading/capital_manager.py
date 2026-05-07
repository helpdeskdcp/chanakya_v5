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

# Paper Trading Virtual Capital (per user)
DEFAULT_PAPER_CAPITAL = 200000.0  # ₹2,00,000 default per user

# ── Correct Lot Sizes (verified May 2026) ────────────
MCX_LOT_SIZES = {
    "CRUDEOIL":   100,    # 100 barrels/lot
    "CRUDEOILM":  10,     # Mini crude
    "NATURALGAS": 1250,   # 1250 MMBtu/lot
    "GOLD":       1000,   # 1 KG = 1000 gms/lot
    "GOLDM":      100,    # 100 gms (Mini gold)
    "SILVER":     30000,  # 30 KGS = 30,000 gms/lot
    "SILVERM":    5000,   # 5 KGS mini
    "COPPER":     2500,
    "ZINC":       5000,
    "LEAD":       5000,
    "NICKEL":     1500,
    "ALUMINIUM":  5000,
}

# NSE F&O Lot Sizes (corrected)
FNO_LOT_SIZES = {
    "NIFTY":      65,     # corrected from 75
    "BANKNIFTY":  30,
    "FINNIFTY":   60,     # corrected from 40
    "MIDCPNIFTY": 120,
    "SENSEX":     20,
}

# Master lot size lookup
ALL_LOT_SIZES = {**MCX_LOT_SIZES, **FNO_LOT_SIZES}

def get_lot_size(symbol, exchange="NSE"):
    """Symbol चा correct lot size return करतो"""
    sym = symbol.upper().replace("-EQ","").replace("-I","")
    if sym in ALL_LOT_SIZES:
        return ALL_LOT_SIZES[sym]
    if exchange == "MCX":
        return MCX_LOT_SIZES.get(sym, 1)
    if exchange == "NSE" and sym in FNO_LOT_SIZES:
        return FNO_LOT_SIZES[sym]
    return 1  # Equity = 1 share

def get_paper_capital(username="avinash"):
    """User-specific paper capital from DB"""
    try:
        import sqlite3, datetime
        conn = sqlite3.connect("data/chanakya_v5.db")
        r = conn.execute(
            "SELECT capital, initial_capital, total_pnl FROM paper_capital WHERE username=?",
            (username,)).fetchone()
        conn.close()
        if r:
            return {
                "available":        round(r[0], 2),
                "net":              round(r[0], 2),
                "initial_capital":  round(r[1], 2),
                "total_pnl":        round(r[2], 2),
                "collateral":       0.0,
                "utilized":         0.0,
                "total":            round(r[0], 2),
                "mode":             "PAPER_VIRTUAL",
                "username":         username,
            }
    except Exception as e:
        logger.error("get_paper_capital: %s", e)
    return {
        "available": DEFAULT_PAPER_CAPITAL,
        "net": DEFAULT_PAPER_CAPITAL,
        "initial_capital": DEFAULT_PAPER_CAPITAL,
        "total_pnl": 0.0,
        "mode": "PAPER_VIRTUAL",
    }

def update_paper_capital(username, pnl, trade_id=None):
    """Trade close झाल्यावर capital update"""
    try:
        import sqlite3, datetime
        conn = sqlite3.connect("data/chanakya_v5.db")
        conn.row_factory = sqlite3.Row
        r = conn.execute(
            "SELECT capital, total_pnl FROM paper_capital WHERE username=?",
            (username,)).fetchone()
        if not r:
            # New user — create with default
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""INSERT INTO paper_capital
                (username, capital, initial_capital, total_pnl, updated_at, updated_by)
                VALUES (?,?,?,0,?,'system')""",
                (username, DEFAULT_PAPER_CAPITAL, DEFAULT_PAPER_CAPITAL, now))
            conn.commit()
            r = conn.execute(
                "SELECT capital, total_pnl FROM paper_capital WHERE username=?",
                (username,)).fetchone()
        new_capital  = round(r["capital"] + pnl, 2)
        new_total    = round(r["total_pnl"] + pnl, 2)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""UPDATE paper_capital SET
            capital=?, total_pnl=?, updated_at=?, updated_by='system'
            WHERE username=?""", (new_capital, new_total, now, username))
        # Ledger entry
        note = f"Trade #{trade_id}" if trade_id else "PnL update"
        conn.execute("""INSERT INTO capital_ledger
            (username, type, amount, balance_after, note, done_by, created_at)
            VALUES (?,?,?,?,?,'system',?)""",
            (username, "PNL", pnl, new_capital, note, now))
        conn.commit(); conn.close()
        return new_capital
    except Exception as e:
        logger.error("update_paper_capital: %s", e)
        return None

def admin_topup(username, amount, done_by="administrator", note="Top-up"):
    """Admin: capital add/deduct करतो"""
    try:
        import sqlite3, datetime
        conn = sqlite3.connect("data/chanakya_v5.db")
        r = conn.execute(
            "SELECT capital FROM paper_capital WHERE username=?",
            (username,)).fetchone()
        if not r:
            return {"success": False, "error": "User not found"}
        new_capital = round(r[0] + amount, 2)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""UPDATE paper_capital SET
            capital=?, updated_at=?, updated_by=?
            WHERE username=?""", (new_capital, now, done_by, username))
        type_ = "TOPUP" if amount > 0 else "DEDUCT"
        conn.execute("""INSERT INTO capital_ledger
            (username, type, amount, balance_after, note, done_by, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (username, type_, amount, new_capital, note, done_by, now))
        conn.commit(); conn.close()
        logger.info("Admin %s: %s Rs%s → balance Rs%s", done_by, type_, amount, new_capital)
        return {"success": True, "username": username,
                "amount": amount, "new_capital": new_capital}
    except Exception as e:
        logger.error("admin_topup: %s", e)
        return {"success": False, "error": str(e)}

def get_capital(mode="PAPER", username="avinash"):
    """Mode based capital fetch"""
    if mode == "LIVE":
        cap = get_live_capital()
        return cap if cap else get_paper_capital(username)
    return get_paper_capital(username)

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
