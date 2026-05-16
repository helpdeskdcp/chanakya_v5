import statistics

def detect(
    candles,
    spread=0,
    tick_gap=0,
    ws_health="GOOD"
):

    try:

        if not candles or len(candles) < 20:

            return {
                "anomaly": False,
                "severity": 0,
                "type": "NONE"
            }

        closes = [
            float(c["close"])
            for c in candles[-20:]
        ]

        highs = [
            float(c["high"])
            for c in candles[-20:]
        ]

        lows = [
            float(c["low"])
            for c in candles[-20:]
        ]

        ranges = [
            h - l
            for h, l in zip(highs, lows)
        ]

        avg_range = statistics.mean(ranges[:-1])

        latest_range = ranges[-1]

        severity = 0
        anomaly_type = "NONE"

        # ── Volatility explosion ──
        if latest_range > avg_range * 3:

            severity += 40
            anomaly_type = "VOLatility_SHOCK"

        # ── Spread anomaly ──
        if spread > avg_range * 0.5:

            severity += 25

            if anomaly_type == "NONE":
                anomaly_type = "SPREAD_DISTORTION"

        # ── Tick starvation ──
        if tick_gap > 10:

            severity += 30

            if anomaly_type == "NONE":
                anomaly_type = "TICK_STARVATION"

        # ── Infra degradation ──
        if ws_health != "GOOD":

            severity += 35

            if anomaly_type == "NONE":
                anomaly_type = "INFRA_DEGRADATION"

        anomaly = severity >= 40

        severity = max(
            0,
            min(100, severity)
        )

        return {
            "anomaly": anomaly,
            "severity": severity,
            "type": anomaly_type
        }

    except Exception as e:

        return {
            "anomaly": True,
            "severity": 100,
            "type": f"ERROR:{e}"
        }
