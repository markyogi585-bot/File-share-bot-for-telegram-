# 🗄️ Telegram File Share Bot — Ultra Advanced

> **Force Join** + **Encrypted Files** + **Share Links** + **Admin Panel** + **Railway Hosting**

---

## ✨ Features

### 📁 File Management
- Upload **unlimited files** (documents, videos, audio, photos, stickers, voice notes, animations)
- Files stored in a **private Telegram channel** (Telegram's own CDN, free & unlimited)
- Unique **file key** for every upload
- **Rename** files anytime
- **Delete** files anytime
- **Search** files by name or `#tags`
- File **info** (size, downloads, upload date)
- Paginated `/myfiles` list

### 🔐 Security
- **Password lock** any file (AES-256 PBKDF2 hashing)
- **Unlock** files
- Encrypted **share links** using Fernet symmetric encryption
- **Rate limiting** per user (upload/download)
- **Ban/Unban** users
- HMAC integrity signatures

### 🔗 Share Links
- Deep link format: `https://t.me/BOT?start=get_FILEKEY`
- Works without any extra app — pure Telegram
- Password-protected links ask for password before delivery

### 📢 Force Join
- Require users to join **N channels** before using bot
- Dynamic channel management (add/remove without restart)
- Re-verify button

### 👤 User Features
- **Profile** page
- **Referral system** with leaderboard
- **Bot stats** (total users, files, storage)

### 🔑 Admin Panel
- `/admin` — Full admin dashboard with stats
- `/broadcast` — Broadcast to all users
- `/ban` / `/unban` — User management
- `/addchannel` / `/removechannel` — Force join channel management
- `/forcejoin` — Toggle force join on/off
- `/maintenance` — Maintenance mode toggle
- `/setlimit` — Change file/storage limits
- `/logs` — Download bot logs
- `/botinfo` — System information

### ⚙️ System
- **Railway.app** ready (webhook + polling support)
- **MongoDB** with Motor (async) — indexed for performance
- **APScheduler** for auto-cleanup of expired files
- **Zero crash** global error handler
- Graceful shutdown

---

## 🚀 Railway Deployment (5 minutes)

### Step 1 — MongoDB Setup
1. Go to [MongoDB Atlas](https://cloud.mongodb.com)
2. Create free cluster
3. Database Access → Add user
4. Network Access → Allow `0.0.0.0/0`
5. Copy connection string

### Step 2 — Storage Channel
1. Create a **private Telegram channel**
2. Add your bot as **admin** (Post Messages permission)
3. Get channel ID: Forward a message to `@userinfobot`
4. Channel ID starts with `-100`

### Step 3 — Railway Deploy
1. Push this code to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. In **Variables** tab, set all env vars from `.env.example`
4. Deploy! ✅

### Step 4 — Set Webhook (Optional, better for production)
After deploy, set `WEBHOOK_URL=https://your-app.railway.app` in Railway variables.
The bot auto-detects `PORT` from Railway and uses webhook mode.

---

## 📦 Local Development

```bash
git clone <repo>
cd tg_filebot

# Install dependencies
pip install -r requirements.txt

# Copy env file
cp .env.example .env
# Edit .env with your values

# Run
python bot.py
```

---

## 🌐 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | From @BotFather |
| `BOT_USERNAME` | ✅ | Without @ |
| `ADMIN_IDS` | ✅ | Comma-separated user IDs |
| `MONGO_URI` | ✅ | MongoDB connection string |
| `STORAGE_CHANNEL_ID` | ✅ | Private channel ID (starts with -100) |
| `FORCE_JOIN_CHANNELS` | ⬜ | Comma-separated @channels |
| `ENCRYPTION_KEY` | ⬜ | 32+ char random string |
| `WEBHOOK_URL` | ⬜ | Your Railway app URL |
| `BOT_NAME` | ⬜ | Display name |
| `MAX_FILE_SIZE_MB` | ⬜ | Default: 2000 |
| `MAX_FILES_PER_USER` | ⬜ | Default: 1000 |

---

## 📁 Project Structure

```
tg_filebot/
├── bot.py              # Entry point
├── config.py           # All settings
├── requirements.txt    # Dependencies  
├── Procfile            # Railway start command
├── railway.json        # Railway config
├── handlers/
│   ├── start_handler.py    # /start, /help, /profile
│   ├── file_handler.py     # Upload, download, lock, share
│   ├── admin_handler.py    # Full admin panel
│   └── channel_handler.py  # Force join verify
├── middlewares/
│   ├── force_join.py       # Channel membership check
│   └── rate_limiter.py     # Per-user rate limiting
├── database/
│   └── mongodb.py          # All DB operations
└── utils/
    ├── encryption.py       # AES-256 + link tokens
    ├── helpers.py          # Formatting utilities
    ├── scheduler.py        # Background tasks
    └── logger.py           # Structured logging
```

---

## ⚡ Commands Reference

**User Commands:**
```
/start          — Bot start + welcome
/get <key>      — File retrieve karo
/myfiles        — Apni files dekho  
/delete <key>   — File delete karo
/rename <key> <name>  — File rename karo
/lock <key> <pass>    — File lock karo
/unlock <key>   — Lock hatao
/share <key>    — Share link banao
/info <key>     — File info
/search <query> — Files search karo
/profile        — Apna profile
/stats          — Bot stats
/referral       — Referral link
/leaderboard    — Top referrers
/help           — Help message
```

**Admin Commands:**
```
/admin          — Admin panel
/broadcast <msg>        — All users ko message
/ban <id> [reason]      — User ban
/unban <id>             — User unban
/addchannel @ch Name    — Force join channel add
/removechannel @ch      — Channel remove
/channels               — Channel list
/setlimit <setting> <val> — Limits change
/allusers               — Users list
/allfiles               — Files count
/forcejoin              — Toggle force join
/maintenance            — Toggle maintenance
/logs                   — Bot logs download
/botinfo                — System info
```
