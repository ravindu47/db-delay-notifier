
---

# 🚆 CommuteBot Pro (Hybrid SaaS Edition)

**CommuteBot Pro** is a comprehensive, context-aware rail assistant designed for students and professionals in Germany. Unlike standard scheduling apps, this bot tracks **Work** and **University** commutes simultaneously, using a dynamic "80/20 Rule" to predict your direction based on your shift start time.

It is architected as a **SaaS (Software as a Service)** application, capable of handling multiple users with isolated profiles using a single cloud instance.

---

## ✨ Key Features

### 🎓 1. Hybrid Commute Tracking (Uni + Work)

* Supports dual destinations: **Workplace** and **University**.
* Users can switch contexts or monitor both simultaneously using `/check`.

### 🧠 2. Dynamic "80/20" Prediction Algorithm

* **Smart Routing:** The bot predicts your direction based on your specific **Start Hour** (e.g., 08:00 AM).
* **Morning Mode (Start - 2h):** Monitors Home ➔ Work/Uni.
* **Evening Mode (Start + 6h):** Monitors Work/Uni ➔ Home.


* **Manual Override:** Use `/mode` to toggle logic for Night Shifts.

### ⚡ 3. 24/7 Keep-Alive Architecture

* Built with a lightweight **Flask Web Server** running alongside the Telegram bot.
* Prevents cloud platforms (like Render Free Tier) from "sleeping" by accepting periodic ping requests.

### 📢 4. Intelligent Alerts

* **Status Coding:**
* 🟢 **Green:** "No Delays" (Bot confirms the train is on time).
* 🔴 **Red:** "Cancelled" or "High Delay" (>5 mins).
* 📢 **Orange:** "Platform Change" alerts.


* **IPv6 Optimized:** Uses Supabase Connection Pooling (Port 6543) for stable cloud connectivity.

---

## 🏗️ System Workflow

```text
1. User  ───> (Telegram Bot) ───> Sets Profile (/setwork, /time 8)
2. Bot   ───> (Supabase DB)  ───> Saves Preferences via Connection Pooler
3. Bot   ───> (DB API v6)    ───> Fetches Real-time Journey Data
4. API   ───> (Bot)          ───> Returns Delays, Platforms & Transfers
5. Bot   ───> (User)         ───> Sends Formatted Smart Alert

```

---

## 🛠️ Deployment Guide (From Scratch)

Follow these steps to deploy the bot on **Render** with **Supabase**.

### Phase 1: Database Setup (Supabase)

1. Create a free project at [supabase.com]().
2. Go to the **SQL Editor** and run this schema:

```sql
CREATE TABLE users (
    chat_id BIGINT PRIMARY KEY,
    home_id TEXT, home_name TEXT,
    work_id TEXT, work_name TEXT,
    uni_id TEXT, uni_name TEXT,
    shift_type TEXT DEFAULT 'day',
    start_hour INT DEFAULT 8,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

```

3. Go to **Settings > Database > Connection Pooler**.
4. Change Mode to **Transaction**.
5. Copy the **Connection String (URI)** and replace port `5432` with `6543`.
* *Format:* `postgresql://[user].[project]:[pass]@[host]:6543/postgres`



### Phase 2: Render Deployment (Hosting)

1. Push your code to **GitHub**.
2. Log in to [dashboard.render.com]() and create a **New Web Service**.
3. Connect your GitHub repository.
4. **Configure Settings:**
* **Runtime:** Python 3
* **Build Command:** `pip install -r requirements.txt`
* **Start Command:** `python bot.py`


5. **Environment Variables:**
Add the following variables in the "Environment" tab:

| Key | Value |
| --- | --- |
| `TELEGRAM_TOKEN` | Your Bot Token from @BotFather |
| `DATABASE_URL` | Your Supabase URI (Port 6543) |
| `ADMIN_ID` | Your Telegram User ID |
| `PORT` | `10000` |

### Phase 3: Preventing Sleep (The Ping Method)

Render's free tier spins down after 15 minutes of inactivity. To keep the bot alive 24/7:

1. Copy your **Render App URL** (e.g., `https://commutebot-pro.onrender.com`).
2. Go to a free cron service like **Cron-job.org** or **UptimeRobot**.
3. Create a new monitor:
* **URL:** `https://your-app-name.onrender.com/`
* **Interval:** Every **14 minutes** (Must be less than 15).


4. This hits the Flask server inside `bot.py`, keeping the process active indefinitely.

---

## 📱 User Commands (Menu)

The bot features a pop-up menu for easy navigation:

* `/start` - Initialize and see instructions.
* `/check` - **Instant Status:** Shows the next connection for Work/Uni.
* `/sethome <station>` - Set Home location.
* `/setwork <station>` - Set Work location.
* `/setuni <station>` - Set University location.
* `/time <hour>` - Set your shift start time (e.g., `/time 8`).
* `/mode` - Toggle Day/Night shift logic.

---

## ⚠️ Troubleshooting

* **"Network is unreachable" Error:**
* Ensure you are using the Supabase **Connection Pooler** URL (Port `6543`), not the direct connection.


* **"Station not found":**
* The bot uses URL encoding to handle German characters (ä, ö, ü). Try typing the main city name first.



---

## ⚖️ Disclaimer

This project uses the public **Deutsche Bahn API (v6)**. It is an independent open-source project and is not affiliated with Deutsche Bahn AG.

---

**Maintained by:** Chameesha Ravindu
**License:** MIT

---
