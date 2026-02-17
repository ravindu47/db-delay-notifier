import os
import logging
import requests
import datetime
import psycopg2
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
DB_URL = os.environ.get("DATABASE_URL") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 Hybrid CommuteBot is Active!"

def run_web_server():
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- DATABASE FUNCTIONS ---
def get_db_connection():
    return psycopg2.connect(DB_URL, connect_timeout=10)

def upsert_user(chat_id, home_id=None, home_name=None, work_id=None, work_name=None, uni_id=None, uni_name=None, shift_type=None, start_hour=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (chat_id,))
        
        if home_id: cur.execute("UPDATE users SET home_id=%s, home_name=%s WHERE chat_id=%s", (home_id, home_name, chat_id))
        if work_id: cur.execute("UPDATE users SET work_id=%s, work_name=%s WHERE chat_id=%s", (work_id, work_name, chat_id))
        if uni_id:  cur.execute("UPDATE users SET uni_id=%s, uni_name=%s WHERE chat_id=%s", (uni_id, uni_name, chat_id))
        if shift_type: cur.execute("UPDATE users SET shift_type=%s WHERE chat_id=%s", (shift_type, chat_id))
        if start_hour is not None: cur.execute("UPDATE users SET start_hour=%s WHERE chat_id=%s", (start_hour, chat_id))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ DB Error: {e}")
        return False

def get_user(chat_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Fetching Uni details as well
        cur.execute("SELECT chat_id, home_id, home_name, work_id, work_name, uni_id, uni_name, shift_type, start_hour FROM users WHERE chat_id = %s", (chat_id,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    except: return None

def get_all_users():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT chat_id, home_id, home_name, work_id, work_name, uni_id, uni_name, shift_type, start_hour FROM users")
        users = cur.fetchall()
        cur.close()
        conn.close()
        return users
    except: return []

# --- API & FORMATTING ---
def get_journey(from_id, to_id):
    try:
        url = f"https://v6.db.transport.rest/journeys?from={from_id}&to={to_id}&results=1&transfers=1"
        return requests.get(url, timeout=15).json().get('journeys', [])
    except: return []

def format_route_status(journeys, label):
    """Generates a detailed status message for a specific route (Uni or Work)"""
    if not journeys:
        return f"📍 **{label}:** ⚠️ No connection found."

    j = journeys[0] # Take the next immediate connection
    legs = j.get('legs', [])
    dep = legs[0].get('departure', '')[11:16]
    arr = legs[-1].get('arrival', '')[11:16]
    
    # Analyze Delays
    max_delay = max((leg.get('departureDelay', 0) or 0) for leg in legs)
    is_cancelled = any(leg.get('cancelled') for leg in legs)
    plat_change = any(leg.get('plannedPlatform') != leg.get('platform') for leg in legs)
    
    # Status Header
    if is_cancelled:
        status = "❌ **CANCELLED**"
    elif max_delay > 60:
        status = f"⚠️ **Delay +{int(max_delay/60)} min**"
    else:
        status = "✅ **No Delays**"

    # Build details
    details = []
    if plat_change:
        real_plat = legs[0].get('platform')
        details.append(f"📢 **Change to Gl. {real_plat}!**")
    
    route_str = " ➔ ".join([l.get('line', {}).get('name', 'Train') for l in legs])
    
    return (
        f"📍 **{label}** ({dep} - {arr})\n"
        f"Status: {status}\n"
        f"🚆 {route_str}\n" + "\n".join(details)
    )

# --- LOGIC ENGINE ---
async def get_commute_plan(user):
    """Determines where the user is going based on 80/20 & Manual Mode"""
    _, h_id, h_name, w_id, w_name, u_id, u_name, s_type, start_hour = user
    
    if not h_id: return None, "Please set Home first."
    if not w_id and not u_id: return None, "Please set Work or Uni first."

    # Default Start Hour if not set
    if start_hour is None: start_hour = 8 

    # 1. Determine Time Window (Morning vs Evening)
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    hour = now.hour
    
    # Morning is defined as: [Start Time - 2h] to [Start Time + 6h]
    morning_start = (start_hour - 2) % 24
    morning_end = (start_hour + 6) % 24
    
    # Handle midnight wrap logic
    if morning_start < morning_end:
        is_morning = morning_start <= hour < morning_end
    else:
        is_morning = hour >= morning_start or hour < morning_end
    
    # 2. Apply Shift Mode (Manual Override)
    # Day Shift: Morning=To Dest, Evening=To Home
    # Night Shift: Morning=To Home, Evening=To Dest
    going_to_dest = is_morning if s_type == 'day' else not is_morning
    
    routes_to_check = []
    
    if going_to_dest:
        # Going TO Work/Uni
        if w_id: routes_to_check.append({"label": "To Work", "from": h_id, "to": w_id})
        if u_id: routes_to_check.append({"label": "To Uni", "from": h_id, "to": u_id})
        header = "🌅 **Morning Commute**"
    else:
        # Returning TO Home
        if w_id: routes_to_check.append({"label": "From Work", "from": w_id, "to": h_id})
        if u_id: routes_to_check.append({"label": "From Uni", "from": u_id, "to": h_id})
        header = "🌙 **Evening Return**"

    return routes_to_check, header

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    upsert_user(chat_id)
    await update.message.reply_text(
        "👋 **Welcome to Hybrid CommuteBot!**\n\n"
        "I track both your Uni and Work schedules.\n\n"
        "🛠️ **Setup Commands:**\n"
        "1️⃣ `/sethome <name>` - Set Home Station\n"
        "2️⃣ `/setwork <name>` - Set Work Station\n"
        "3️⃣ `/setuni <name>` - Set Uni Station\n"
        "4️⃣ `/time <hour>` - Set Start Time (e.g., `/time 8` or `/time 14`)\n\n"
        "⚙️ **Controls:**\n"
        "• `/mode` - Toggle Day/Night shift\n"
        "• `/check` - Check Status (Shows Work, Uni, or Both!)"
    )

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User types time directly: /time 9"""
    chat_id = update.message.chat_id
    try:
        time_input = int(context.args[0])
        if 0 <= time_input <= 23:
            upsert_user(chat_id, start_hour=time_input)
            await update.message.reply_text(f"🕒 Start Time set to: **{time_input}:00**.\n(I'll switch routes automatically based on this).")
        else:
            await update.message.reply_text("❌ Please enter a number between 0 and 23.")
    except:
        await update.message.reply_text("⚠️ Usage: `/time 8` (for 8 AM) or `/time 14` (for 2 PM).")

async def toggle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    # Toggle logic
    user = get_user(chat_id)
    current_mode = user[7] if user and user[7] else 'day'
    new_mode = 'night' if current_mode == 'day' else 'day'
    
    upsert_user(chat_id, shift_type=new_mode)
    await update.message.reply_text(f"🔄 Mode switched to: **{new_mode.upper()} Shift**")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual Check - Shows detailed status even if No Delay"""
    chat_id = update.message.chat_id
    user = get_user(chat_id)
    if not user: 
        await update.message.reply_text("Please run `/start` first.")
        return

    routes, header = await get_commute_plan(user)
    if not routes:
        await update.message.reply_text(f"⚠️ {header}") # Error message
        return

    await update.message.reply_text(f"🔎 Checking schedules...")
    
    final_msg = [header]
    for route in routes:
        journeys = get_journey(route['from'], route['to'])
        status_msg = format_route_status(journeys, route['label'])
        final_msg.append(status_msg)
    
    await update.message.reply_text("\n\n".join(final_msg), parse_mode='Markdown')

async def check_all_users(context: ContextTypes.DEFAULT_TYPE):
    """Background Job - Alerts ONLY if issues exist"""
    users = get_all_users()
    for user_data in users:
        chat_id = user_data[0]
        routes, header = await get_commute_plan(user_data)
        
        if not routes: continue # Skip if setup incomplete

        alerts = []
        for route in routes:
            journeys = get_journey(route['from'], route['to'])
            if not journeys: continue
            
            # Check for issues (Delay > 5m, Cancelled, Platform Change)
            j = journeys[0]
            legs = j.get('legs', [])
            max_delay = max((leg.get('departureDelay', 0) or 0) for leg in legs)
            is_cancelled = any(leg.get('cancelled') for leg in legs)
            plat_change = any(leg.get('plannedPlatform') != leg.get('platform') for leg in legs)

            if max_delay > 300 or is_cancelled or plat_change:
                status_msg = format_route_status(journeys, route['label'])
                alerts.append(status_msg)
        
        if alerts:
            await context.bot.send_message(chat_id, f"🔔 **Alert**\n\n" + "\n\n".join(alerts), parse_mode='Markdown')

# --- STATION SEARCH HANDLER ---
async def search_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: `/sethome <name>`, `/setwork <name>`, or `/setuni <name>`")
        return

    url = f"https://v6.db.transport.rest/locations?query={query}&results=3"
    results = requests.get(url).json()
    if not results:
        await update.message.reply_text("❌ Station not found.")
        return

    command = update.message.text.split()[0][1:] # sethome, setwork, setuni
    buttons = [[InlineKeyboardButton(s['name'], callback_data=f"{command}:{s['id']}:{s['name']}")] for s in results]
    await update.message.reply_text(f"🔍 Select Station:", reply_markup=InlineKeyboardMarkup(buttons))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(':')
    chat_id = query.message.chat_id
    cmd, s_id, s_name = data[0], data[1], data[2]
    
    if cmd == "sethome": upsert_user(chat_id, home_id=s_id, home_name=s_name)
    elif cmd == "setwork": upsert_user(chat_id, work_id=s_id, work_name=s_name)
    elif cmd == "setuni": upsert_user(chat_id, uni_id=s_id, uni_name=s_name)
    
    await query.edit_message_text(f"✅ **{cmd.replace('set', '').capitalize()}** Station set to: **{s_name}**")

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('sethome', search_station))
    app.add_handler(CommandHandler('setwork', search_station))
    app.add_handler(CommandHandler('setuni', search_station)) # New Command
    app.add_handler(CommandHandler('time', set_time)) # New Type-in Time
    app.add_handler(CommandHandler('mode', toggle_mode)) # Manual Mode Toggle
    app.add_handler(CommandHandler('check', check_command))
    
    # Callback
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Job Queue
    if app.job_queue:
        app.job_queue.run_repeating(check_all_users, interval=900, first=10)
    
    app.run_polling()
