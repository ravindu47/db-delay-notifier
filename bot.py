import os
import logging
import requests
import datetime
import psycopg2
import time
import random
from flask import Flask
from threading import Thread
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, Application

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
DB_URL = os.environ.get("DATABASE_URL") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Stability Optimized Mirrors: OEBB is currently more stable for German data
API_URLS = [
    "https://v6.oebb.transport.rest",
    "https://v6.db.transport.rest",
    "https://v5.db.transport.rest"
]

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 Hybrid CommuteBot Pro (v2.1 Stable) is Active!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- ENHANCED FAILOVER API CALLER ---
def call_db_api(endpoint):
    # Profile dbweb works best for new backends
    sep = "&" if "?" in endpoint else "?"
    final_endpoint = f"{endpoint}{sep}profile=dbweb"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }

    for base_url in API_URLS:
        try:
            url = f"{base_url}{final_endpoint}"
            # Anti-bot detection delay
            time.sleep(random.uniform(1.5, 3.0))
            
            response = requests.get(url, headers=headers, timeout=30) 
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logger.warning(f"Rate limited (429) by {base_url}. Cooling down...")
                time.sleep(15)
            else:
                logger.warning(f"Mirror {base_url} status {response.status_code}. Skipping...")
        except Exception as e:
            logger.warning(f"Mirror {base_url} failed: {e}")
    return None

# --- DATABASE FUNCTIONS ---
def get_db_connection():
    return psycopg2.connect(DB_URL, connect_timeout=15)

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
    endpoint = f"/journeys?from={from_id}&to={to_id}&results=1&transfers=1"
    data = call_db_api(endpoint)
    return data.get('journeys', []) if data else None

def format_route_status(journeys, label):
    if journeys is None: return f"📍 *{label}:* ⚠️ API Temporary Unavailable."
    if not journeys: return f"📍 *{label}:* ⚠️ No train found for this time."
    j = journeys[0]
    legs = j.get('legs', [])
    dep = legs[0].get('departure', '')[11:16]
    arr = legs[-1].get('arrival', '')[11:16]
    
    max_delay = max((leg.get('departureDelay', 0) or 0) for leg in legs)
    is_cancelled = any(leg.get('cancelled') for leg in legs)
    
    if is_cancelled: status = "❌ *CANCELLED*"
    elif max_delay > 60: status = f"⚠️ *Delay +{int(max_delay/60)} min*"
    else: status = "✅ *On Time*"

    plat = legs[0].get('platform', 'N/A')
    route_str = " ➔ ".join([l.get('line', {}).get('name', 'Train') for l in legs])
    return f"📍 *{label}* ({dep} - {arr})\nStatus: {status}\n🚆 {route_str} (Plat. {plat})"

# --- LOGIC ENGINE ---
async def get_commute_plan(user):
    _, h_id, h_name, w_id, w_name, u_id, u_name, s_type, start_hour = user
    if not h_id: return None, "Please set Home station."
    if not w_id and not u_id: return None, "Please set Work/Uni station."
    
    start_hour = start_hour if start_hour is not None else 8
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    hour = now.hour
    
    # Morning window logic
    m_start, m_end = (start_hour - 2) % 24, (start_hour + 6) % 24
    is_morning = m_start <= hour < m_end if m_start < m_end else hour >= m_start or hour < m_end
    
    going_to_dest = is_morning if s_type == 'day' else not is_morning
    routes = []
    
    if going_to_dest:
        if w_id: routes.append({"label": "To Work", "from": h_id, "to": w_id})
        if u_id: routes.append({"label": "To Uni", "from": h_id, "to": u_id})
        header = "🌅 *Morning Commute Update*"
    else:
        dest_id = w_id or u_id
        label = "Return Home (Work)" if w_id else "Return Home (Uni)"
        routes.append({"label": label, "from": dest_id, "to": h_id})
        header = "🌙 *Evening Return Update*"
    return routes, header

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.message.chat_id)
    await update.message.reply_text(
        "👋 *CommuteBot Pro Online*\n\n"
        "Configured with stability patches and backup mirrors.\n"
        "Commands: /sethome, /setwork, /setuni, /check, /time, /mode",
        parse_mode='Markdown'
    )

async def search_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    cmd = update.message.text.split()[0][1:]
    if not query:
        await update.message.reply_text(f"⚠️ Usage: `/{cmd} Pfarrkirchen`", parse_mode='Markdown')
        return

    endpoint = f"/locations?query={quote(query)}&results=3"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    res = call_db_api(endpoint)
    
    if not res:
        await update.message.reply_text("🛑 *API Error*\nServers are busy. Try again in a minute.", parse_mode='Markdown')
        return
            
    btns = [[InlineKeyboardButton(s['name'], callback_data=f"{cmd}:{s['id']}:{s['name']}")] for s in res if 'id' in s]
    await update.message.reply_text("🔍 *Select Station:*", reply_markup=InlineKeyboardMarkup(btns), parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.message.chat_id)
    if not user: return
    routes, header = await get_commute_plan(user)
    if not routes:
        await update.message.reply_text(f"⚠️ {header}", parse_mode='Markdown')
        return
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    final_msg = [header]
    for r in routes:
        status = format_route_status(get_journey(r['from'], r['to']), r['label'])
        final_msg.append(status)
    await update.message.reply_text("\n\n".join(final_msg), parse_mode='Markdown')

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        h = int(context.args[0])
        if 0 <= h <= 23:
            upsert_user(update.message.chat_id, start_hour=h)
            await update.message.reply_text(f"🕒 Commute start time set to: *{h}:00*.", parse_mode='Markdown')
        else: raise ValueError
    except: await update.message.reply_text("⚠️ Use: `/time 8` (24h format).", parse_mode='Markdown')

async def toggle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.message.chat_id)
    new_mode = 'night' if (user[7] if user else 'day') == 'day' else 'day'
    upsert_user(update.message.chat_id, shift_type=new_mode)
    await update.message.reply_text(f"🔄 Shift Mode: *{new_mode.upper()}*", parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cmd, sid, sname = q.data.split(':')
    if cmd == "sethome": upsert_user(q.message.chat_id, home_id=sid, home_name=sname)
    elif cmd == "setwork": upsert_user(q.message.chat_id, work_id=sid, work_name=sname)
    elif cmd == "setuni": upsert_user(q.message.chat_id, uni_id=sid, uni_name=sname)
    await q.edit_message_text(f"✅ *{cmd[3:].capitalize()}* set to: *{sname}*", parse_mode='Markdown')

# --- BACKGROUND MONITORING ---
async def check_all_users(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    for u in users:
        routes, _ = await get_commute_plan(u)
        if not routes: continue
        
        alerts = []
        for r in routes:
            js = get_journey(r['from'], r['to'])
            if not js: continue
            
            legs = js[0].get('legs', [])
            max_d = max((l.get('departureDelay', 0) or 0) for l in legs)
            is_cancelled = any(l.get('cancelled') for l in legs)
            
            # Send alert only for significant delay (>5m) or cancellation
            if is_cancelled or max_d > 300:
                alerts.append(format_route_status(js, r['label']))
            
            time.sleep(3) # Heavy delay between API hits

        if alerts:
            try:
                await context.bot.send_message(u[0], "🔔 *Travel Alert*\n\n" + "\n\n".join(alerts), parse_mode='Markdown')
            except: pass
        
        time.sleep(10) # Heavy delay between users

async def post_init(application: Application):
    if ADMIN_ID != 0:
        try: await application.bot.send_message(chat_id=ADMIN_ID, text="🚀 *System Online* (v2.1 Stable)")
        except: pass
    
    commands = [
        BotCommand("start", "Boot Bot"),
        BotCommand("check", "Manual Status Check"),
        BotCommand("sethome", "Set Home Station"),
        BotCommand("setwork", "Set Work Station"),
        BotCommand("setuni", "Set Uni Station"),
        BotCommand("time", "Set Commute Time"),
        BotCommand("mode", "Switch Day/Night Shift")
    ]
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('sethome', search_station))
    app.add_handler(CommandHandler('setwork', search_station))
    app.add_handler(CommandHandler('setuni', search_station))
    app.add_handler(CommandHandler('time', set_time))
    app.add_handler(CommandHandler('mode', toggle_mode))
    app.add_handler(CommandHandler('check', check_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    if app.job_queue: 
        # Check every 30 minutes to stay within limits
        app.job_queue.run_repeating(check_all_users, interval=1800, first=10)
    
    app.run_polling()
