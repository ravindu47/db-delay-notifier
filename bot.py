import os
import logging
import requests
import datetime
import time
import asyncio
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, Application

# --- ඔයාගේ විස්තර මෙතනට දාන්න ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
ADMIN_ID = 1238096007  # <--- මෙතනට ඔයාගේ Chat ID එක දාන්න (නැත්නම් Restart Alert එන්නේ නෑ)

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (For Uptime) ---
server = Flask(__name__)
@server.route('/')
def index():
    return "🚆 DB Pro Bot is Running!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- GLOBAL VARS ---
user_routes = {}
sent_alerts = {}
bot_state = {"sleeping": False, "last_check": time.time()}

# --- API FUNCTIONS (Improved Error Handling) ---
def get_station_data(name):
    try:
        # දෝෂ මගහරවා ගැනීමට headers භාවිතය
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://v6.db.transport.rest/locations?query={name}&results=1"
        response = requests.get(url, headers=headers, timeout=10)
        
        # පිළිතුර JSON දැයි පරීක්ෂා කිරීම
        try:
            data = response.json()
        except ValueError:
            logger.error("API returned non-JSON response.")
            return None, None

        if data and isinstance(data, list) and len(data) > 0:
            return data[0]['id'], data[0]['name']
    except Exception as e:
        logger.error(f"Location API Error: {e}")
    return None, None

def get_delay_data(station_id):
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
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    await update.message.reply_text(
        f"👋 **Hello!**\nYour Chat ID is: `{user_id}`\n(Copy this to the code if you haven't yet!)\n\n"
        "Send me your **START** station (e.g., Pfarrkirchen).", 
        parse_mode='Markdown'
    )
    context.user_data['step'] = 'start_station'

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in user_routes:
        s_name = user_routes[chat_id]['start_name']
        link = "https://www.bahn.de/service/fahrplaene/live-tracking"
        await update.message.reply_text(f"📍 **Live Map for {s_name}:**\n[Click Here]({link})", parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ Please start monitoring first.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    if step == 'start_station':
        await context.bot.send_chat_action(chat_id, action="typing")
        s_id, s_name = get_station_data(text)
        
        if not s_id:
            await update.message.reply_text("❌ Station not found or API busy.\nPlease check the spelling (e.g. 'Pfarrkirchen') and try again.")
            return

        context.user_data['start_id'] = s_id
        context.user_data['start_name'] = s_name
        await update.message.reply_text(f"✅ Start: *{s_name}*\nNow send the **END** station.", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': text, 
            'active': True
        }
        sent_alerts[chat_id] = set()
        await update.message.reply_text(f"🚀 **Monitoring Started!**\nroute: {context.user_data['start_name']} ➔ {text}", parse_mode='Markdown')
        context.user_data['step'] = None

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    # --- CRON JOB / LAG MONITOR ---
    # Bot එක නිදාගෙන නැගිට්ටා නම් හෝ Cron job පරක්කු වුණා නම් දැනුම් දීම
    current_time = time.time()
    time_diff = current_time - bot_state["last_check"]
    
    # විනාඩි 5කට වඩා (300s) පරක්කු නම්, ඒ කියන්නේ Cron job මිස් වෙලා හෝ Server sleep වෙලා
    if time_diff > 300 and not bot_state["sleeping"]:
        try:
            if ADMIN_ID:
                await context.bot.send_message(
                    ADMIN_ID, 
                    f"⚠️ **System Alert:** Monitoring was paused for {int(time_diff/60)} mins (Server Sleep/Lag). Now resuming."
                , parse_mode='Markdown')
        except: pass
    
    bot_state["last_check"] = current_time
    # -------------------------------

    now = get_germany_time()
    
    # Auto-Sleep Logic (01:00 - 06:00)
    if 1 <= now.hour < 6:
        if not bot_state["sleeping"]:
            bot_state["sleeping"] = True
            for chat_id in user_routes:
                await context.bot.send_message(chat_id, "😴 **Goodnight!** Pausing until 06:00.", parse_mode='Markdown')
        return

    if bot_state["sleeping"]:
        bot_state["sleeping"] = False
        for chat_id in user_routes:
            await context.bot.send_message(chat_id, "☀️ **Good Morning!** Resuming monitoring...", parse_mode='Markdown')

    # Data Fetching Loop
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        departures = get_delay_data(route['start_id'])
        
        for dep in departures:
            trip_id = dep.get('tripId', dep.get('when'))
            is_cancelled = dep.get('cancelled', False)
            delay = dep.get('delay', 0)
            
            alert_key = f"{trip_id}_{is_cancelled}_{delay}"
            if alert_key in sent_alerts.get(chat_id, set()): continue

            line_name = dep.get('line', {}).get('name', 'Train')
            time_str = dep.get('when', '')[11:16]
            platform = dep.get('platform', 'N/A')
            
            # Load Factor (Crowd)
            load = dep.get('loadFactor', '')
            crowd = "🟢" if load == 'low' else "🟡" if load == 'medium' else "🔴" if load in ['high', 'very-high'] else "⚪"

            msg = ""
            if is_cancelled:
                msg = f"❌ *CANCELLATION ALERT*\n🚆 {line_name} ({time_str})\n⚠️ **CANCELLED (Fällt aus)**"
            elif delay and delay >= 300:
                msg = f"⚠️ *DELAY ALERT*\n🚆 {line_name} ({time_str})\n⏳ Delay: +{int(delay/60)} min\n🚉 Plat: {platform}\n👥 Load: {crowd}"
            
            if msg:
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                if chat_id not in sent_alerts: sent_alerts[chat_id] = set()
                sent_alerts[chat_id].add(alert_key)

# --- RESTART ALERT ---
async def post_init(application: Application):
    """Bot එක Start වෙන වෙලාවෙම Admin ට මැසේජ් එකක් යවයි"""
    if ADMIN_ID != 123456789:
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID, 
                text="🤖 **System Restarted!**\n\nI am back online. If you lost your session, please send /start again."
            , parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send restart alert: {e}")

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('link', get_link))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    if application.job_queue:
        # Check every 2 minutes
        application.job_queue.run_repeating(check_updates, interval=120, first=10)
    
    application.run_polling()
