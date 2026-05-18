import os, logging
logger = logging.getLogger(__name__)

def place_live_order(username, symbol, exchange, token, direction, qty, order_type="MIS"):
    try:
        from broker.global_broker import get_broker
        from trading.paper_engine import place_trade
        broker = get_broker()
        if not broker or not broker.is_connected():
            logger.error("Broker not connected")
            return None
        params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": str(token),
            "transactiontype": direction,
            "exchange": exchange,
            "ordertype": "MARKET",
            "producttype": order_type,
            "duration": "DAY",
            "quantity": str(qty),
        }
        r = broker.api.placeOrder(params)
        if r and r.get("status"):
            order_id = r.get("data",{}).get("orderid","")
            trade_id = place_trade(username, symbol, exchange, direction,
                                   0, 0, 0, qty=qty, token=str(token),
                                   strategy="LIVE", mode="LIVE")
            logger.info(f"Live order placed: {order_id} trade#{trade_id}")
            return order_id
        logger.error(f"Order failed: {r}")
        return None
    except Exception as e:
        logger.error(f"place_live_order: {e}")
        return None

def place_intraday(username, symbol, exchange, token, direction, qty):
    return place_live_order(username, symbol, exchange, token, direction, qty, "MIS")

def place_carryforward(username, symbol, exchange, token, direction, qty):
    return place_live_order(username, symbol, exchange, token, direction, qty, "CNC")

def place_fno(username, symbol, exchange, token, direction, qty):
    return place_live_order(username, symbol, exchange, token, direction, qty, "NRML")

def cancel_order(order_id):
    try:
        from broker.global_broker import get_broker
        broker = get_broker()
        if not broker: return False
        r = broker.api.cancelOrder(order_id, "NORMAL")
        return bool(r and r.get("status"))
    except Exception as e:
        logger.error(f"cancel_order: {e}"); return False

def get_live_positions():
    try:
        from broker.global_broker import get_broker
        broker = get_broker()
        if not broker: return []
        r = broker.api.position()
        if r and r.get("data"):
            return r["data"]
    except Exception as e:
        logger.error(f"live_positions: {e}")
    return []
