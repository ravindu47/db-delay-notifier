import os
import logging
import requests
import datetime
import psycopg2
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
# Supabase Database URL (Get this from Project Settings)
DB_URL = os.environ.get("DATABASE_URL") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (Keep-Alive) ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 SaaS Commute Bot with Database Active!"
def run_web_server():
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- DATABASE FUNCTIONS ---
def get_db_connection():
    return psycopg2.connect(DB_URL)

def upsert_user(chat_id, home_id=None, home_name=None, work_id=None, work_name=None, shift_type=None):
    """Saves or Updates user data without creating duplicates"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check if user exists
    cur.execute("SELECT * FROM users WHERE chat_id = %s", (chat_id,))
    exists = cur.fetchone()
    
    if not exists:
        cur.execute("INSERT INTO users (chat_id) VALUES (%s)", (chat_id,))
        conn.commit()

    # Dynamic Update
    if home_id:
        cur.execute("UPDATE users SET home_id=%s, home_name=%s WHERE chat_id=%s", (home_id, home_name, chat_id))
    if work_id:
        cur.execute("UPDATE users SET work_id=%s, work_name=%s WHERE chat_id=%s", (work_id, work_name, chat_id))
    if shift_type:
        cur.execute("UPDATE users SET shift_type=%s WHERE chat_id=%s", (shift_type, chat_id))
        
    conn.commit()
    cur.close()
    conn.close()

def get_all_users():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, home_id, home_name, work_id, work_name, shift_type FROM users")
    users = cur.fetchall()
    conn.close()
    return users # Returns list of tuples

# --- API FUNCTIONS (JOURNEYS) ---
def get_journey(from_id, to_id):
    """Fetches complex connections (Start -> Transfer -> End)"""
    try:
        # Using /journeys to support connections/transfers
        url = f"https://v6.db.transport.rest/journeys?from={from_id}&to={to_id}&results=3&transfers=1"
        return requests.get(url, timeout=15).json().get('journeys', [])
    except: return []

def format_journey_msg(journeys):
    if not journeys: return ["⚠️ No connection found."]
    
    msgs = []
    for j in journeys:
        legs = j.get('legs', [])
        first_leg = legs[0]
        last_leg = legs[-1]
        
        # Times
        dep_time = first_leg.get('departure', '')[11:16]
        arr_time = last_leg.get('arrival', '')[11:16]
        
        # Status logic
        is_cancelled = False
        max_delay = 0
        platform_changed = False
        
        route_details = []
        
        for leg in legs:
            if leg.get('cancelled'): is_cancelled = True
            delay = leg.get('departureDelay', 0)
            if delay and delay > max_delay: max_delay = delay
            
            # Platform Check
            planned_plat = leg.get('plannedPlatform')
            real_plat = leg.get('platform')
            if planned_plat and real_plat and planned_plat != real_plat:
                platform_changed = True
            
            line_name = leg.get('line', {}).get('name', 'Train')
            route_details.append(line_name)

        # Build Status String
        status = "🟢"
        if is_cancelled: status = "❌ CANCELLED"
        elif max_delay >= 300: status = f"⚠️ +{int(max_delay/60)} min"
        
        # Alerts
        alert_text = ""
        if platform_changed: alert_text += "\n📢 **PLATFORM CHANGE!** Check screens."
        if len(legs) > 1: alert_text += f"\n🔄 Change at {legs[0].get('destination', {}).get('name')}"

        msgs.append(f"⏰ `{dep_time}` - `{arr_time}`\n🚆 {' ➔ '.join(route_details)}\nResult: {status}{alert_text}\n")
        
    return msgs

# --- BOT LOGIC ---

async def check_commute_job(context: ContextTypes.DEFAULT_TYPE):
    """Global Loop: Checks trips for ALL users in DB"""
    try:
        users = get_all_users()
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return

    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    hour = now.hour

    for user in users:
        chat_id, home_id, home_name, work_id, work_name, shift_type = user
        
        if not home_id or not work_id: continue # Skip if setup incomplete

        # --- 80/20 & Shift Logic ---
        # If 'day' shift: Morning=Work, Evening=Home
        # If 'night' shift: Morning=Home, Evening=Work (Reverse)
        
        is_morning_time = 4 <= hour < 14
        is_going_to_work = is_morning_time if shift_type == 'day' else not is_morning_time
        
        if is_going_to_work:
            start_id, end_id = home_id, work_id
            mode = f"☀️ Going to Work ({work_name})"
        else:
            start_id, end_id = work_id, home_id
            mode = f"🌙 Returning Home ({home_name})"

        # Fetch Journey
        journeys = get_journey(start_id, end_id)
        report = format_journey_msg(journeys)
        
        msg = f"{mode}\n\n" + "\n".join(report)
        
        # (Optional: Add 'Wake Up' logic here based on time)
        
        try:
            # Only send if not duplicate (Simple logic for now)
            # For a real SaaS, we would compare with last sent message ID in DB
            await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
        except: pass

# --- SETUP CONVERSATION HANDLERS ---
# (Simplified: User sends location, we give buttons, they pick)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Welcome to CommuteBot Pro!**\n\n"
        "Let's set you up.\n"
        "1️⃣ Send `/sethome <Station Name>`\n"
        "2️⃣ Send `/setwork <Station Name>`\n"
        "3️⃣ Send `/mode` to toggle Day/Night shift."
    )
    # Ensure user exists in DB
    Thread(target=upsert_user, args=(update.message.chat_id,)).start()

async def search_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic function to search and show buttons"""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Please type a station name. Ex: `/sethome Pfarrkirchen`")
        return

    # API Search
    url = f"https://v6.db.transport.rest/locations?query={query}&results=3"
    results = requests.get(url).json()
    
    if not results:
        await update.message.reply_text("❌ Station not found.")
        return

    command = update.message.text.split()[0][1:] # 'sethome' or 'setwork'
    buttons = []
    for s in results:
        # callback: "sethome:12345:Name"
        data = f"{command}:{s['id']}:{s['name']}"
        buttons.append([InlineKeyboardButton(s['name'], callback_data=data)])
    
    await update.message.reply_text(f"🔍 Results for '{query}':", reply_markup=InlineKeyboardMarkup(buttons))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cmd, s_id, s_name = query.data.split(':')
    chat_id = query.message.chat_id
    
    if cmd == "sethome":
        upsert_user(chat_id, home_id=s_id, home_name=s_name)
        await query.edit_message_text(f"✅ Home set to: **{s_name}**")
    elif cmd == "setwork":
        upsert_user(chat_id, work_id=s_id, work_name=s_name)
        await query.edit_message_text(f"✅ Work set to: **{s_name}**")

async def toggle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    # Simple toggle logic (would need a DB fetch first ideally)
    # For now, let's force set to Night or Day via args
    # Usage: /mode night or /mode day
    mode = "day"
    if context.args and context.args[0].lower() == "night":
        mode = "night"
    
    upsert_user(chat_id, shift_type=mode)
    await update.message.reply_text(f"🔄 Shift mode set to: **{mode.upper()}**\n(Logic flipped for Day/Night)")

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('sethome', search_station))
    app.add_handler(CommandHandler('setwork', search_station))
    app.add_handler(CommandHandler('mode', toggle_mode))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    if app.job_queue:
        # Check every 15 mins (900s) to be safe with limits
        app.job_queue.run_repeating(check_commute_job, interval=900, first=10)
    
    app.run_polling()
