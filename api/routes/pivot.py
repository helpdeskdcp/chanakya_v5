"""
api/routes/pivot.py  —  Chanakya v5
Daily Pivot Lines API — uses existing broker.global_broker session
"""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)
pivot_bp = Blueprint("pivot", __name__)

INDEX_CONFIG = {
    "NIFTY":      {"exchange": "NSE", "token": "99926000"},
    "BANKNIFTY":  {"exchange": "NSE", "token": "99926009"},
    "FINNIFTY":   {"exchange": "NSE", "token": "99926037"},
    "MIDCPNIFTY": {"exchange": "NSE", "token": "99926074"},
}
MCX_SYMBOLS = {"NATURALGAS", "CRUDEOIL", "CRUDEOILM", "GOLD", "SILVER"}
MARKET_START, MARKET_END = "09:15", "15:30"
MCX_START,    MCX_END    = "09:00", "23:30"


def _get_broker():
    try:
        from broker.global_broker import get_broker
        return get_broker()
    except Exception as e:
        logger.error(f"Broker session error: {e}")
        return None


def _resolve_token(symbol):
    if symbol in INDEX_CONFIG:
        c = INDEX_CONFIG[symbol]
        return c["exchange"], c["token"]
    if symbol in MCX_SYMBOLS:
        try:
            import json, os
            path = "/root/chanakya_v5/data/scrip_master.json"
            with open(path) as f:
                data = json.load(f)
            today = datetime.now().date()
            # FUTCOM active expiry चा token घे
            candidates = [
                r for r in data
                if r.get("name","").upper() == symbol.upper()
                and r.get("instrumenttype") == "FUTCOM"
                and r.get("exch_seg") == "MCX"
                and r.get("expiry","")
            ]
            if candidates:
                def _exp(r):
                    try: return datetime.strptime(r["expiry"],"%d%b%Y").date()
                    except: return datetime.max.date()
                candidates.sort(key=_exp)
                active = next((c for c in candidates if _exp(c) >= today), candidates[0])
                logger.info(f"MCX token: {symbol} → {active['symbol']} {active['token']}")
                return "MCX", str(active["token"])
        except Exception as e:
            logger.warning(f"MCX token resolve failed: {e}")
    return "MCX", None


def _fetch_candles(broker, token, exchange, interval, target_date=None, days=3):
    """
    Fetch via broker.get_candles() and optionally filter by target_date.
    target_date: datetime.date object — filter rows to that date only
    """
    import time
    time.sleep(0.3)  # rate limiter साठी थोडा delay
    raw = broker.get_candles(token, exchange, interval, days=days)
    if not raw:
        return []
    result = []
    for row in raw:
        try:
            ts    = str(row[0])[:16]          # "2026-05-09 09:15"
            date_ = ts[:10]                   # "2026-05-09"
            if target_date and date_ != str(target_date):
                continue
            result.append({
                "time":   ts[11:],
                "open":   round(float(row[1]), 2),
                "high":   round(float(row[2]), 2),
                "low":    round(float(row[3]), 2),
                "close":  round(float(row[4]), 2),
                "volume": int(row[5]) if len(row) > 5 else 0,
                "price":  round(float(row[4]), 2),
            })
        except Exception as e:
            logger.debug(f"Candle parse skip: {e}")
    return result


def _prev_trading_day(ref):
    d = ref - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _make_pivots(H, L, C):
    pp = (H + L + C) / 3
    return {
        "pp": round(pp, 2),
        "r1": round(2*pp - L, 2),
        "r2": round(pp + H - L, 2),
        "r3": round(H + 2*(pp - L), 2),
        "s1": round(2*pp - H, 2),
        "s2": round(pp - H + L, 2),
        "s3": round(L - 2*(H - pp), 2),
    }


@pivot_bp.route("/ohlc", methods=["GET"])
def prev_day_ohlc():
    symbol   = request.args.get("symbol", "NIFTY").upper()
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    try:
        chart_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Use YYYY-MM-DD"}), 400

    prev_day = _prev_trading_day(chart_date)
    broker = _get_broker()
    if not broker:
        return jsonify({"error": "Broker session unavailable"}), 503

    exchange, token = _resolve_token(symbol)
    if not token:
        return jsonify({"error": f"Token not found for {symbol}"}), 404

    candles = _fetch_candles(broker, token, exchange, "ONE_DAY", target_date=prev_day, days=5)
    if not candles:
        return jsonify({"error": f"No OHLC for {symbol} on {prev_day}"}), 404

    c = candles[0]
    H, L, C = c["high"], c["low"], c["close"]
    return jsonify({
        "symbol": symbol, "prev_date": str(prev_day),
        "ohlc":   {"open": c["open"], "high": H, "low": L, "close": C},
        "pivots": _make_pivots(H, L, C),
    })


@pivot_bp.route("/candles", methods=["GET"])
def intraday_candles():
    symbol   = request.args.get("symbol",   "NIFTY").upper()
    date_str = request.args.get("date",     datetime.now().strftime("%Y-%m-%d"))
    interval = request.args.get("interval", "FIVE_MINUTE").upper()

    VALID = {"ONE_MINUTE","THREE_MINUTE","FIVE_MINUTE","TEN_MINUTE",
             "FIFTEEN_MINUTE","THIRTY_MINUTE","ONE_HOUR","ONE_DAY"}
    if interval not in VALID:
        return jsonify({"error": f"Invalid interval"}), 400

    try:
        chart_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Use YYYY-MM-DD"}), 400

    broker = _get_broker()
    if not broker:
        return jsonify({"error": "Broker session unavailable"}), 503

    exchange, token = _resolve_token(symbol)
    if not token:
        return jsonify({"error": f"Token not found for {symbol}"}), 404

    days_back = 1 if chart_date == datetime.now().date() else (datetime.now().date() - chart_date).days + 2
    candles = _fetch_candles(broker, token, exchange, interval, target_date=chart_date, days=max(days_back, 2))
    if not candles:
        return jsonify({"error": f"No candle data for {symbol} on {chart_date}"}), 404

    return jsonify({
        "symbol": symbol, "date": str(chart_date),
        "exchange": exchange, "interval": interval,
        "ltp": candles[-1]["close"],
        "candles": candles,
    })


@pivot_bp.route("/live-ltp", methods=["GET"])
def live_ltp():
    symbol = request.args.get("symbol", "NIFTY").upper()
    broker = _get_broker()
    if not broker:
        return jsonify({"error": "Broker session unavailable"}), 503

    exchange, token = _resolve_token(symbol)
    if not token:
        return jsonify({"error": f"Token not found for {symbol}"}), 404

    ltp = broker.get_ltp(exchange, symbol, token)
    if ltp:
        return jsonify({
            "symbol": symbol, "ltp": ltp,
            "timestamp": datetime.now().isoformat(),
        })
    return jsonify({"error": "LTP fetch failed"}), 502


# ─── Signal Detection ────────────────────────────────────────────────────────

def _detect_signals(candles, pivots, threshold=0.0010, symbol='NIFTY'):
    """
    Mathematical signal detection at pivot levels.
    threshold: % proximity to consider a pivot touch (0.10%)
    """
    signals = []
    levels = {
        's3': (pivots['s3'], 'SUPPORT', 3),
        's2': (pivots['s2'], 'SUPPORT', 2),
        's1': (pivots['s1'], 'SUPPORT', 1),
        'pp': (pivots['pp'], 'PIVOT',   2),
        'r1': (pivots['r1'], 'RESIST',  1),
        'r2': (pivots['r2'], 'RESIST',  2),
        'r3': (pivots['r3'], 'RESIST',  3),
    }
    for i in range(1, len(candles)):
        c    = candles[i]
        prev = candles[i - 1]
        bull = c['close'] > c['open']
        bear = c['close'] < c['open']

        for lname, (lval, ltype, strength) in levels.items():
            near = abs(lval - 0) > 0  # safety

            if ltype == 'SUPPORT':
                # Bounce: low touches support, prev candle bearish, current bullish
                touched = c['low'] <= lval * (1 + threshold) and c['low'] >= lval * (1 - threshold)
                prev_bear = prev['close'] < prev['open']
                if touched and bull and prev_bear:
                    signals.append({
                        'time': c['time'], 'type': 'BUY',
                        'price': c['close'], 'level': lname.upper(),
                        'level_val': lval, 'strength': strength,
                        'reason': f'{lname.upper()} Bounce → {lval}',
                        'sl': round(lval * (1 - threshold * 2), 2),
                        'target': round(pivots.get('pp' if lname != 'pp' else 'r1', lval * 1.005), 2),
                    })

            elif ltype == 'RESIST':
                # Rejection: high touches resistance, prev bullish, current bearish
                touched = c['high'] >= lval * (1 - threshold) and c['high'] <= lval * (1 + threshold)
                prev_bull = prev['close'] > prev['open']
                if touched and bear and prev_bull:
                    signals.append({
                        'time': c['time'], 'type': 'SELL',
                        'price': c['close'], 'level': lname.upper(),
                        'level_val': lval, 'strength': strength,
                        'reason': f'{lname.upper()} Rejection → {lval}',
                        'sl': round(lval * (1 + threshold * 2), 2),
                        'target': round(pivots.get('pp' if lname != 'pp' else 's1', lval * 0.995), 2),
                    })

            elif ltype == 'PIVOT':
                # PP crossover
                if prev['close'] < lval <= c['close'] and bull:
                    signals.append({
                        'time': c['time'], 'type': 'BUY',
                        'price': c['close'], 'level': 'PP',
                        'level_val': lval, 'strength': 2,
                        'reason': f'PP Breakout ↑ {lval}',
                        'sl': round(lval * 0.998, 2),
                        'target': round(pivots['r1'], 2),
                    })
                elif prev['close'] > lval >= c['close'] and bear:
                    signals.append({
                        'time': c['time'], 'type': 'SELL',
                        'price': c['close'], 'level': 'PP',
                        'level_val': lval, 'strength': 2,
                        'reason': f'PP Breakdown ↓ {lval}',
                        'sl': round(lval * 1.002, 2),
                        'target': round(pivots['s1'], 2),
                    })

    # Dedup — cooldown 8 candles per level, max 2 signals per level
    from collections import defaultdict
    last_fired = {}   # level → candle index
    level_count = defaultdict(int)
    filtered = []
    for i, s in enumerate(signals):
        lkey = s['level'] + s['type']
        last = last_fired.get(lkey, -99)
        # Find candle index by time
        cidx = next((j for j,c in enumerate(candles) if c['time'] == s['time']), i)
        if (cidx - last) >= 8 and level_count[lkey] < 2:
            filtered.append(s)
            last_fired[lkey] = cidx
            level_count[lkey] += 1
    return filtered


def _atr_prediction(broker, token, exchange, today_close, today_pivots):
    """ATR-based next day range prediction."""
    import time as _time
    _time.sleep(0.3)
    raw = broker.get_candles(token, exchange, 'ONE_DAY', days=20)
    if not raw or len(raw) < 5:
        return None
    ranges = []
    for row in raw:
        try:
            h, l = float(row[2]), float(row[3])
            ranges.append(h - l)
        except: pass
    if not ranges:
        return None
    atr     = round(sum(ranges[-14:]) / len(ranges[-14:]), 2)
    is_bull = today_close >= today_pivots['pp']
    if is_bull:
        pred_low  = round(today_close - atr * 0.35, 2)
        pred_high = round(today_close + atr * 1.10, 2)
        t1, t2    = today_pivots['r1'], today_pivots['r2']
    else:
        pred_low  = round(today_close - atr * 1.10, 2)
        pred_high = round(today_close + atr * 0.35, 2)
        t1, t2    = today_pivots['s1'], today_pivots['s2']
    conf = min(75, 50 + len(ranges) * 1.2)
    return {
        'method': 'ATR', 'atr': atr,
        'direction': 'BULLISH' if is_bull else 'BEARISH',
        'pred_low': pred_low, 'pred_high': pred_high,
        'target1': round(t1, 2), 'target2': round(t2, 2),
        'confidence': round(conf),
    }


def _ml_prediction(symbol, today_close, today_pivots, candles_today):
    """Chanakya ML model prediction."""
    try:
        import pickle, os, numpy as np
        model_path = '/root/chanakya_v5/data/ml_model.pkl'
        if not os.path.exists(model_path):
            raise FileNotFoundError("ml_model.pkl not found")
        with open(model_path, 'rb') as f:
            model = pickle.load(f)

        if not candles_today or len(candles_today) < 10:
            raise ValueError("Not enough candles for ML")

        closes  = [c['close'] for c in candles_today]
        highs   = [c['high']  for c in candles_today]
        lows    = [c['low']   for c in candles_today]

        # Basic features
        ema9  = sum(closes[-9:])  / 9
        ema21 = sum(closes[-21:]) / 21 if len(closes) >= 21 else sum(closes) / len(closes)
        day_range = max(highs) - min(lows)
        pp_dist   = (today_close - today_pivots['pp']) / today_pivots['pp']
        r1_dist   = (today_pivots['r1'] - today_close) / today_close
        s1_dist   = (today_close - today_pivots['s1']) / today_close

        features = np.array([[
            today_close, ema9, ema21,
            day_range, pp_dist, r1_dist, s1_dist,
            today_close / today_pivots['pp'],
        ]])

        pred = model.predict(features)[0]
        prob = model.predict_proba(features)[0] if hasattr(model, 'predict_proba') else [0.5, 0.5]
        is_bull    = int(pred) == 1
        confidence = round(max(prob) * 100)

        if is_bull:
            pred_low  = round(today_close * 0.997, 2)
            pred_high = round(today_close + (today_pivots['r1'] - today_close) * 0.8, 2)
            t1, t2    = today_pivots['r1'], today_pivots['r2']
        else:
            pred_low  = round(today_close - (today_close - today_pivots['s1']) * 0.8, 2)
            pred_high = round(today_close * 1.003, 2)
            t1, t2    = today_pivots['s1'], today_pivots['s2']

        return {
            'method': 'ML', 'model': 'chanakya_xgb',
            'direction': 'BULLISH' if is_bull else 'BEARISH',
            'pred_low': pred_low, 'pred_high': pred_high,
            'target1': round(t1, 2), 'target2': round(t2, 2),
            'confidence': confidence,
        }
    except Exception as e:
        logger.warning(f"ML prediction failed: {e}")
        return {'method': 'ML', 'error': str(e)}


# ─── Signal Route ─────────────────────────────────────────────────────────────

@pivot_bp.route("/signals", methods=["GET"])
def get_signals():
    """
    GET /api/pivot/signals?symbol=NIFTY&date=2026-05-08
    Returns buy/sell signals detected at pivot levels.
    """
    symbol   = request.args.get("symbol", "NIFTY").upper()
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    try:
        chart_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Use YYYY-MM-DD"}), 400

    broker = _get_broker()
    if not broker:
        return jsonify({"error": "Broker unavailable"}), 503

    exchange, token = _resolve_token(symbol)
    if not token:
        return jsonify({"error": f"Token not found for {symbol}"}), 404

    # Get pivots for this date (prev day OHLC)
    prev_day = _prev_trading_day(chart_date)
    is_mcx   = exchange == "MCX"
    day_start = datetime.combine(prev_day, datetime.strptime(MCX_START if is_mcx else MARKET_START, "%H:%M").time())
    day_end   = datetime.combine(prev_day, datetime.strptime(MCX_END   if is_mcx else MARKET_END,   "%H:%M").time())
    prev_candles = _fetch_candles(broker, token, exchange, "ONE_DAY", target_date=prev_day, days=5)

    if not prev_candles:
        return jsonify({"error": f"No OHLC for {symbol} on {prev_day}"}), 404

    c = prev_candles[0]
    pivots = _make_pivots(c["high"], c["low"], c["close"])

    # Get intraday candles
    import time as _t; _t.sleep(0.5)  # rate limiter gap
    days_back = max(4, (datetime.now().date() - chart_date).days + 3)
    candles = _fetch_candles(broker, token, exchange, "FIVE_MINUTE", target_date=chart_date, days=days_back)
    if not candles:
        return jsonify({"error": f"No candle data for {symbol} on {chart_date}"}), 404

    signals = _detect_signals(candles, pivots, symbol=symbol)
    # Ensure confidence key exists
    _conf_map = {
        'NIFTY':     {'R1_SELL':60,'R2_SELL':50,'PP_SELL':55,'PP_BUY':55,'S1_BUY':20,'S2_BUY':25},
        'BANKNIFTY': {'R2_SELL':66,'R1_SELL':28,'PP_SELL':18,'PP_BUY':18,'S1_BUY':28},
        'DEFAULT':   {'R1_SELL':50,'R2_SELL':50,'PP_SELL':45,'PP_BUY':45,'S1_BUY':35},
    }
    _sym_cfg = _conf_map.get(symbol, _conf_map['DEFAULT'])
    for s in signals:
        if 'confidence' not in s:
            s['confidence'] = _sym_cfg.get(f"{s.get('level','PP')}_{s.get('type','BUY')}", 40)
    buy_count  = sum(1 for s in signals if s['type'] == 'BUY')
    sell_count = sum(1 for s in signals if s['type'] == 'SELL')

    return jsonify({
        "symbol": symbol, "date": str(chart_date),
        "pivots": pivots,
        "signals": signals,
        "summary": {"buy": buy_count, "sell": sell_count, "total": len(signals)},
    })


# ─── Predict Route ────────────────────────────────────────────────────────────

@pivot_bp.route("/predict", methods=["GET"])
def predict_next_day():
    """
    GET /api/pivot/predict?symbol=NIFTY&date=2026-05-08
    Returns next day prediction using ATR math + ML model.
    """
    symbol   = request.args.get("symbol", "NIFTY").upper()
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    try:
        chart_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Use YYYY-MM-DD"}), 400

    broker = _get_broker()
    if not broker:
        return jsonify({"error": "Broker unavailable"}), 503

    exchange, token = _resolve_token(symbol)
    if not token:
        return jsonify({"error": f"Token not found for {symbol}"}), 404

    # Today's pivots
    prev_day = _prev_trading_day(chart_date)
    prev_candles = _fetch_candles(broker, token, exchange, "ONE_DAY", target_date=prev_day, days=5)
    if not prev_candles:
        return jsonify({"error": "No OHLC data"}), 404
    c = prev_candles[0]
    pivots = _make_pivots(c["high"], c["low"], c["close"])

    # Today's close
    days_back = max(2, (datetime.now().date() - chart_date).days + 2)
    candles = _fetch_candles(broker, token, exchange, "FIVE_MINUTE", target_date=chart_date, days=days_back)
    today_close = candles[-1]["close"] if candles else c["close"]

    # Next day pivots (based on today's projected OHLC)
    next_day_pivots = _make_pivots(
        max(c["high"], today_close),
        min(c["low"],  today_close),
        today_close,
    )

    # ATR prediction
    atr_pred = _atr_prediction(broker, token, exchange, today_close, next_day_pivots)

    # ML prediction
    ml_pred  = _ml_prediction(symbol, today_close, next_day_pivots, candles)

    # Consensus
    consensus = "NEUTRAL"
    if atr_pred and ml_pred and 'direction' in ml_pred:
        if atr_pred['direction'] == ml_pred['direction']:
            consensus = atr_pred['direction'] + " (Both Agree ✅)"
        else:
            consensus = f"CONFLICT — ATR:{atr_pred['direction']} vs ML:{ml_pred['direction']}"

    return jsonify({
        "symbol": symbol, "base_date": str(chart_date),
        "today_close": today_close,
        "next_day_pivots": next_day_pivots,
        "atr_prediction": atr_pred,
        "ml_prediction":  ml_pred,
        "consensus": consensus,
    })
