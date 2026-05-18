"""Compatibility shim: re-exports telegram alert helpers from alerts.telegram_bot.
Some legacy modules import from `notifications.telegram` — keep them working."""
from alerts.telegram_bot import (
    send,
    send_admin,
    alert_signal,
    alert_trade_open,
    alert_sl_hit,
    alert_target_hit,
    alert_daily_pnl,
    alert_system,
    alert_new_user,
    alert_payment,
)

# Aliases expected by legacy code
send_message = send
_send = send


def alert_trade_close(chat_id, trade):
    """Generic trade-close alert (legacy). Falls back to SL/Target/system based on payload."""
    try:
        reason = (trade.get("exit_reason") or trade.get("reason") or "").upper()
        if "SL" in reason:
            return alert_sl_hit(chat_id, trade)
        if "TARGET" in reason or "TGT" in reason:
            return alert_target_hit(chat_id, trade)
        sym = trade.get("symbol", "")
        pnl = trade.get("pnl", 0)
        return send(chat_id, f"<b>Trade Closed</b>\n{sym}\nPnL: {pnl}\nReason: {reason or 'manual'}")
    except Exception:
        return False
