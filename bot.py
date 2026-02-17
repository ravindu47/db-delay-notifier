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
DB_URL = os.environ.get("DATABASE_URL") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (Keep-Alive for Render) ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 SaaS Commute Bot is Running!"

def run_web_server():
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# --- DATABASE FUNCTIONS ---
def get_db_connection():
    return psycopg2.connect(DB_URL)

def upsert_user(chat_id, home_id=None, home_name=None, work_id=None, work_name=None, shift_type=None):
    """Saves or Updates user data (Overwrite mode) to ensure persistence"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (chat_id,))
        if home_id:
            cur.execute("UPDATE users SET home_id=%s, home_name=%s WHERE chat_id=%s", (home_id, home_name, chat_id))
        if work_id:
            cur.execute("UPDATE users SET work_id=%s, work_name=%s WHERE chat_id=%s", (work_id, work_name, chat_id))
        if shift_type:
            cur.execute("UPDATE users SET shift_type=%s WHERE chat_id=%s", (shift_type, chat_id))
        conn.commit()
    except Exception as e:
        logger.error(f"DB Upsert Error: {e}")
    finally:
        cur.close()
        conn.close()

def get_all_users():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, home_id, home_name, work_id, work_name, shift_type FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users

# --- API FUNCTIONS (JOURNEYS) ---
def get_journey(from_id, to_id):
    """Fetches complex connections including transfers and waiting times"""
    try:
        url = f"https://v6.db.transport.rest/journeys?from={from_id}&to={to_id}&results=2&transfers=1"
        return requests.get(url, timeout=15).json().get('journeys', [])
    except Exception as e:
        logger.error(f"API Journey Error: {e}")
        return []

def format_journey_msg(journeys):
    if not journeys: return ["⚠️ No upcoming connections found."]
    
    msgs = []
    for j in journeys:
        legs = j.get('legs', [])
        first_leg = legs[0]
        last_leg = legs[-1]
        
        dep_time = first_leg.get('departure', '')[11:16]
        arr_time = last_leg.get('arrival', '')[11:16]
        
        is_cancelled = False
        max_delay = 0
        platform_alert = ""
        route_path = []
        
        for leg in legs:
            if leg.get('cancelled'): is_cancelled = True
            delay = leg.get('departureDelay', 0)
            if delay and delay > max_delay: max_delay = delay
            
            # Platform Change Detection
            planned = leg.get('plannedPlatform')
            actual = leg.get('platform')
            if planned and actual and planned != actual:
                platform_alert = f"\n📢 *PLATFORM CHANGE:* Now at Gl. {actual}"
            
            line = leg.get('line', {}).get('name', 'Train/Bus')
            route_path.append(line)

        status = "🟢 On Time"
        if is_cancelled: status = "❌ *CANCELLED*"
        elif max_delay >= 300: status = f"⚠️ *+{int(max_delay/60)} min delay*"
        
        transfer_text = ""
        if len(legs) > 1:
            transfer_station = legs[0].get('destination', {}).get('name', 'Transfer point')
            transfer_text = f"\n🔄 Change at: {transfer_station}"

        msgs.append(f"⏰ `{dep_time}` ➔ `{arr_time}`\n🚆 {' ➔ '.join(route_path)}\nResult: {status}{platform_alert}{transfer_text}")
        
    return msgs

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    upsert_user(chat_id)
    
    welcome_text = (
        "👋 **Welcome to CommuteBot Pro!**\n\n"
        "I am your personal rail assistant. I monitor your specific commute so you don't have to check the app manually.\n\n"
        "🛡️ **Why trust me?**\n"
        "• **Direct DB Data:** Real-time Deutsche Bahn API access.\n"
        "• **Smart 80/20 Rule:** I auto-switch between work and home routes based on time.\n"
        "• **Connection Aware:** I track transfers and waiting times.\n"
        "• **Instant Alerts:** Notifications for delays, cancellations, or platform changes.\n\n"
        "🚀 **Quick Setup:**\n"
        "1️⃣ `/sethome <station>` - Set your Home (e.g., Bad Birnbach)\n"
        "2️⃣ `/setwork <station>` - Set your Work/Uni (e.g., Pfarrkirchen)\n"
        "3️⃣ `/mode` - Toggle Day/Night shift logic\n"
        "4️⃣ `/check` - Get an instant manual status"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def set_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: `/sethome <station_name>`")
        return

    url = f"https://v6.db.transport.rest/locations?query={query}&results=3"
    results = requests.get(url).json()
    
    if not results:
        await update.message.reply_text("❌ Station not found.")
        return

    command = update.message.text.split()[0][1:] 
    buttons = [[InlineKeyboardButton(s['name'], callback_data=f"{command}:{s['id']}:{s['name']}")] for s in results]
    await update.message.reply_text(f"🔍 Select your station:", reply_markup=InlineKeyboardMarkup(buttons))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cmd, s_id, s_name = query.data.split(':')
    
    if cmd == "sethome":
        upsert_user(query.message.chat_id, home_id=s_id, home_name=s_name)
        await query.edit_message_text(f"🏠 **Home Set:** {s_name}")
    elif cmd == "setwork":
        upsert_user(query.message.chat_id, work_id=s_id, work_name=s_name)
        await query.edit_message_text(f"🏢 **Work Set:** {s_name}")

async def toggle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    mode = "night" if context.args and context.args[0] == "night" else "day"
    upsert_user(chat_id, shift_type=mode)
    await update.message.reply_text(f"🔄 **Shift Mode:** {mode.upper()}")

async def check_all_users(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    hour = now.hour

    for user in users:
        chat_id, h_id, h_name, w_id, w_name, s_type = user
        if not h_id or not w_id: continue

        # 80/20 Prediction Logic
        is_morning = 4 <= hour < 14
        is_work_trip = is_morning if s_type == 'day' else not is_morning
        
        start_id, end_id = (h_id, w_id) if is_work_trip else (w_id, h_id)
        mode_label = "☀️ Morning Commute" if is_work_trip else "🌙 Evening Return"

        journeys = get_journey(start_id, end_id)
        report = format_journey_msg(journeys)
        
        msg = f"🔔 **{mode_label}**\n\n" + "\n\n".join(report)
        try:
            await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
        except: pass

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('sethome', set_station))
    app.add_handler(CommandHandler('setwork', set_station))
    app.add_handler(CommandHandler('mode', toggle_mode))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    if app.job_queue:
        app.job_queue.run_repeating(check_all_users, interval=900, first=10)
    
    app.run_polling()
