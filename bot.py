import os
import logging
import requests
import datetime
import time
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, Application

# --- CONFIGURATION ---
# Getting sensitive data from Environment Variables for security
# If running locally, make sure to set these variables or replace with actual values temporarily
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) 

# Default User Configuration (Auto-Resume)
# This ensures the bot automatically monitors "Bad Birnbach" for the Admin upon restart.
# Station ID for Bad Birnbach: 8000858
PERMANENT_USERS = {
    ADMIN_ID: "8000858", 
}

# --- LOGGING SETUP ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (TO KEEP RENDER ALIVE) ---
server = Flask(__name__)

@server.route('/')
def index():
    return "🚆 DB Train Monitor Bot is Running Securely!"

def run_web_server():
    """Runs a simple Flask server to prevent Render form putting the app to sleep immediately."""
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- GLOBAL VARIABLES ---
user_routes = {}   # Stores active monitoring routes
sent_alerts = {}   # Stores sent alert keys to prevent duplicates
bot_state = {
    "sleeping": False, 
    "last_check": time.time()
}

# --- API HELPER FUNCTIONS ---

def get_station_suggestions(name):
    """
    Searches for stations using the DB API.
    Returns a list of dictionaries with station ID and Name.
    """
    try:
        # Fetch up to 5 results for fuzzy matching
        url = f"https://v6.db.transport.rest/locations?query={name}&results=5"
        res = requests.get(url, timeout=10)
        data = res.json()
        
        suggestions = []
        for item in data:
            if item.get('type') in ['stop', 'station']:
                suggestions.append({'id': item['id'], 'name': item['name']})
        return suggestions
    except Exception as e:
        logger.error(f"Station Search API Error: {e}")
        return []

def get_delay_data(station_id):
    """
    Fetches departure data for a specific station for the next 2 hours.
    """
    try:
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?duration=120&results=15"
        res = requests.get(url, timeout=15)
        return res.json().get('departures', [])
    except Exception as e:
        logger.error(f"Departure API Error: {e}")
        return []

def get_germany_time():
    """
    Returns the current time adjusted to UTC+1 (Approx. Germany Time).
    """
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and instructions."""
    await update.message.reply_text(
        "👋 **Hello! Welcome to DB Train Monitor.**\n\n"
        "I am currently monitoring **Bad Birnbach** automatically.\n"
        "To change the station, simply type the name (e.g., `Eggenfelden`).\n"
        "I will provide buttons if multiple stations are found.", 
        parse_mode='Markdown'
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles user text input to search for stations.
    If multiple stations are found, it displays inline buttons.
    """
    text = update.message.text
    chat_id = update.message.chat_id
    
    await context.bot.send_chat_action(chat_id, action="typing")
    
    # Search for stations
    suggestions = get_station_suggestions(text)

    if not suggestions:
        await update.message.reply_text("❌ Station not found. Please check the spelling.")
        return

    # If only 1 result found, set it immediately
    if len(suggestions) == 1:
        s = suggestions[0]
        user_routes[chat_id] = {'start_id': s['id'], 'start_name': s['name'], 'active': True}
        sent_alerts[chat_id] = set()
        await update.message.reply_text(f"✅ Monitoring set to: *{s['name']}*", parse_mode='Markdown')
        return

    # If multiple results, create buttons
    keyboard = []
    for s in suggestions:
        # Callback data format: "set:STATION_ID:STATION_NAME"
        keyboard.append([InlineKeyboardButton(s['name'], callback_data=f"set:{s['id']}:{s['name']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🔍 Found {len(suggestions)} stations. Please select one:", 
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button clicks for station selection."""
    query = update.callback_query
    await query.answer() 
    
    # Parse data from the button
    data = query.data.split(':')
    s_id = data[1]
    s_name = data[2]
    chat_id = query.message.chat_id

    # Update user route
    user_routes[chat_id] = {'start_id': s_id, 'start_name': s_name, 'active': True}
    sent_alerts[chat_id] = set()
    
    await query.edit_message_text(
        text=f"✅ **Station Updated!**\nNow monitoring: *{s_name}*", 
        parse_mode='Markdown'
    )

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    """
    Background job to check for train updates.
    Runs every 2 minutes.
    """
    # Update last check time for system monitoring
    bot_state["last_check"] = time.time()
    
    now = get_germany_time()
    
    # --- SMART SLEEP MODE (01:00 - 06:00) ---
    if 1 <= now.hour < 6:
        if not bot_state["sleeping"]:
            bot_state["sleeping"] = True
            for cid in user_routes: 
                try: await context.bot.send_message(cid, "😴 **Goodnight!** Pausing alerts until 06:00.")
                except: pass
        return

    if bot_state["sleeping"]:
        bot_state["sleeping"] = False
        for cid in user_routes: 
            try: await context.bot.send_message(cid, "☀️ **Good Morning!** Resuming monitoring.")
            except: pass

    # --- TRAIN DATA PROCESSING ---
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        
        deps = get_delay_data(route['start_id'])
        
        for dep in deps:
            trip_id = dep.get('tripId', dep.get('when'))
            is_can = dep.get('cancelled', False)
            delay = dep.get('delay', 0)
            
            # Create unique alert key
            alert_key = f"{trip_id}_{is_can}_{delay}"
            
            # Skip if alert already sent
            if alert_key in sent_alerts.get(chat_id, set()): continue
            
            # Extract details
            line = dep.get('line', {}).get('name', 'Train')
            t = dep.get('when', '')[11:16]
            plat = dep.get('platform', 'N/A')
            load = dep.get('loadFactor', '')
            
            # Determine crowd level icon
            crowd = "🟢" if load == 'low' else "🟡" if load == 'medium' else "🔴" if load in ['high', 'very-high'] else "⚪"
            
            msg = ""
            if is_can:
                msg = (f"❌ *CANCELLATION ALERT*\n"
                       f"🚆 {line} ({t})\n"
                       f"⚠️ **CANCELLED**\n"
                       f"📍 {route['start_name']}")
            elif delay and delay >= 300: # Delay > 5 mins
                msg = (f"⚠️ *DELAY ALERT*\n"
                       f"🚆 {line} ({t})\n"
                       f"⏳ Delay: +{int(delay/60)} min\n"
                       f"🚉 Plat: {plat}\n"
                       f"👥 Load: {crowd}\n"
                       f"📍 {route['start_name']}")
            
            if msg:
                try:
                    await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
                    # Update history to prevent spam
                    if chat_id not in sent_alerts: sent_alerts[chat_id] = set()
                    sent_alerts[chat_id].add(alert_key)
                except Exception as e:
                    logger.error(f"Failed to send alert: {e}")

async def post_init(application: Application):
    """
    Runs immediately after bot startup.
    Handles Auto-Resume and Admin Notification.
    """
    # Auto-Resume Logic for Permanent Users
    for chat_id, s_id in PERMANENT_USERS.items():
        if chat_id != 0: # Ensure valid ID
            user_routes[chat_id] = {
                'start_id': s_id, 
                'start_name': "Bad Birnbach (Auto)", 
                'active': True
            }
            sent_alerts[chat_id] = set()
    
    # Notify Admin
    if ADMIN_ID != 0:
        try:
            await application.bot.send_message(
                ADMIN_ID, 
                "🤖 **System Online!**\nAuto-resume active. Waiting for updates.", 
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Admin Alert Error: {e}")

if __name__ == '__main__':
    # Start Flask Server in a separate thread
    Thread(target=run_web_server, daemon=True).start()
    
    # Initialize Telegram Bot
    if not TOKEN:
        logger.error("Error: TELEGRAM_TOKEN not found in environment variables.")
    else:
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
        
        # Add Handlers
        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
        app.add_handler(CallbackQueryHandler(button_callback))
        
        # Start Job Queue (Runs check_updates every 120 seconds)
        if app.job_queue:
            app.job_queue.run_repeating(check_updates, interval=120, first=10)
        
        # Start Polling
        app.run_polling()
