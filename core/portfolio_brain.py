from collections import defaultdict

INDEX_GROUPS = {
    "BANKNIFTY": "BANKS",
    "FINNIFTY": "BANKS",
    "NIFTY": "INDEX",
    "MIDCPNIFTY": "MIDCAP",

    "CRUDEOIL": "COMMODITY",
    "NATURALGAS": "COMMODITY",
    "GOLD": "METAL",
    "SILVER": "METAL",
}

def symbol_group(symbol):

    for key, grp in INDEX_GROUPS.items():

        if key in symbol.upper():
            return grp

    return "OTHER"

def analyze(open_trades, new_symbol):

    exposure = defaultdict(int)

    for t in open_trades:

        grp = symbol_group(
            t.get("symbol", "")
        )

        exposure[grp] += 1

    new_group = symbol_group(new_symbol)

    same_group = exposure.get(new_group, 0)

    total_open = sum(exposure.values())

    heat = total_open * 10 + same_group * 20

    decision = "ALLOW"

    if same_group >= 3:
        decision = "BLOCK"

    elif heat >= 70:
        decision = "REDUCE"

    return {
        "group": new_group,
        "same_group": same_group,
        "heat": heat,
        "decision": decision,
        "exposure": dict(exposure)
    }
