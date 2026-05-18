import statistics

REALITIES = []

def simulate(
    direction,
    entry,
    candles,
    sl,
    target
):
    """
    Parallel outcome simulator
    """

    try:

        if not candles:
            return {}

        closes = [float(c["close"]) for c in candles[-20:]]

        avg_move = statistics.mean([
            abs(closes[i] - closes[i-1])
            for i in range(1, len(closes))
        ])

        realities = []

        # ── Reality 1: tighter SL ──
        realities.append({
            "name": "tight_sl",
            "sl": sl * 0.8,
            "target": target,
        })

        # ── Reality 2: wider SL ──
        realities.append({
            "name": "wide_sl",
            "sl": sl * 1.2,
            "target": target,
        })

        # ── Reality 3: extended target ──
        realities.append({
            "name": "extended_target",
            "sl": sl,
            "target": target * 1.5,
        })

        # ── Reality 4: conservative target ──
        realities.append({
            "name": "safe_target",
            "sl": sl,
            "target": target * 0.7,
        })

        results = []

        for r in realities:

            expectancy = 0

            if direction == "BUY":

                expectancy = (
                    (r["target"] - entry)
                    /
                    max(1, abs(entry - r["sl"]))
                )

            else:

                expectancy = (
                    (entry - r["target"])
                    /
                    max(1, abs(r["sl"] - entry))
                )

            results.append({
                "reality": r["name"],
                "expectancy": round(expectancy, 2)
            })

        best = max(
            results,
            key=lambda x: x["expectancy"]
        )

        REALITIES.append(best)

        return {
            "best": best,
            "all": results,
            "volatility": round(avg_move, 2)
        }

    except Exception as e:

        return {
            "error": str(e)
        }

def stats():

    return {
        "runs": len(REALITIES),
        "recent": REALITIES[-10:]
    }
