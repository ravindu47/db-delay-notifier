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
ADMIN_ID = 1238096007 

# මෙතනට Bad Birnbach ස්ටේෂන් එක ඔටෝම සෙට් කරලා තියෙන්නේ (ID: 8000858)
PERMANENT_USERS = {
    1238096007: "8000858", # Ravindu (Bad Birnbach)
}

# --- LOGGING SETUP ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (Keep Render Online) ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 Bad Birnbach Monitor is LIVE!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- GLOBAL VARS ---
user_routes = {}
sent_alerts = {}
bot_state = {"sleeping": False, "last_check": time.time()}

# --- API FUNCTIONS ---
def get_station_data(name):
    try:
        url = f"https://v6.db.transport.rest/locations?query={name}&results=1"
        res = requests.get(url, timeout=10)
        data = res.json()
        if data: return data[0]['id'], data[0]['name']
    except: pass
    return None, None

def get_delay_data(station_id):
    try:
        # පැය 2ක ඉදිරි දත්ත බලයි
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?duration=120&results=15"
        res = requests.get(url, timeout=15)
        return res.json().get('departures', [])
    except: return []

def get_germany_time():
    # UTC+1 (Germany Time)
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Welcome Ravindu!**\n\n"
        "I am automatically monitoring **Bad Birnbach** for you.\n"
        "If you want to track a different station, just type the name here.", 
        parse_mode='Markdown'
    )
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    await context.bot.send_chat_action(chat_id, action="typing")
    
    s_id, s_name = get_station_data(text)
    if s_id:
        user_routes[chat_id] = {'start_id': s_id, 'start_name': s_name, 'active': True}
        sent_alerts[chat_id] = set()
        await update.message.reply_text(f"✅ Monitoring switched to: *{s_name}*", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Station not found. Check spelling.")

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    bot_state["last_check"] = time.time()
    now = get_germany_time()
    
    # Auto-Sleep 01:00 - 06:00
    if 1 <= now.hour < 6:
        if not bot_state["sleeping"]:
            bot_state["sleeping"] = True
            for cid in user_routes: 
                try: await context.bot.send_message(cid, "😴 **Bot Sleeping...** See you at 06:00.")
                except: pass
        return

    if bot_state["sleeping"]:
        bot_state["sleeping"] = False
        for cid in user_routes: 
            try: await context.bot.send_message(cid, "☀️ **Good Morning!** Resuming Bad Birnbach monitor.")
            except: pass

    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        deps = get_delay_data(route['start_id'])
        
        for dep in deps:
            trip_id = dep.get('tripId', dep.get('when'))
            is_can = dep.get('cancelled', False)
            delay = dep.get('delay', 0)
            
            # Smart deduplication: alert only on change
            alert_key = f"{trip_id}_{is_can}_{delay}"
            if alert_key in sent_alerts.get(chat_id, set()): continue
            
            line = dep.get('line', {}).get('name', 'Train')
            t = dep.get('when', '')[11:16]
            plat = dep.get('platform', 'N/A')
            load = dep.get('loadFactor', 'unknown')
            crowd = "🟢" if load == 'low' else "🟡" if load == 'medium' else "🔴" if load in ['high', 'very-high'] else "⚪"
            
            msg = ""
            if is_can:
                msg = f"❌ *CANCELLATION ALERT*\n\n🚆 {line} ({t})\n⚠️ **CANCELLED**\n📍 {route['start_name']}"
            elif delay and delay >= 300:
                msg = f"⚠️ *DELAY ALERT*\n\n🚆 {line} ({t})\n⏳ Delay: +{int(delay/60)} min\n🚉 Plat: {plat}\n👥 Load: {crowd}\n📍 {route['start_name']}"
            
            if msg:
                try:
                    await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
                    if chat_id not in sent_alerts: sent_alerts[chat_id] = set()
                    sent_alerts[chat_id].add(alert_key)
                except: pass

# --- AUTO-RESUME ON RESTART ---
async def post_init(application: Application):
    for chat_id, s_id in PERMANENT_USERS.items():
        user_routes[chat_id] = {
            'start_id': s_id, 
            'start_name': "Bad Birnbach", 
            'active': True
        }
        sent_alerts[chat_id] = set()
    
    try:
        await application.bot.send_message(
            ADMIN_ID, 
            "🤖 **System Restarted & Auto-Resumed!**\nMonitoring **Bad Birnbach** now.", 
            parse_mode='Markdown'
        )
    except: pass

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    if app.job_queue:
        app.job_queue.run_repeating(check_updates, interval=120, first=10)
    
    app.run_polling()
