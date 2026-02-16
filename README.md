# 🚆 Smart Commute Assistant (Passau-Mühldorf Line)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue)
![Status](https://img.shields.io/badge/Status-Active-success)

A highly customized, intelligent Telegram bot designed for commuters on the **Passau — Mühldorf** railway line. It uses the "80/20 Rule" to predict your travel direction based on the time of day, while offering a single-tap solution for off-schedule trips.

## 🌟 Key Features

### 🧠 Smart "80/20" Schedule Logic
The bot automatically switches its monitoring direction based on probable commute patterns:
* **☀️ Morning Mode (04:00 - 18:00):** Monitors departures from **Bad Birnbach** heading towards **Mühldorf** (Work/Uni).
* **🌙 Evening Mode (18:00 - 04:00):** Monitors departures from **Pfarrkirchen & Eggenfelden** heading towards **Passau** (Home).

### 🧭 Direction Filtering
Unlike standard bots, this system filters trains by their final destination.
* *Going to Work?* It hides trains going the wrong way (to Passau).
* *Going Home?* It hides trains going further away (to Mühldorf).

### 🔄 The "Magic Button" (20% Case)
Need to go home early? Or work a late shift?
Every automatic message includes a **Dynamic Button**. One tap instantly checks the *opposite* direction without needing to type commands.

### ⚡ Real-Time Alerts
* **Delays:** Alerts if a train is delayed by >5 minutes.
* **Cancellations:** Instant warnings for cancelled trips.
* **Platform Info:** Displays track numbers.

---

## 🛠️ Deployment Guide

This bot is optimized for **Render (Free Tier)** with a Cron-job to keep it awake.

### Prerequisites
1.  **Telegram Bot Token:** From [@BotFather](https://t.me/BotFather).
2.  **Admin ID:** Your Telegram User ID (from [@userinfobot](https://t.me/userinfobot)).

### Step 1: Deploy to Render
1.  Clone this repository.
2.  Create a new **Web Service** on Render.
3.  Set **Build Command:** `pip install -r requirements.txt`
4.  Set **Start Command:** `python bot.py`

### Step 2: Environment Variables
Go to the "Environment" tab in Render and add:
* `TELEGRAM_TOKEN`: (Your Bot Token)
* `ADMIN_ID`: (Your User ID)

### Step 3: Keep-Alive (Cron Job)
To prevent the free tier from sleeping:
1.  Register on [cron-job.org](https://cron-job.org).
2.  Create a job to ping your Render URL (e.g., `https://your-bot.onrender.com/`) every **5 minutes**.

---

## 📂 Project Structure

* `bot.py`: Main application logic with Flask server and Telegram handlers.
* `requirements.txt`: Dependencies (`python-telegram-bot`, `flask`, `requests`).

---

## ⚠️ Disclaimer
This project uses the public **Deutsche Bahn API (v6)**. It is a personal project and is not affiliated with Deutsche Bahn AG.

---
**Author:** Ravindu
