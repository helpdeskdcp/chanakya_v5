import sqlite3, hashlib, os, datetime, secrets
DB_PATH = os.getenv("DB_PATH", "data/chanakya_v5.db")

def init_db():
    try:
        os.makedirs("data", exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT "demo",
            created_at TEXT,
            broker_api_key TEXT DEFAULT "",
            broker_client_id TEXT DEFAULT "",
            broker_password TEXT DEFAULT "",
            broker_totp TEXT DEFAULT "",
            is_active INTEGER DEFAULT 1
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT,
            expires_at TEXT
        )""")
        conn.commit(); conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

def _hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, email, password, role="demo"):
    try:
        conn = sqlite3.connect(DB_PATH)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO users (username,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            (username.lower(), email, _hash(password), role, now))
        conn.commit(); conn.close()
        return True
    except Exception as e:
        print(f"create_user error: {e}"); return False

def get_user(username):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM users WHERE username=?", (username.lower(),)).fetchone()
        conn.close()
        return dict(r) if r else None
    except: return None

def verify_password(username, password):
    try:
        user = get_user(username)
        if not user: return False
        return user["password_hash"] == _hash(password) and user["is_active"]
    except: return False

def update_role(username, role):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        conn.commit(); conn.close(); return True
    except: return False

def update_broker(username, api_key, client_id, password, totp):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE users SET broker_api_key=?,broker_client_id=?,broker_password=?,broker_totp=? WHERE username=?",
            (api_key, client_id, password, totp, username))
        conn.commit(); conn.close(); return True
    except: return False

def create_session(username):
    try:
        token = secrets.token_hex(32)
        now = datetime.datetime.now()
        exp = (now + datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM sessions WHERE username=?", (username,))
        conn.execute("INSERT INTO sessions (username,token,created_at,expires_at) VALUES (?,?,?,?)",
            (username, token, now.strftime("%Y-%m-%d %H:%M:%S"), exp))
        conn.commit(); conn.close()
        return token
    except: return None

def verify_session(token):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
        conn.close()
        if not r: return None
        if datetime.datetime.now() > datetime.datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S"):
            return None
        return r["username"]
    except: return None

def get_all_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except: return []

def delete_session(token):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit(); conn.close()
    except: pass

# Auto init
init_db()

# Create default admin if not exists
if not get_user("avinash"):
    create_user("avinash", "admin@chanakya.ai", "chanakya2026", "developer")
    print("Default admin created: avinash/chanakya2026")
