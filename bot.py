import os
import logging
import requests
import datetime
import time
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, Application

# --- CONFIGURATION ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
ADMIN_ID = 1238096007  # <--- ඔයාගේ ID එක මෙතනට දැම්මා (Restart Alerts එන්නේ ඔයාට විතරයි)

# --- LOGGING SETUP ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (TO KEEP RENDER ALIVE) ---
server = Flask(__name__)
@server.route('/')
def index():
    return "🚆 DB Pro Bot is Running 24/7!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- GLOBAL VARIABLES ---
user_routes = {}
sent_alerts = {}
bot_state = {
    "sleeping": False, 
    "last_check": time.time()
}

# --- API FUNCTIONS ---
def get_station_data(name):
    """Search for a station by name."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://v6.db.transport.rest/locations?query={name}&results=1"
        response = requests.get(url, headers=headers, timeout=10)
        
        try:
            data = response.json()
        except ValueError:
            return None, None

        if data and isinstance(data, list) and len(data) > 0:
            return data[0]['id'], data[0]['name']
    except Exception as e:
        logger.error(f"Location API Error: {e}")
    return None, None

def get_delay_data(station_id):
    """Fetch departure data for the next 2 hours."""
    try:
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?duration=120&results=15"
        response = requests.get(url, timeout=15)
        try:
            return response.json().get('departures', [])
        except ValueError:
            return []
    except Exception as e:
        logger.error(f"Departure API Error: {e}")
    return []

def get_germany_time():
    """Get current time in Germany (Approx. UTC+1)."""
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Friendly welcome message for everyone."""
    await update.message.reply_text(
        "👋 **Hello! Welcome to DB Train Monitor.** 🚆\n\n"
        "I can help you track delays, cancellations, and crowd levels.\n"
        "To start, please send me your **START** station (e.g., Pfarrkirchen).", 
        parse_mode='Markdown'
    )
    context.user_data['step'] = 'start_station'

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send live tracking map link."""
    chat_id = update.message.chat_id
    if chat_id in user_routes:
        s_name = user_routes[chat_id]['start_name']
        link = "https://www.bahn.de/service/fahrplaene/live-tracking"
        await update.message.reply_text(f"📍 **Live Map for {s_name}:**\n[Click Here to View Map]({link})", parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ Please start monitoring first using /start")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle station names inputs."""
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    if step == 'start_station':
        await context.bot.send_chat_action(chat_id, action="typing")
        s_id, s_name = get_station_data(text)
        
        if not s_id:
            await update.message.reply_text("❌ Station not found. Please check the spelling and try again.")
            return

        context.user_data['start_id'] = s_id
        context.user_data['start_name'] = s_name
        await update.message.reply_text(f"✅ Start: *{s_name}*\nNow send the **END** station (e.g., Passau).", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': text, 
            'active': True
        }
        sent_alerts[chat_id] = set()
        await update.message.reply_text(
            f"🚀 **Monitoring Started!**\n\n"
            f"📍 Route: {context.user_data['start_name']} ➔ {text}\n"
            f"ℹ️ Use /link for live map.\n"
            f"💤 _Bot sleeps 01:00-06:00 to save energy._", 
            parse_mode='Markdown'
        )
        context.user_data['step'] = None

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    """Background task to check for delays/cancellations."""
    
    # --- 1. SYSTEM MONITOR (CRON JOB CHECK) ---
    current_time = time.time()
    time_diff = current_time - bot_state["last_check"]
    
    # If checked more than 5 mins ago (300s), send alert to ADMIN only
    if time_diff > 300 and not bot_state["sleeping"]:
        try:
            msg = f"⚠️ **System Alert:** Monitor paused for {int(time_diff/60)} mins (Server Lag/Restart). Resuming now."
            await context.bot.send_message(ADMIN_ID, msg, parse_mode='Markdown')
        except: pass
    
    bot_state["last_check"] = current_time

    # --- 2. SLEEP MODE LOGIC ---
    now = get_germany_time()
    if 1 <= now.hour < 6: # Sleep between 01:00 and 06:00
        if not bot_state["sleeping"]:
            bot_state["sleeping"] = True
            for chat_id in user_routes:
                await context.bot.send_message(chat_id, "😴 **Goodnight!** Monitoring paused until 06:00.", parse_mode='Markdown')
        return

    if bot_state["sleeping"]: # Wake up at 06:00
        bot_state["sleeping"] = False
        for chat_id in user_routes:
            await context.bot.send_message(chat_id, "☀️ **Good Morning!** Resuming train monitoring...", parse_mode='Markdown')

    # --- 3. TRAIN DATA CHECK ---
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        departures = get_delay_data(route['start_id'])
        
        for dep in departures:
            trip_id = dep.get('tripId', dep.get('when'))
            is_cancelled = dep.get('cancelled', False)
            delay = dep.get('delay', 0)
            
            # Create a unique key for this specific state of the train
            alert_key = f"{trip_id}_{is_cancelled}_{delay}"
            
            # If we already sent this exact alert, skip it
            if alert_key in sent_alerts.get(chat_id, set()): continue

            line_name = dep.get('line', {}).get('name', 'Train')
            time_str = dep.get('when', '')[11:16]
            platform = dep.get('platform', 'N/A')
            
            # Load Factor (Crowd Level)
            load = dep.get('loadFactor', '')
            crowd = "🟢 Low" if load == 'low' else "🟡 Med" if load == 'medium' else "🔴 High" if load in ['high', 'very-high'] else "⚪ N/A"

            msg = ""
            if is_cancelled:
                msg = (f"❌ *CANCELLATION ALERT*\n\n"
                       f"🚆 Train: {line_name}\n"
                       f"🕒 Time: {time_str}\n"
                       f"⚠️ Status: **CANCELLED (Fällt aus)**\n"
                       f"📍 Station: {route['start_name']}")
            
            elif delay and delay >= 300: # Delay > 5 mins
                msg = (f"⚠️ *DELAY ALERT*\n\n"
                       f"🚆 Train: {line_name}\n"
                       f"🕒 Time: {time_str}\n"
                       f"⏳ Delay: +{int(delay/60)} mins\n"
                       f"🚉 Platform: {platform}\n"
                       f"👥 Crowd: {crowd}\n"
                       f"📍 Station: {route['start_name']}")
            
            if msg:
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                if chat_id not in sent_alerts: sent_alerts[chat_id] = set()
                sent_alerts[chat_id].add(alert_key)

# --- RESTART ALERT (ADMIN ONLY) ---
async def post_init(application: Application):
    """Notify Admin when bot restarts."""
    try:
        await application.bot.send_message(
            chat_id=ADMIN_ID, 
            text="🤖 **System Restarted!**\n\nI am back online and monitoring.", 
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send restart alert: {e}")

if __name__ == '__main__':
    # Start Flask Server in background
    Thread(target=run_web_server, daemon=True).start()
    
    # Initialize Bot
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    # Add Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('link', get_link))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # Start Background Job (Checks every 2 mins)
    if application.job_queue:
        application.job_queue.run_repeating(check_updates, interval=120, first=10)
    
    application.run_polling()
