import os
import logging
import datetime
import time
import requests
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER ---
server = Flask(__name__)
@server.route('/')
def index():
    return "🚆 DB Monitoring Bot is Online!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- BOT CONFIG ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
user_routes = {}

# --- NEW: DIRECT API CALL (TO BYPASS DNS ISSUES) ---
def get_station_id(name):
    """Finds station ID using a public DB API."""
    try:
        url = f"https://v6.db.transport.rest/locations?query={name}&results=1"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data:
            return data[0]['id'], data[0]['name']
    except Exception as e:
        logger.error(f"API Error (Location): {e}")
    return None, None

def get_departures(station_id):
    """Fetches departures using a public DB API."""
    try:
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?duration=45&results=10"
        response = requests.get(url, timeout=10)
        return response.json().get('departures', [])
    except Exception as e:
        logger.error(f"API Error (Departures): {e}")
    return []

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ravindu! Send me your START station (e.g., Pfarrkirchen).")
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    if step == 'start_station':
        s_id, s_name = get_station_id(text)
        if not s_id:
            await update.message.reply_text("❌ Station not found or Server busy. Try again.")
            return
        context.user_data['start_id'] = s_id
        context.user_data['start_name'] = s_name
        await update.message.reply_text(f"✅ Start: *{s_name}*\nNow send the **END** station.", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        e_id, e_name = get_station_id(text)
        if not e_id:
            await update.message.reply_text("❌ End station not found. Try again.")
            return
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': e_name,
            'active': True
        }
        await update.message.reply_text(f"🚀 Monitoring started for: *{context.user_data['start_name']}*!", parse_mode='Markdown')
        context.user_data['step'] = None

async def check_delays(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        
        departures = get_departures(route['start_id'])
        for dep in departures:
            delay = dep.get('delay')
            if delay and delay >= 300: # 300 seconds = 5 minutes
                platform = dep.get('platform', 'N/A')
                alert = (f"⚠️ *DELAY ALERT*\n\n"
                         f"🚆 Train: {dep['line']['name']}\n"
                         f"🕒 Time: {dep['when'][11:16]}\n"
                         f"⏳ Delay: +{int(delay/60)} mins\n"
                         f"🚉 Platform: {platform}\n"
                         f"📍 From: {route['start_name']}")
                await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode='Markdown')

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    if application.job_queue:
        application.job_queue.run_repeating(check_delays, interval=300, first=10)
    
    application.run_polling()
