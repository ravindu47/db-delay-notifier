
# 🚆 CommuteBot Pro (SaaS Edition)

**CommuteBot Pro** is an intelligent, multi-user rail assistant designed for the **Passau — Mühldorf** railway line in Germany. Unlike standard scheduling apps, this bot uses **predictive algorithms (80/20 Rule)** and **persistent user profiles** to deliver proactive, context-aware travel alerts.

It is built to run as a **SaaS (Software as a Service)** model, supporting hundreds of students and commuters with personalized schedules using a single cloud instance.

---

## 🎯 The Problem

Commuters on regional lines often face a repetitive struggle:

1. Opening the DB Navigator app multiple times a day.
2. Manually searching for the same connections (Home ↔ Work).
3. Missing crucial updates like **Platform Changes** or **Cancellations** until they arrive at the station.

## 💡 The Solution

CommuteBot Pro eliminates manual checking. It "knows" where you need to be based on the time of day and notifies you **only** when there is relevant information (Delays, Platform changes, etc.).

---

## ✨ Key Features

### 🧠 1. Smart "80/20" Prediction Algorithm

The bot intelligently guesses your direction based on the time of day:

* **04:00 - 14:00 (Morning Mode):** Automatically monitors trains from **Home → Work**.
* **14:00 - 04:00 (Evening Mode):** Automatically monitors trains from **Work → Home**.
* *Result:* Users get the right information without typing a single command.

### 🗄️ 2. Persistent User Database (Supabase)

* User preferences (`Home Station`, `Work Station`, `Shift Type`) are stored in a **PostgreSQL Database**.
* **Benefit:** Data is never lost, even if the hosting server restarts.
* **Scalability:** Supports unlimited unique users with custom routes.

### 📢 3. Advanced Alert System

The bot parses complex API data to provide specific alerts:

* **🚨 Platform Changes:** Compares `plannedPlatform` vs. `actualPlatform` and alerts users immediately (e.g., *"Change to Platform 3!"*).
* **⚠️ Delay Thresholds:** Highlights delays over 5 minutes.
* **❌ Cancellations:** Instant notification if a trip is cancelled.

### 🔗 4. Complex Journey Tracking

* Supports **Connecting Trains**: Instead of just departures, it tracks full journeys (A → Transfer → B).
* **Transfer Logic:** Displays where to change trains and the waiting time.

### 🌙 5. Shift Worker Support

* Includes a **Day/Night Mode** toggle.
* *Night Mode:* Reverses the 80/20 logic for users working night shifts (Morning = Home, Evening = Work).

---

## 🏗️ System Architecture

```mermaid
graph TD
    User[Telegram User] -->|Commands| Bot[Python Bot (Render)]
    Bot -->|Read/Write| DB[(Supabase PostgreSQL)]
    Bot -->|Fetch Schedule| API[Deutsche Bahn API v6]
    API -->|JSON Data| Bot
    Bot -->|Formatted Alert| User

```

---

## 🛠️ Installation & Setup

### Prerequisites

* Python 3.9+
* A Telegram Bot Token (via @BotFather)
* A Supabase Account (Free Tier)
* Render Account (for hosting)

### 1. Database Setup (Supabase)

1. Create a new project on [Supabase]().
2. Go to the **SQL Editor** and run this schema:

```sql
-- Creates a table to store user preferences with support for updates
CREATE TABLE users (
    chat_id BIGINT PRIMARY KEY,  -- Telegram User ID
    home_id TEXT,                -- Station ID (EVA_NR)
    home_name TEXT,              -- Station Name
    work_id TEXT,
    work_name TEXT,
    shift_type TEXT DEFAULT 'day', -- 'day' or 'night'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

```

### 2. Environment Variables

Create a `.env` file or set these in your cloud provider:

```bash
TELEGRAM_TOKEN=your_telegram_bot_token
ADMIN_ID=your_personal_telegram_id
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres
PORT=10000

```

### 3. Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py

```

---

## 📱 User Guide (Commands)

| Command | Description |
| --- | --- |
| `/start` | Registers the user in the database and shows the welcome guide. |
| `/sethome <name>` | Search and set your **Home** station (e.g., `/sethome Bad Birnbach`). |
| `/setwork <name>` | Search and set your **Work/Uni** station (e.g., `/setwork Pfarrkirchen`). |
| `/mode <day/night>` | Toggle your shift type. Useful for night-shift workers. |
| `/check` | Manually triggers an instant schedule check for your current route. |

---

## 🔮 Future Roadmap

* [ ] **Push Notifications:** Alert only when a delay > 10 mins occurs (Silent mode otherwise).
* [ ] **Subscription Model:** Integration with Stripe for premium features.
* [ ] **Calendar Sync:** Sync train times with Google Calendar.
* [ ] **GPS Support:** "Take me home" feature using live location.

---

## ⚖️ Disclaimer

This project uses the public **Deutsche Bahn API (v6)**. It is an independent project and is not affiliated with Deutsche Bahn AG.

---

**Maintained by:** Chameesha Ravindu
**License:** MIT

