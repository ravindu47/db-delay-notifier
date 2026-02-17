import os
import logging
import requests
import datetime
import psycopg2
from flask import Flask
from threading import Thread
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, Application

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
def index(): return "🚆 Hybrid CommuteBot Pro is Active!"

def run_web_server():
    # Attempting to bind to the correct port for Render
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- DATABASE FUNCTIONS ---
def get_db_connection():
    # Use Pooler Port 6543 for stability
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
    if not journeys: return f"📍 **{label}:** ⚠️ No connection found."
    j = journeys[0]
    legs = j.get('legs', [])
    dep = legs[0].get('departure', '')[11:16]
    arr = legs[-1].get('arrival', '')[11:16]
    max_delay = max((leg.get('departureDelay', 0) or 0) for leg in legs)
    is_cancelled = any(leg.get('cancelled') for leg in legs)
    
    if is_cancelled: status = "❌ **CANCELLED**"
    elif max_delay > 60: status = f"⚠️ **Delay +{int(max_delay/60)} min**"
    else: status = "✅ **No Delays**"

    plat = legs[0].get('platform')
    route_str = " ➔ ".join([l.get('line', {}).get('name', 'Train') for l in legs])
    return f"📍 **{label}** ({dep} - {arr})\nStatus: {status}\n🚆 {route_str} (Gl. {plat})"

# --- LOGIC ENGINE ---
async def get_commute_plan(user):
    _, h_id, h_name, w_id, w_name, u_id, u_name, s_type, start_hour = user
    if not h_id: return None, "Please set Home station first."
    if not w_id and not u_id: return None, "Please set Work or Uni station."
    
    start_hour = start_hour if start_hour is not None else 8
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    hour = now.hour
    
    morning_start, morning_end = (start_hour - 2) % 24, (start_hour + 6) % 24
    is_morning = morning_start <= hour < morning_end if morning_start < morning_end else hour >= morning_start or hour < morning_end
    
    going_to_dest = is_morning if s_type == 'day' else not is_morning
    routes = []
    if going_to_dest:
        if w_id: routes.append({"label": "To Work", "from": h_id, "to": w_id})
        if u_id: routes.append({"label": "To Uni", "from": h_id, "to": u_id})
        header = "🌅 **Morning Commute**"
    else:
        if w_id: routes.append({"label": "Return Home (Work)", "from": w_id, "to": h_id})
        if u_id: routes.append({"label": "Return Home (Uni)", "from": u_id, "to": h_id})
        header = "🌙 **Evening Return**"
    return routes, header

# --- HANDLERS ---

async def post_init(application: Application):
    """
    FIX: This runs AFTER the event loop is created but BEFORE the bot starts polling.
    This prevents the 'RuntimeError: There is no current event loop' crash.
    """
    commands = [
        BotCommand("start", "Start the bot & register"),
        BotCommand("check", "Check next Work/Uni connection"),
        BotCommand("sethome", "Set your Home station"),
        BotCommand("setwork", "Set your Work station"),
        BotCommand("setuni", "Set your Uni station"),
        BotCommand("time", "Set Work Start Hour (e.g. /time 8)"),
        BotCommand("mode", "Toggle Day/Night Shift mode")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Menu commands set successfully via post_init!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    upsert_user(chat_id)
    await update.message.reply_text(
        "👋 **Welcome to Hybrid CommuteBot Pro!**\n\n"
        "I track both your Uni and Work schedules. Use the / menu to setup.\n\n"
        "🚀 **Setup:**\n"
        "1️⃣ `/sethome <name>`\n"
        "2️⃣ `/setwork <name>` and/or `/setuni <name>`\n"
        "3️⃣ `/time <hour>` (e.g., `/time 9` for 9 AM start)"
    )

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user = get_user(chat_id)
    if not user: return
    routes, header = await get_commute_plan(user)
    if not routes:
        await update.message.reply_text(f"⚠️ {header}")
        return
    final_msg = [header]
    for r in routes:
        final_msg.append(format_route_status(get_journey(r['from'], r['to']), r['label']))
    await update.message.reply_text("\n\n".join(final_msg), parse_mode='Markdown')

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        h = int(context.args[0])
        if 0 <= h <= 23:
            upsert_user(update.message.chat_id
