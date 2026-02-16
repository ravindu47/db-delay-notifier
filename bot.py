import os
import logging
import requests
import datetime
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, Application

# --- CONFIGURATION ---
# Fetching sensitive keys from Environment Variables (Render/System)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- STATION CONSTANTS ---
# Specific Station IDs for the route
BAD_BIRNBACH = "8000858"  # Home
EGGENFELDEN = "8001716"   # Work
PFARRKIRCHEN = "8004746"  # Uni

# --- DIRECTION CONSTANTS ---
# Used to filter trains going in the wrong direction
DIR_MUHLDORF = "8000260" # Direction towards Work/Uni (West)
DIR_PASSAU = "8000298"   # Direction towards Home (East)

# --- LOGGING SETUP ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (Keep-Alive) ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 Smart Commute Bot (80/20 Logic) is Active!"

def run_web_server():
    """Runs a lightweight web server to keep Render active."""
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- HELPER FUNCTIONS ---

def get_germany_time():
    """Returns current UTC time adjusted to Germany (UTC+1)."""
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

def get_trains(station_id, direction_id):
    """
    Fetches departures from a specific station, filtering ONLY trains 
    heading towards a specific direction ID (Passau or Mühldorf).
    """
    try:
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?direction={direction_id}&duration=120&results=4"
        res = requests.get(url, timeout=15).json()
        return res.get('departures', [])
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

def format_train_msg(trains, origin_name):
    """Formats raw API data into a readable list string."""
    lines = []
    for t in trains:
        line = t.get('line', {}).get('name', 'Train')
        time_str = t.get('when', '')[11:16]
        delay = t.get('delay', 0)
        is_cancelled = t.get('cancelled', False)
        
        # Status Logic
        status = "🟢"
        if is_cancelled: status = "❌ Cancelled"
        elif delay >= 300: status = f"⚠️ +{int(delay/60)} min"
        
        lines.append(f"• `{time_str}` {origin_name}: **{line}** » {status}")
    return lines

# --- CORE LOGIC ---

async def send_schedule_report(context, chat_id, is_morning_mode, manual_request=False):
    """
    Generates and sends the schedule report.
    - is_morning_mode=True: Checks trains going TO Mühldorf (Work/Uni).
    - is_morning_mode=False: Checks trains going TO Passau (Home).
    """
    
    report_lines = []
    
    if is_morning_mode:
        mode_text = "☀️ **Going to Work/Uni** (Default)"
        opp_text = "🏠 Check Return Trip"
        # Logic: Check Bad Birnbach departures heading to Mühldorf
        trains = get_trains(BAD_BIRNBACH, DIR_MUHLDORF)
        report_lines.extend(format_train_msg(trains, "Bad Birnbach"))
        
    else:
        mode_text = "🌙 **Returning Home** (Default)"
        opp_text = "🏢 Check Work Trip"
        # Logic: Check Pfarrkirchen & Eggenfelden departures heading to Passau
        t1 = get_trains(PFARRKIRCHEN, DIR_PASSAU)
        t2 = get_trains(EGGENFELDEN, DIR_PASSAU)
        report_lines.extend(format_train_msg(t1, "Pfarrkirchen"))
        report_lines.extend(format_train_msg(t2, "Eggenfelden"))

    # If no trains found
    if not report_lines:
        if manual_request: 
            await context.bot.send_message(chat_id, "⚠️ No upcoming trains found for this route.")
        return

    # Sort and Deduplicate
    unique_lines = sorted(list(set(report_lines)))
    msg = f"{mode_text}\n\n" + "\n".join(unique_lines)
    
    # Interactive Button: Allows user to instantly check the OPPOSITE direction
    keyboard = [[InlineKeyboardButton(f"🔄 {opp_text}", callback_data="switch_check")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send Message
    try:
        await context.bot.send_message(chat_id, msg, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

async def check_commute(context: ContextTypes.DEFAULT_TYPE):
    """
    Scheduled Job: Checks time and decides which direction is 'Default' (80% Rule).
    Runs every 10 minutes.
    """
    now = get_germany_time()
    hour = now.hour
    
    # 80/20 Rule Implementation:
    # Before 18:00 (6 PM) -> Assume Morning/Work Mode (80% probability)
    # After 18:00 (6 PM)  -> Assume Evening/Home Mode (80% probability)
    is_morning = 4 <= hour < 18 
    
    # Only run for the Admin
    if ADMIN_ID != 0:
        # We pass manual_request=False to avoid spamming "No trains found" errors automatically
        await send_schedule_report(context, ADMIN_ID, is_morning, manual_request=False)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the 'Magic Button' click.
    Calculates the 'Opposite' of the current default mode and sends that report.
    """
    query = update.callback_query
    await query.answer("Checking opposite direction...") # Telegram feedback
    
    now = get_germany_time()
    hour = now.hour
    
    # Determine what the current 'Default' mode is
    current_default_is_morning = 4 <= hour < 18
    
    # The user wants the OPPOSITE of the default
    target_mode_is_morning = not current_default_is_morning 
    
    # Send the requested report manually
    await send_schedule_report(context, query.message.chat_id, target_mode_is_morning, manual_request=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    await update.message.reply_text(
        "👋 **Smart Commute Bot (Passau-Mühldorf Line) Active!**\n\n"
        "🕒 **Auto-Schedule:**\n"
        "☀️ Before 18:00: Shows trains to **Mühldorf** (Work/Uni)\n"
        "🌙 After 18:00: Shows trains to **Passau** (Home)\n\n"
        "💡 **Tip:** Use the button below any message to instantly check the *other* direction! (The 20% case)."
    )

if __name__ == '__main__':
    # Start Web Server for Render
    Thread(target=run_web_server, daemon=True).start()
    
    # Initialize Bot
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Job Queue
    if app.job_queue:
        # Check schedule every 10 minutes (600 seconds)
        app.job_queue.run_repeating(check_commute, interval=600, first=10)
    
    app.run_polling()
