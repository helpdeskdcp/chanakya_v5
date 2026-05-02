import os, requests, logging
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

def send(msg: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
        return r.json().get("ok", False)
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def alert_trade_open(username, symbol, direction, entry, sl, target, qty, mode="PAPER"):
    emoji = "📈" if direction == "BUY" else "📉"
    msg = (
        f"{emoji} <b>TRADE OPEN [{mode}]</b>\n"
        f"👤 {username}\n"
        f"📌 {symbol} — <b>{direction}</b>\n"
        f"💰 Entry: ₹{entry}\n"
        f"🛡 SL: ₹{sl}\n"
        f"🎯 Target: ₹{target}\n"
        f"📦 Qty: {qty}\n"
        f"🕐 {datetime.now().strftime('%d-%b %H:%M:%S')}"
    )
    return send(msg)

def alert_trade_close(username, symbol, direction, entry, exit_price, pnl, mode="PAPER"):
    emoji = "✅" if pnl >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CLOSED [{mode}]</b>\n"
        f"👤 {username}\n"
        f"📌 {symbol} — {direction}\n"
        f"💰 Entry: ₹{entry} → Exit: ₹{exit_price}\n"
        f"{'🟢' if pnl>=0 else '🔴'} P&L: ₹{pnl:+.0f}\n"
        f"🕐 {datetime.now().strftime('%d-%b %H:%M:%S')}"
    )
    return send(msg)

def alert_signal(symbol, direction, entry, sl, target, score):
    emoji = "📈" if direction == "BUY" else "📉"
    msg = (
        f"⚡ <b>SIGNAL ALERT</b>\n"
        f"{emoji} {symbol} — <b>{direction}</b>\n"
        f"💰 Entry: ₹{entry}\n"
        f"🛡 SL: ₹{sl} | 🎯 Target: ₹{target}\n"
        f"🏆 Score: {score}%\n"
        f"🕐 {datetime.now().strftime('%d-%b %H:%M:%S')}"
    )
    return send(msg)
