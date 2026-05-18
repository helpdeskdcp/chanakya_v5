"""
Chanakya AI Mythos — Telegram Alert Bot
Auto alerts for signals, trades, PnL + user commands
"""
import os, requests, logging, threading, time
from datetime import datetime
import pytz

logger = logging.getLogger("telegram")
IST = pytz.timezone("Asia/Kolkata")

BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN","")
ADMIN_CHAT = os.getenv("TELEGRAM_ADMIN_CHAT","")

# ── Core send ────────────────────────────────────────────────────
def send(chat_id, text, parse_mode="HTML"):
    if not BOT_TOKEN or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id":str(chat_id),"text":text,"parse_mode":parse_mode},
            timeout=5
        )
        return r.status_code == 200
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return False

def send_admin(text):
    if ADMIN_CHAT:
        return send(ADMIN_CHAT, text)
    return False

def now_ist():
    return datetime.now(IST).strftime("%H:%M:%S IST")

# ── Alert Templates ──────────────────────────────────────────────
def alert_signal(chat_id, sig):
    sym   = sig.get("symbol","")
    stype = sig.get("signal","")
    score = sig.get("score",0)
    osym  = sig.get("opt_symbol","")
    entry = sig.get("opt_entry") or sig.get("opt_ltp") or 0
    sl    = sig.get("opt_sl",0)
    tgt   = sig.get("opt_target",0)
    risk  = sig.get("risk","MEDIUM")
    emoji = "BUY CE" if "CE" in stype else "BUY PE"
    color = "green" if "CE" in stype else "red"
    send(chat_id,
        f"SIGNAL: {sym} {emoji}\n"
        f"Score: {score}% | Risk: {risk}\n"
        f"Option: {osym}\n"
        f"Entry: Rs{entry} | SL: Rs{sl} | Target: Rs{tgt}\n"
        f"Time: {now_ist()}"
    )

def alert_trade_open(chat_id, trade):
    mode = "PAPER" if trade.get("paper") else "LIVE"
    send(chat_id,
        f"{mode} TRADE OPENED\n"
        f"{trade.get('symbol','')} {trade.get('direction','')}\n"
        f"Entry: Rs{trade.get('entry',0)}\n"
        f"SL: Rs{trade.get('sl',0)} | Target: Rs{trade.get('target',0)}\n"
        f"ID: {trade.get('id','')} | {now_ist()}"
    )

def alert_sl_hit(chat_id, trade):
    pnl = abs(trade.get("pnl",0))
    send(chat_id,
        f"SL HIT - TRADE CLOSED\n"
        f"{trade.get('symbol','')} {trade.get('direction','')}\n"
        f"Loss: Rs{pnl:.0f}\n"
        f"Entry Rs{trade.get('entry',0)} to Exit Rs{trade.get('ltp',0)}\n"
        f"{now_ist()}"
    )

def alert_target_hit(chat_id, trade):
    pnl = trade.get("pnl",0)
    send(chat_id,
        f"TARGET HIT - PROFIT BOOKED\n"
        f"{trade.get('symbol','')} {trade.get('direction','')}\n"
        f"Profit: Rs+{pnl:.0f}\n"
        f"Entry Rs{trade.get('entry',0)} to Exit Rs{trade.get('ltp',0)}\n"
        f"{now_ist()}"
    )

def alert_daily_pnl(chat_id, stats):
    pnl = stats.get("total_pnl",0)
    sign = "+" if pnl >= 0 else ""
    send(chat_id,
        f"DAILY PnL SUMMARY\n"
        f"PnL: Rs{sign}{pnl:.0f}\n"
        f"Trades: {stats.get('total_trades',0)}\n"
        f"Wins: {stats.get('wins',0)} | Loss: {stats.get('losses',0)}\n"
        f"Win Rate: {stats.get('win_rate',0):.0f}%\n"
        f"{datetime.now(IST).strftime('%d %b %Y')}"
    )

def alert_system(text):
    send_admin(f"SYSTEM: {text}")

def alert_new_user(username, email, plan):
    send_admin(f"NEW USER: {username} | {email} | Plan: {plan}")

def alert_payment(username, plan, amount):
    send_admin(f"PAYMENT: {username} | {plan} | Rs{amount}")

# ── Command Handler ──────────────────────────────────────────────
def handle_command(chat_id, text):
    cmd = text.strip().lower().split()[0] if text else ""
    if cmd == "/start" or cmd == "/help":
        send(chat_id,
            "Chanakya AI Mythos\n"
            "Commands:\n"
            "/signal - Latest signal\n"
            "/pnl - Today PnL\n"
            "/status - System status\n"
            "/help - This menu"
        )
    else:
        send(chat_id, "Use /help to see available commands")

# ── Polling ──────────────────────────────────────────────────────
def _poll():
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set")
        return
    offset = 0
    logger.info("Telegram polling started")
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15
            )
            if r.status_code == 200:
                for u in r.json().get("result",[]):
                    offset = u["update_id"] + 1
                    msg = u.get("message",{})
                    txt = msg.get("text","")
                    if txt.startswith("/"):
                        handle_command(msg["chat"]["id"], txt)
        except Exception as e:
            logger.debug("Poll error: %s", e)
        time.sleep(1)

def start():
    t = threading.Thread(target=_poll, daemon=True, name="tg-bot")
    t.start()
    logger.info("Telegram bot started")
