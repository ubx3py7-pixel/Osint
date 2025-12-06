#!/usr/bin/env python3
# yu.py — PART 1/2 (complete bot, part 1)
"""
FIRE DROP OSINT Bot — full fixed version (split into 2 parts).
Paste Part 1 then Part 2. Run with: python3 yu.py
"""

import asyncio
import aiohttp
import sqlite3
import time
import random
import string
import json
from typing import Optional

# ---------------- CONFIG ----------------
BOT_TOKEN = "8365786304:AAGzmEgcLTmS2vzJMJOM-YrEtgtw8T3I-4Q"
OWNER_ID = 6940098775

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
OSINT_API_TEMPLATE = "https://dark-trace-networks.vercel.app/api?key=DarkTrace_Network&type=mobile&term={term}"

DB_PATH = "firedrop_min.db"
DEFAULT_CREDITS = 5
POLL_TIMEOUT = 30
# ----------------------------------------

# ---------------- TEMPLATES ----------------
TEMPLATE_FOUND = """════════════════════
║  📱 PHONE INFO 📱  ║
════════════════════
📞 Number: {number}

👤 Name: {name}  
👨 Father: {father}

📧 Email: {email}
📱 Alt Number: {alt_number}

🌐 Circle: {circle}
🆔 ID: {id_field}
🏠 Address: {address}

━━━━━━━━━━━━━━━━━━━━
💎 Credits Left: {credits_left}
Zoro found it! 💨
"""

TEMPLATE_NOT_FOUND = """Zoro lost the battle 😔.
No data found

Remaining credits: {credits_left}
"""

# ---------------- DB HELPERS ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            username TEXT,
            credits INTEGER DEFAULT {DEFAULT_CREDITS},
            cmd_count INTEGER DEFAULT 0,
            slowed_until INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            credits INTEGER NOT NULL,
            remaining_uses INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def ensure_user(tg_id: int, username: Optional[str]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (tg_id, username, credits) VALUES (?, ?, ?)",
                (tg_id, username or "", DEFAULT_CREDITS))
    cur.execute("UPDATE users SET username=? WHERE tg_id=?", (username or "", tg_id))
    conn.commit()
    conn.close()

def get_user(tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT tg_id, username, credits, cmd_count, slowed_until FROM users WHERE tg_id=?", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return row

def change_credits(tg_id: int, delta: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET credits = credits + ? WHERE tg_id=?", (delta, tg_id))
    conn.commit()
    cur.execute("SELECT credits FROM users WHERE tg_id=?", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def inc_cmd_count(tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET cmd_count = cmd_count + 1 WHERE tg_id=?", (tg_id,))
    conn.commit()
    cur.execute("SELECT cmd_count FROM users WHERE tg_id=?", (tg_id,))
    val = cur.fetchone()[0]
    conn.close()
    return val

def set_cmd_count(tg_id: int, value: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET cmd_count=? WHERE tg_id=?", (value, tg_id))
    conn.commit()
    conn.close()

def set_slowed_until(tg_id: int, timestamp: int):
    # kept for compatibility (no slow-mode active) — useful for /rem owner command
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET slowed_until=? WHERE tg_id=?", (timestamp, tg_id))
    conn.commit()
    conn.close()

def create_redeem_code(credits: int, uses: int):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO redeem_codes (code, credits, remaining_uses) VALUES (?, ?, ?)",
                (code, credits, uses))
    conn.commit()
    conn.close()
    return code

def redeem_code_db(code: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT credits, remaining_uses FROM redeem_codes WHERE code=?", (code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    credits, uses = row
    if uses <= 0:
        conn.close()
        return None
    cur.execute("UPDATE redeem_codes SET remaining_uses = remaining_uses - 1 WHERE code=?", (code,))
    conn.commit()
    conn.close()
    return credits

def get_user_count():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    c = cur.fetchone()[0]
    conn.close()
    return c

# ---------------- HTTP / TELEGRAM HELPERS ----------------
async def api_request(session, method, payload=None):
    url = f"{API_BASE}/{method}"
    try:
        async with session.post(url, json=payload or {}, timeout=60) as resp:
            return await resp.json()
    except Exception as e:
        # return minimal error for callers
        return {"ok": False, "error": str(e)}

async def send_message(session, chat_id: int, text: str, parse_mode: str = "HTML"):
    payload = {"chat_id": chat_id, "text": text}
    # only include parse_mode if provided to avoid Telegram errors with malformed content
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return await api_request(session, "sendMessage", payload)

# ---------------- OSINT FETCH & NORMALIZER ----------------
async def fetch_osint(number: str):
    url = OSINT_API_TEMPLATE.format(term=number)
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(url, timeout=12) as r:
                raw = await r.text()
                # write raw debug file (best-effort)
                try:
                    fname = f"osint_{number}_{int(time.time())}.json"
                    with open(fname, "w", encoding="utf-8") as f:
                        f.write(raw)
                except Exception:
                    pass
                try:
                    return json.loads(raw)
                except Exception:
                    return {"_raw_text": raw, "_error": "invalid_json"}
        except Exception as e:
            return {"_error": str(e)}

def normalize_osint_response(resp):
    if not resp:
        return None
    if isinstance(resp, dict) and set(resp.keys()) <= {"_error", "_raw_text", "error"}:
        return None

    candidate = None
    if isinstance(resp, dict):
        for k in ("data", "result", "records", "items", "output"):
            if k in resp and resp[k]:
                if isinstance(resp[k], list) and len(resp[k]) > 0 and isinstance(resp[k][0], dict):
                    candidate = resp[k][0]
                    break
                if isinstance(resp[k], dict):
                    candidate = resp[k]
                    break
        if candidate is None:
            if set(resp.keys()) & {"name", "fullname", "father", "email", "address", "id", "aadhar", "operator"}:
                candidate = resp

    if candidate is None and isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], dict):
        candidate = resp[0]

    if not candidate or not isinstance(candidate, dict):
        return None

    def pick(*names, default="N/A"):
        for n in names:
            v = candidate.get(n)
            if v is not None and v != "":
                return v
        return default

    return {
        "name": pick("name", "fullname", "owner", "username", "full_name"),
        "father": pick("father", "father_name", "f_name", "parent"),
        "email": pick("email", "mail", "e_mail"),
        "alt": pick("alt", "alt_number", "alternate", "secondary", "phone2", "mobile2"),
        "circle": pick("circle", "network", "operator", "service_provider"),
        "id_field": pick("id", "nid", "aadhar", "aadhar_no", "id_no", "identification"),
        "address": pick("address", "addr", "location", "residence", "permanent_address"),
    }
    # ---------------- COMMAND HANDLER & POLLING (PART 2) ----------------

def is_owner(uid: int):
    return uid == OWNER_ID

async def process_message(session, msg):
    """
    Full message handler:
    - logs incoming update to last_update.json
    - strips @BotName from commands
    - handles /start and /help immediately
    - processes lookups, credits, redeem, and owner commands
    No slow-mode blocking (completely removed).
    """

    # Log raw update for debugging
    try:
        raw = json.dumps(msg, ensure_ascii=False, indent=2)
    except Exception:
        raw = str(msg)
    print("=== Incoming message ===")
    print(raw)
    try:
        with open("last_update.json", "w", encoding="utf-8") as f:
            f.write(raw)
    except Exception:
        pass

    # Ensure text
    if "text" not in msg:
        return

    text = msg["text"].strip()
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    from_user = msg.get("from") or {}
    user_id = from_user.get("id")
    username = from_user.get("username") or from_user.get("first_name") or ""
    ensure_user(user_id, username)

    # Only process commands
    if not text.startswith("/"):
        return

    # Parse command and argument and strip @BotName if present
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    print(f"Normalized command: {cmd} | arg: '{arg}' | from: {user_id} @{username}")

    # Immediate /start
    if cmd == "/start":
        total = get_user_count()
        await send_message(session, chat_id,
            f"Welcome to FIRE DROP OSINT bot.\n🔥 Total Users: {total}\n\nType /help to see command menu.")
        # update bot description (best-effort)
        try:
            await api_request(session, "setMyDescription", {"description": f"FIRE DROP OSINT — Users: {total}"})
        except Exception:
            pass
        return

    # Immediate /help
    if cmd == "/help":
        await send_message(session, chat_id,
            "/num <number> - number info check\n"
            "/addhar <id> - addhar info check\n"
            "/gaddi <vehicle> - vehicle info check\n"
            "/credits - available credits\n\n"
            "Note: This is an OSINT bot that uses leaked DBs. Accuracy not guaranteed.")
        return

    # Credits
    if cmd in ("/credits", "/credit"):
        user = get_user(user_id)
        credits = user[2] if user else 0
        await send_message(session, chat_id, f"💎 Credits Left: {credits}")
        return

    # OSINT lookups
    if cmd in ("/num", "/addhar", "/aadhar", "/aadhaar", "/gaddi"):
        if not arg:
            await send_message(session, chat_id, "Usage: /num 9876543210")
            return

        user = get_user(user_id)
        credits = user[2] if user else 0
        if credits <= 0:
            await send_message(session, chat_id, f"Dear {username} you have used all ur credit Dm @Firedrop_69 to buys credits.")
            return

        # stats
        inc_cmd_count(user_id)

        resp = await fetch_osint(arg)
        norm = normalize_osint_response(resp)

        if norm:
            reply = TEMPLATE_FOUND.format(
                number=arg,
                name=norm["name"],
                father=norm["father"],
                email=norm["email"],
                alt_number=norm["alt"],
                circle=norm["circle"],
                id_field=norm["id_field"],
                address=norm["address"],
                credits_left=max(0, credits - 1)
            )
        else:
            # notify owner with preview for debugging
            try:
                preview = json.dumps(resp, ensure_ascii=False) if not isinstance(resp, str) else str(resp)
            except Exception:
                preview = str(resp)
            try:
                # send small preview only
                await send_message(session, OWNER_ID, f"OSINT parse warning for `{arg}`:\n{preview[:1200]}")
            except Exception:
                pass
            reply = TEMPLATE_NOT_FOUND.format(credits_left=max(0, credits - 1))

        # deduct credit and send
        change_credits(user_id, -1)
        await send_message(session, chat_id, reply)
        return

    # Redeem
    if cmd == "/redeem":
        if not arg:
            await send_message(session, chat_id, "Usage: /redeem CODE")
            return
        code = arg.strip().upper()
        pts = redeem_code_db(code)
        if pts is None:
            await send_message(session, chat_id, "Invalid or expired redeem code.")
            return
        new = change_credits(user_id, pts)
        await send_message(session, chat_id, f"Redeemed {pts} credits! New balance: {new}")
        return

    # Owner commands
    if is_owner(user_id):
        if cmd == "/gen":
            parts = arg.split()
            if len(parts) != 2:
                await send_message(session, chat_id, "Usage: /gen <credit_amount> <uses>")
                return
            try:
                credit_amount = int(parts[0]); uses = int(parts[1])
            except:
                await send_message(session, chat_id, "Invalid arguments.")
                return
            code = create_redeem_code(credit_amount, uses)
            await send_message(session, chat_id, f"Generated code: {code} (credits: {credit_amount}, uses: {uses})")
            return

        if cmd == "/announcement":
            if not arg:
                await send_message(session, chat_id, "Usage: /announcement <message>")
                return
            conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT tg_id FROM users"); rows = cur.fetchall(); conn.close()
            sent = 0
            for r in rows:
                try:
                    await send_message(session, r[0], f"📢 Announcement:\n\n{arg}")
                    sent += 1
                except Exception:
                    pass
            await send_message(session, chat_id, f"Announcement sent to {sent} users.")
            return

        if cmd == "/give":
            parts = arg.split()
            if len(parts) < 2:
                await send_message(session, chat_id, "Usage: /give <all|tg-id> <amount>")
                return
            target = parts[0]
            try:
                amount = int(parts[1])
            except:
                await send_message(session, chat_id, "Amount must be integer.")
                return
            if target.lower() == "all":
                conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT tg_id FROM users"); rows = cur.fetchall(); conn.close()
                for r in rows:
                    change_credits(r[0], amount)
                await send_message(session, chat_id, f"Gave {amount} credits to all users ({len(rows)} users).")
            else:
                try:
                    uid = int(target); ensure_user(uid, ""); new = change_credits(uid, amount)
                    await send_message(session, chat_id, f"Gave {amount} credits to {uid}. New balance: {new}")
                    try:
                        await send_message(session, uid, f"You received {amount} free credits from the owner! New balance: {new}")
                    except:
                        pass
                except:
                    await send_message(session, chat_id, "Invalid target.")
            return

        if cmd == "/rem":
            if not arg:
                await send_message(session, chat_id, "Usage: /rem <tg-id>")
                return
            try:
                uid = int(arg.split()[0])
            except:
                await send_message(session, chat_id, "Invalid tg-id.")
                return
            set_slowed_until(uid, 0)
            change_credits(uid, 5)
            try:
                await send_message(session, uid, "Hello! +5 credits added. Thanks for supporting.")
            except:
                pass
            await send_message(session, chat_id, f"Given 5 credits to {uid}.")
            return

    # Unknown command -> ignore silently
    return

# ---------------- Poll loop ----------------
async def poll_updates():
    init_db()
    print("DB initialized. Starting poll loop...")
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                params = {"timeout": POLL_TIMEOUT, "offset": offset, "allowed_updates": ["message"]}
                async with session.get(f"{API_BASE}/getUpdates", params=params, timeout=POLL_TIMEOUT+10) as resp:
                    data = await resp.json()
                if not data.get("ok"):
                    await asyncio.sleep(1)
                    continue
                updates = data.get("result") or []
                for upd in updates:
                    offset = max(offset, upd["update_id"] + 1)
                    if "message" in upd:
                        asyncio.create_task(process_message(session, upd["message"]))
            except Exception as e:
                print("Polling error:", e)
                await asyncio.sleep(1)

# ---------------- Entry point ----------------
if __name__ == "__main__":
    try:
        asyncio.run(poll_updates())
    except KeyboardInterrupt:
        print("Stopped by user")