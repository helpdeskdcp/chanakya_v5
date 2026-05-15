import sqlite3
from datetime import datetime

DB = "data/chanakya_v5.db"


def get_atm_strike(spot, step):
    return round(float(spot) / step) * step


def get_nearest_expiry(symbol="NIFTY"):
    conn = sqlite3.connect(DB)

    rows = conn.execute("""
        SELECT DISTINCT expiry
        FROM instruments
        WHERE name=?
        AND instrumenttype='OPTIDX'
        ORDER BY expiry ASC
    """, (symbol,)).fetchall()

    conn.close()

    today = datetime.now()

    valid = []

    for r in rows:
        try:
            dt = datetime.strptime(r[0], "%d%b%Y")
            if dt >= today:
                valid.append(dt)
        except:
            pass

    if not valid:
        return None

    return valid[0].strftime("%d%b%Y").upper()


def find_option(symbol, spot, opt_type="CE"):
    step_map = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "FINNIFTY": 50,
        "MIDCPNIFTY": 25
    }

    step = step_map.get(symbol, 50)

    atm = get_atm_strike(spot, step)

    expiry = get_nearest_expiry(symbol)

    conn = sqlite3.connect(DB)

    row = conn.execute("""
        SELECT token, symbol, strike, expiry
        FROM instruments
        WHERE name=?
        AND instrumenttype='OPTIDX'
        AND expiry=?
        AND strike=?
        AND symbol LIKE ?
        LIMIT 1
    """, (
        symbol,
        expiry,
        atm,
        f"%{opt_type}"
    )).fetchone()

    conn.close()

    if not row:
        return None

    return {
        "token": row[0],
        "symbol": row[1],
        "strike": row[2],
        "expiry": row[3],
        "spot": spot,
        "atm": atm,
        "type": opt_type
    }


if __name__ == "__main__":

    nifty_spot = 23643

    ce = find_option("NIFTY", nifty_spot, "CE")
    pe = find_option("NIFTY", nifty_spot, "PE")

    print("\n🔥 ATM CE")
    print(ce)

    print("\n🔥 ATM PE")
    print(pe)

from data_stream.data_manager import get_data_manager
def get_option_ltp(token):
    try:
        import requests

        r = requests.get(
            "http://127.0.0.1:5002/api/ws/status",
            timeout=3
        ).json()

        ltp = r.get("ltp", {}).get(str(token), 0)

        return float(ltp or 0)

    except Exception as e:
        print("LTP ERROR:", e)
        return 0

        return float(ltp)

    except Exception as e:
        print("LTP ERROR:", e)
        return 0


if __name__ == "__main__":

    nifty_spot = 23643

    ce = find_option("NIFTY", nifty_spot, "CE")
    pe = find_option("NIFTY", nifty_spot, "PE")

    print("\n🔥 ATM CE")
    print(ce)

    print("\n🔥 ATM PE")
    print(pe)

    if ce:
        ce_ltp = get_option_ltp(ce["token"])
        print("\n💰 CE LTP =", ce_ltp)

    if pe:
        pe_ltp = get_option_ltp(pe["token"])
        print("💰 PE LTP =", pe_ltp)

