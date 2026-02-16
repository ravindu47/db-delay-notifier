# 🚆 DB Train Monitor Bot (Personal Assistant)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue)
![Platform](https://img.shields.io/badge/Deploy-Render-success)

A smart, resilient, and automated Telegram Bot designed to track **Deutsche Bahn (DB)** trains in real-time. It acts as a personal commute assistant, notifying you immediately about delays, cancellations, platform changes, and crowd levels.

## 🌟 Key Features

* **⚡ Real-Time Alerts:** Get notified instantly for delays (>5 mins) and cancellations.
* **🧠 Smart Search with Buttons:** Type a station name (e.g., "Eggenfelden"), and the bot suggests matches via inline buttons.
* **🔄 Auto-Resume & Persistence:** If the server restarts, the bot automatically resumes monitoring your default station (no need to type `/start` again).
* **👥 Crowd Intelligence:** Displays crowd levels (Low 🟢, Medium 🟡, High 🔴) based on DB data.
* **🌙 Smart Sleep Mode:** Automatically sleeps between **01:00 - 06:00 CET** to save server resources.
* **📍 Live Map Integration:** Provides direct links to the DB Live Tracking map.
* **🛡️ Admin Monitoring:** Sends system status and restart alerts specifically to the admin.

---

## 🛠️ Installation & Deployment Guide

This bot is designed to run 24/7 on cloud platforms like **Render** (Free Tier).

### Step 1: Prerequisites
1.  **Telegram Bot Token:** Get one from [@BotFather](https://t.me/BotFather).
2.  **Telegram User ID:** Get your ID from [@userinfobot](https://t.me/userinfobot) (This will be the Admin ID).
3.  **Station ID:** The unique ID of your default station (e.g., Bad Birnbach = `8000858`). You can find this by querying the API: `https://v6.db.transport.rest/locations?query=YourStationName`

### Step 2: Deploy to Render (Free)
1.  Fork or Clone this repository to your GitHub.
2.  Create a new **Web Service** on [Render](https://render.com).
3.  Connect your GitHub repository.
4.  Use the following settings:
    * **Runtime:** Python 3
    * **Build Command:** `pip install -r requirements.txt`
    * **Start Command:** `python bot.py`
5.  **IMPORTANT:** Go to the **"Environment"** tab and add the following variables:
    * `TELEGRAM_TOKEN`: (Your Bot Token from BotFather)
    * `ADMIN_ID`: (Your Telegram User ID, e.g., `1238096007`)

### Step 3: Keep the Bot Alive (Cron-Job)
Render's free tier spins down after inactivity. To keep it running 24/7:
1.  Go to [cron-job.org](https://cron-job.org) and sign up (free).
2.  Create a **New Cronjob**.
3.  **URL:** Enter your Render App URL (e.g., `https://your-bot-name.onrender.com/`).
4.  **Execution Schedule:** Every **5 minutes**.
5.  Save. This will "ping" your bot to keep it awake.

---

## ⚙️ Configuration (How to Change Default Station)

Currently, the bot is hardcoded to auto-monitor **Bad Birnbach** (`8000858`) upon restart. To change this to your own station:

1.  Open `bot.py`.
2.  Locate the `PERMANENT_USERS` dictionary near the top:

```python
# Default User Configuration (Auto-Resume)
PERMANENT_USERS = {
    ADMIN_ID: "8000858",  # <--- Change this ID
}

```

3. Replace `"8000858"` with the ID of your preferred station.
* *Tip:* You can find your station's ID by running this URL in your browser:
`https://v6.db.transport.rest/locations?query=YourCityName`
Look for the `"id"` field in the result.



---

## 📂 Project Structure

* `bot.py`: The main logic containing the Flask server, Telegram handlers, and API integration.
* `requirements.txt`: List of dependencies (`python-telegram-bot`, `flask`, `requests`).
* `.gitignore`: Ensures sensitive files and cache are not uploaded to GitHub.

---

## ⚠️ Disclaimer

This project is for educational and personal use only. It uses the public **Deutsche Bahn API (v6)** but is not affiliated with or endorsed by Deutsche Bahn. Please use responsibly to avoid API rate limiting.

---

**Created by Ravindu** | 2026
