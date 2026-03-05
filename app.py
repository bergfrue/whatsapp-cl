"""
WhatsApp Clone - Python Flask Backend
======================================
Real-time multi-user chat using:
  - Flask (web framework)
  - SQLite (database)
  - Server-Sent Events (real-time push)
  - Sessions (authentication)

Run: python app.py
Open: http://localhost:5000
Share on LAN: http://<your-ip>:5000
"""

import sqlite3
import hashlib
import json
import time
import queue
import threading
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, Response, g
)

app = Flask(__name__)
app.secret_key = "whatsapp_clone_secret_key_change_in_production"

DB_PATH = "whatsapp.db"

# ─── SSE MESSAGE BROKER ──────────────────────────────────────────────────────
# Each connected client gets a queue; new messages are broadcast to all queues.

class MessageBroker:
    def __init__(self):
        self.listeners: dict[int, list[queue.Queue]] = {}  # user_id -> [queues]
        self.lock = threading.Lock()

    def subscribe(self, user_id: int) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self.lock:
            self.listeners.setdefault(user_id, []).append(q)
        return q

    def unsubscribe(self, user_id: int, q: queue.Queue):
        with self.lock:
            if user_id in self.listeners:
                try:
                    self.listeners[user_id].remove(q)
                except ValueError:
                    pass

    def notify(self, user_id: int, data: dict):
        """Send an event to a specific user."""
        with self.lock:
            for q in self.listeners.get(user_id, []):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass

    def broadcast_to_conversation(self, participant_ids: list[int], data: dict):
        for uid in participant_ids:
            self.notify(uid, data)


broker = MessageBroker()


# ─── DATABASE ─────────────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL,
            avatar   TEXT    NOT NULL DEFAULT '',
            about    TEXT    NOT NULL DEFAULT 'Hey there! I am using WhatsApp Clone.',
            online   INTEGER NOT NULL DEFAULT 0,
            created  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            is_group   INTEGER NOT NULL DEFAULT 0,
            name       TEXT,
            created_by INTEGER REFERENCES users(id),
            created    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS participants (
            conv_id INTEGER NOT NULL REFERENCES conversations(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (conv_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id INTEGER NOT NULL REFERENCES conversations(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            text    TEXT    NOT NULL,
            ts      TEXT    NOT NULL DEFAULT (datetime('now')),
            read_by TEXT    NOT NULL DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id, ts);
    """)
    conn.commit()

    # Seed demo users
    demo_users = [
        ("alice",   "alice123",   "", "Building cool stuff"),
        ("bob",     "bob123",     "", "Music lover"),
        ("carol",   "carol123",   "", "Bookworm"),
        ("dave",    "dave123",    "", "Football fan"),
    ]
    for username, password, avatar, about in demo_users:
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (username,password,avatar,about) VALUES (?,?,?,?)",
                (username, hash_password(password), avatar, about)
            )
    conn.commit()

    # Seed demo conversations between demo users
    alice = conn.execute("SELECT id FROM users WHERE username='alice'").fetchone()
    bob   = conn.execute("SELECT id FROM users WHERE username='bob'").fetchone()
    carol = conn.execute("SELECT id FROM users WHERE username='carol'").fetchone()
    dave  = conn.execute("SELECT id FROM users WHERE username='dave'").fetchone()

    if alice and bob and carol and dave:
        # Check if conversations already exist
        if not conn.execute("SELECT id FROM conversations LIMIT 1").fetchone():
            # Direct chat: alice <-> bob
            c1 = conn.execute(
                "INSERT INTO conversations (is_group) VALUES (0)"
            ).lastrowid
            conn.execute("INSERT INTO participants VALUES (?,?)", (c1, alice["id"]))
            conn.execute("INSERT INTO participants VALUES (?,?)", (c1, bob["id"]))
            _seed_messages(conn, c1, [
                (alice["id"], "Hey Bob! How are you? 👋"),
                (bob["id"],   "Hey Alice! Doing great, thanks! 😊"),
                (alice["id"], "Great! Want to work on that project together?"),
                (bob["id"],   "Absolutely! Let's do it 🚀"),
            ])

            # Direct chat: alice <-> carol
            c2 = conn.execute(
                "INSERT INTO conversations (is_group) VALUES (0)"
            ).lastrowid
            conn.execute("INSERT INTO participants VALUES (?,?)", (c2, alice["id"]))
            conn.execute("INSERT INTO participants VALUES (?,?)", (c2, carol["id"]))
            _seed_messages(conn, c2, [
                (carol["id"], "Hey Alice, did you read that new book? 📚"),
                (alice["id"], "Not yet! Is it good?"),
                (carol["id"], "It's amazing! You have to read it"),
            ])

            # Group: Dev Team
            c3 = conn.execute(
                "INSERT INTO conversations (is_group,name,created_by) VALUES (1,'Dev Team 🚀',?)",
                (alice["id"],)
            ).lastrowid
            for uid in [alice["id"], bob["id"], carol["id"], dave["id"]]:
                conn.execute("INSERT INTO participants VALUES (?,?)", (c3, uid))
            _seed_messages(conn, c3, [
                (alice["id"], "Welcome to the Dev Team group! 🎉"),
                (bob["id"],   "Awesome! Ready to ship some code 💻"),
                (carol["id"], "Let's crush it! 💪"),
                (dave["id"],  "Wohooo!! 🔥"),
            ])

    conn.commit()
    conn.close()


def _seed_messages(conn, conv_id, msgs):
    for i, (uid, text) in enumerate(msgs):
        ts = datetime.now().strftime(f"%Y-%m-%d %H:%M:{i:02d}")
        conn.execute(
            "INSERT INTO messages (conv_id,user_id,text,ts) VALUES (?,?,?,?)",
            (conv_id, uid, text, ts)
        )


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def require_login(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def format_time(ts_str: str) -> str:
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return ts_str
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%I:%M %p")
    elif (now - dt).days < 7:
        return dt.strftime("%A")
    return dt.strftime("%d/%m/%Y")


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return redirect(url_for("chat"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, hash_password(password))
        ).fetchone()
        if user:
            session["user_id"] = user["id"]
            db.execute("UPDATE users SET online=1 WHERE id=?", (user["id"],))
            db.commit()
            return redirect(url_for("chat"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        avatar   = request.form.get("avatar", "😊")
        if not username or not password:
            error = "Username and password required"
        elif len(username) < 3:
            error = "Username must be at least 3 characters"
        elif len(password) < 4:
            error = "Password must be at least 4 characters"
        else:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username,password,avatar) VALUES (?,?,?)",
                    (username, hash_password(password), avatar)
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                session["user_id"] = user["id"]
                db.execute("UPDATE users SET online=1 WHERE id=?", (user["id"],))
                db.commit()
                return redirect(url_for("chat"))
            except sqlite3.IntegrityError:
                error = "Username already taken"
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    uid = session.get("user_id")
    if uid:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE users SET online=0 WHERE id=?", (uid,))
            conn.commit()
            conn.close()
        except Exception:
            pass
    session.clear()
    return redirect(url_for("login"))


@app.route("/chat")
@require_login
def chat():
    user = current_user()
    db   = get_db()

    # All conversations this user is part of
    convs_raw = db.execute("""
        SELECT c.id, c.is_group, c.name,
               m.text AS last_text, m.ts AS last_ts, m.user_id AS last_uid
        FROM   conversations c
        JOIN   participants  p ON p.conv_id = c.id AND p.user_id = ?
        LEFT JOIN messages   m ON m.id = (
            SELECT id FROM messages WHERE conv_id=c.id ORDER BY ts DESC LIMIT 1
        )
        ORDER BY COALESCE(m.ts,'') DESC
    """, (user["id"],)).fetchall()

    conversations = []
    for c in convs_raw:
        conv = dict(c)
        if not c["is_group"]:
            # Get the other participant
            other = db.execute("""
                SELECT u.id, u.username, u.avatar, u.online
                FROM participants p
                JOIN users u ON u.id = p.user_id
                WHERE p.conv_id=? AND p.user_id != ?
            """, (c["id"], user["id"])).fetchone()
            if other:
                conv["display_name"]   = other["username"]
                conv["display_avatar"] = other["avatar"]
                conv["other_online"]   = other["online"]
                conv["other_id"]       = other["id"]
            else:
                conv["display_name"]   = "Unknown"
                conv["display_avatar"] = "?"
                conv["other_online"]   = 0
        else:
            conv["display_name"]   = c["name"] or "Group"
            conv["display_avatar"] = "👥"
            conv["other_online"]   = 0

        # Unread count
        read_msgs = db.execute("""
            SELECT COUNT(*) as cnt FROM messages
            WHERE conv_id=? AND user_id != ?
            AND json_extract(read_by,'$') NOT LIKE ?
        """, (c["id"], user["id"], f'%{user["id"]}%')).fetchone()
        conv["unread"] = read_msgs["cnt"] if read_msgs else 0

        if c["last_ts"]:
            conv["last_time"] = format_time(c["last_ts"])
        else:
            conv["last_time"] = ""

        if c["last_uid"] == user["id"]:
            conv["last_text"] = f'You: {c["last_text"] or ""}'
        else:
            conv["last_text"] = c["last_text"] or ""

        conversations.append(conv)

    # All other users (for starting new chats)
    all_users = db.execute(
        "SELECT id, username, avatar, online FROM users WHERE id != ? ORDER BY username",
        (user["id"],)
    ).fetchall()

    return render_template("chat.html",
                           user=user,
                           conversations=conversations,
                           all_users=all_users)


@app.route("/api/messages/<int:conv_id>")
@require_login
def get_messages(conv_id):
    user = current_user()
    db   = get_db()

    # Verify user is participant
    part = db.execute(
        "SELECT 1 FROM participants WHERE conv_id=? AND user_id=?",
        (conv_id, user["id"])
    ).fetchone()
    if not part:
        return jsonify({"error": "forbidden"}), 403

    msgs = db.execute("""
        SELECT m.id, m.text, m.ts, m.user_id, m.read_by,
               u.username, u.avatar
        FROM messages m
        JOIN users u ON u.id = m.user_id
        WHERE m.conv_id = ?
        ORDER BY m.ts ASC
    """, (conv_id,)).fetchall()

    # Mark as read
    for msg in msgs:
        if msg["user_id"] != user["id"]:
            try:
                read_by = json.loads(msg["read_by"])
            except Exception:
                read_by = []
            if user["id"] not in read_by:
                read_by.append(user["id"])
                db.execute(
                    "UPDATE messages SET read_by=? WHERE id=?",
                    (json.dumps(read_by), msg["id"])
                )
    db.commit()

    result = []
    for m in msgs:
        result.append({
            "id":       m["id"],
            "text":     m["text"],
            "time":     format_time(m["ts"]),
            "ts":       m["ts"],
            "user_id":  m["user_id"],
            "username": m["username"],
            "avatar":   m["avatar"],
            "is_me":    m["user_id"] == user["id"],
        })

    # Conv info
    conv = db.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    info = {"is_group": conv["is_group"], "name": conv["name"]}
    if not conv["is_group"]:
        other = db.execute("""
            SELECT u.username, u.avatar, u.online, u.about
            FROM participants p JOIN users u ON u.id=p.user_id
            WHERE p.conv_id=? AND p.user_id != ?
        """, (conv_id, user["id"])).fetchone()
        if other:
            info["other_name"]   = other["username"]
            info["other_avatar"] = other["avatar"]
            info["other_online"] = other["online"]
            info["other_about"]  = other["about"]

    return jsonify({"messages": result, "conv": info})


@app.route("/api/send", methods=["POST"])
@require_login
def send_message():
    user = current_user()
    data = request.json or {}
    conv_id = data.get("conv_id")
    text    = (data.get("text") or "").strip()

    if not conv_id or not text:
        return jsonify({"error": "missing fields"}), 400

    db = get_db()
    part = db.execute(
        "SELECT 1 FROM participants WHERE conv_id=? AND user_id=?",
        (conv_id, user["id"])
    ).fetchone()
    if not part:
        return jsonify({"error": "forbidden"}), 403

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    read_by = json.dumps([user["id"]])
    msg_id = db.execute(
        "INSERT INTO messages (conv_id,user_id,text,ts,read_by) VALUES (?,?,?,?,?)",
        (conv_id, user["id"], text, ts, read_by)
    ).lastrowid
    db.commit()

    msg_data = {
        "type":     "message",
        "id":       msg_id,
        "conv_id":  conv_id,
        "text":     text,
        "time":     format_time(ts),
        "ts":       ts,
        "user_id":  user["id"],
        "username": user["username"],
        "avatar":   user["avatar"],
        "is_me":    False,  # recipient's perspective
    }

    # Notify all participants
    participants = db.execute(
        "SELECT user_id FROM participants WHERE conv_id=?", (conv_id,)
    ).fetchall()
    for p in participants:
        uid = p["user_id"]
        payload = dict(msg_data)
        payload["is_me"] = (uid == user["id"])
        broker.notify(uid, payload)

    return jsonify({"ok": True, "id": msg_id, "time": format_time(ts)})


@app.route("/api/new_chat", methods=["POST"])
@require_login
def new_chat():
    user    = current_user()
    data    = request.json or {}
    user_id = data.get("user_id")
    db      = get_db()

    if not user_id:
        return jsonify({"error": "missing user_id"}), 400

    # Check if DM already exists
    existing = db.execute("""
        SELECT c.id FROM conversations c
        JOIN participants p1 ON p1.conv_id=c.id AND p1.user_id=?
        JOIN participants p2 ON p2.conv_id=c.id AND p2.user_id=?
        WHERE c.is_group=0
        LIMIT 1
    """, (user["id"], user_id)).fetchone()

    if existing:
        return jsonify({"conv_id": existing["id"]})

    conv_id = db.execute(
        "INSERT INTO conversations (is_group) VALUES (0)"
    ).lastrowid
    db.execute("INSERT INTO participants VALUES (?,?)", (conv_id, user["id"]))
    db.execute("INSERT INTO participants VALUES (?,?)", (conv_id, user_id))
    db.commit()
    return jsonify({"conv_id": conv_id})


@app.route("/api/new_group", methods=["POST"])
@require_login
def new_group():
    user    = current_user()
    data    = request.json or {}
    name    = (data.get("name") or "").strip()
    members = data.get("members", [])
    db      = get_db()

    if not name or not members:
        return jsonify({"error": "missing name or members"}), 400

    conv_id = db.execute(
        "INSERT INTO conversations (is_group,name,created_by) VALUES (1,?,?)",
        (name, user["id"])
    ).lastrowid
    all_members = list(set([user["id"]] + [int(m) for m in members]))
    for uid in all_members:
        db.execute("INSERT INTO participants VALUES (?,?)", (conv_id, uid))
    db.commit()
    return jsonify({"conv_id": conv_id})


@app.route("/api/users")
@require_login
def get_users():
    user = current_user()
    db   = get_db()
    users = db.execute(
        "SELECT id, username, avatar, online, about FROM users WHERE id != ?",
        (user["id"],)
    ).fetchall()
    return jsonify([dict(u) for u in users])


@app.route("/stream")
@require_login
def stream():
    """Server-Sent Events endpoint for real-time updates."""
    user = current_user()
    uid  = user["id"]

    # Mark online
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET online=1 WHERE id=?", (uid,))
    conn.commit()
    conn.close()

    q = broker.subscribe(uid)

    def event_stream():
        yield f"data: {json.dumps({'type': 'connected', 'user_id': uid})}\n\n"
        try:
            while True:
                try:
                    data = q.get(timeout=25)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    yield "data: {\"type\":\"ping\"}\n\n"
        except GeneratorExit:
            broker.unsubscribe(uid, q)
            conn2 = sqlite3.connect(DB_PATH)
            conn2.execute("UPDATE users SET online=0 WHERE id=?", (uid,))
            conn2.commit()
            conn2.close()

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":   "no-cache",
            "X-Accel-Buffering":"no",
            "Connection":      "keep-alive",
        }
    )


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket
    init_db()

    # Get local IP for sharing on LAN
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()

    print("\n" + "="*55)
    print("  💬  WhatsApp Clone  -  Python Flask")
    print("="*55)
    print(f"  Local:    http://localhost:5000")
    print(f"  Network:  http://{local_ip}:5000  ← share this!")
    print("="*55)
    print("\n  Demo accounts (username / password):")
    print("    alice  / alice123")
    print("    bob    / bob123")
    print("    carol  / carol123")
    print("    dave   / dave123")
    print("\n  Press Ctrl+C to stop\n")

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
