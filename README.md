# 💬 WhatsApp Clone — Python Flask

A fully functional real-time multi-user chat app built with **Python + Flask**.

---

## ✅ Features

| Feature | Details |
|---|---|
| 👤 Auth | Register / Login / Logout with sessions |
| 💬 DMs | One-on-one private chats |
| 👥 Groups | Create group chats with multiple users |
| ⚡ Real-time | Server-Sent Events (SSE) — no extra libraries |
| 💾 Persistence | SQLite database — messages saved forever |
| 🟢 Online status | Live online/offline indicators |
| 🔔 Unread badges | Unread message counters per conversation |
| 😊 Emoji | Built-in emoji picker |
| 📱 Responsive | Works on mobile and desktop |

---

## 🚀 Quick Start

### 1. Install Python (3.8+)
Download from https://python.org

### 2. Install Flask (only dependency)
```bash
pip install flask
```

### 3. Run the app
```bash
python app.py
```

### 4. Open in browser
```
http://localhost:5000
```

---

## 🌐 How to Share with Others

### Option A — Same Wi-Fi / LAN (easiest)
When you run `python app.py`, it prints:
```
  Network:  http://192.168.1.X:5000  ← share this!
```
Anyone on the same Wi-Fi can open that URL on their phone or laptop.

### Option B — Internet (share globally with ngrok)
1. Download ngrok from https://ngrok.com/download
2. In a second terminal:
   ```bash
   ngrok http 5000
   ```
3. Ngrok gives you a public URL like:
   ```
   https://abc123.ngrok.io
   ```
4. Share that link with anyone in the world!

### Option C — Deploy to a server (permanent)
Deploy to any cloud provider:

**Render.com (free):**
1. Push code to GitHub
2. Create new Web Service on render.com
3. Set start command: `python app.py`
4. Done — get a public URL

**Railway.app (free tier):**
```bash
railway init
railway up
```

**PythonAnywhere (free):**
1. Upload files to pythonanywhere.com
2. Set up a Flask web app
3. Point it to app.py

---

## 🔐 Demo Accounts
| Username | Password |
|---|---|
| alice | alice123 |
| bob | bob123 |
| carol | carol123 |
| dave | dave123 |

---

## 📁 Project Structure
```
whatsapp_clone/
├── app.py              ← Main Flask app (backend)
├── requirements.txt    ← Just Flask
├── whatsapp.db         ← SQLite database (auto-created)
└── templates/
    ├── login.html      ← Login page
    ├── register.html   ← Register page
    └── chat.html       ← Main chat UI
```

---

## 🛠 Tech Stack
- **Python 3.8+** — backend language
- **Flask** — web framework
- **SQLite** — database (built into Python)
- **SSE** — Server-Sent Events for real-time (no websocket libs needed)
- **Vanilla JS** — frontend (no React/Vue)
- **Pure CSS** — WhatsApp-style dark theme

---

## 🔒 Security Notes
- Passwords are SHA-256 hashed
- Sessions use Flask's signed cookies
- Change `app.secret_key` before deploying publicly!

---

## 💡 How Real-time Works (SSE)
Each browser connects to `/stream` which keeps an HTTP connection open.
When someone sends a message, the server pushes it to all participants instantly — no polling, no websocket library needed!
