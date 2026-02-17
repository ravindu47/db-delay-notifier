# 🚆 CommuteBot Pro (Hybrid SaaS Edition)

**CommuteBot Pro** is a high-performance, context-aware rail assistant for Germany. It uses **predictive algorithms** and **dual-track monitoring** to support students and workers commuting to multiple locations (Work and University).

---

## 💡 The Solution

This bot eliminates the need to manually check the DB Navigator app. It understands your daily routine and sends proactive alerts for delays, cancellations, or platform changes specifically for your upcoming trip.

## ✨ Advanced Features

### 🎓 1. Dual-Track Monitoring (Work + Uni)

* Users can set both **Work** and **University** locations.
* The bot tracks both schedules and provides a combined status report.

### ⏰ 2. Dynamic "80/20" Prediction

* Unlike fixed timers, users set their own **Work Start Time** (e.g., `/time 8`).
* The bot automatically switches direction:
* **Morning:** Home ➔ Work/Uni (Starts 2h before work).
* **Evening:** Work/Uni ➔ Home.



### 📢 3. Intelligent Status Reporting

* **Zero Delay Mode:** Shows "✅ No Delays" and upcoming train details even when on time.
* **Real-time Alerts:** Instant notifications for cancellations and platform shifts.

### 🔗 4. IPv6 Optimized Connection

* Uses **Supabase Connection Pooling (Port 6543)** to ensure 100% uptime on cloud hosting like Render, bypassing common IPv6 network issues.

---

## 🏗️ System Architecture

1. **User** ───> **Telegram Bot** (Slash Commands: /setuni, /setwork, /check)
2. **Bot** ───> **Supabase DB (Port 6543)** (Stores User Profiles & Custom Shifts)
3. **Bot** ───> **DB Transport API v6** (Fetches real-time journey data)
4. **API** ───> **Bot** (Parses delays, cancellations & platform data)
5. **Bot** ───> **User** (Proactive Smart Alerts)

---

## 🛠️ Installation & Setup

### 1. Database Schema

Run this in your Supabase SQL Editor to support the Hybrid features:

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

### 2. Environment Variables (.env)

**Note:** Use the Pooler URI for the `DATABASE_URL` to avoid connectivity errors.

```env
TELEGRAM_TOKEN=your_bot_token
ADMIN_ID=your_id
DATABASE_URL=postgresql://[user].[project_id]:[pass]@aws-1-eu-west-1.pooler.supabase.com:6543/postgres
PORT=10000

```

---

## 📱 User Guide (Commands)

| Command | Description |
| --- | --- |
| `/start` | Register and see the setup guide. |
| `/sethome <name>` | Set your Home station (e.g., `/sethome Passau`). |
| `/setwork <name>` | Set your Work station (e.g., `/setwork Mühldorf`). |
| `/setuni <name>` | Set your University station (e.g., `/setuni Deggendorf`). |
| `/time <hour>` | Set your shift start time (e.g., `/time 9`). |
| `/mode` | Toggle between **Day** and **Night** shift logic. |
| `/check` | **Instant Check:** Shows the nearest train/bus for your current route. |

---

## 🔮 Future Roadmap

* [ ] **Multi-Station Support:** Adding support for more than two destinations.
* [ ] **Silent Hours:** Customizable "Do Not Disturb" settings.
* [ ] **Delay History:** Statistics on line reliability.

---

**Maintained by:** Chameesha Ravindu
**License:** MIT

---
