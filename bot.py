import os
import logging
import datetime
import asyncio
import time
import socket
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from pyhafas import HafasClient
from pyhafas.profile import DBProfile

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
client = HafasClient(DBProfile())
user_routes = {}

# --- DNS FIX: This part helps when the server can't find reiseauskunft.bahn.de ---
def resolve_db_host():
    try:
        # Try to find the IP of DB server manually
        ip = socket.gethostbyname('reiseauskunft.bahn.de')
        logger.info(f"DB Server IP found: {ip}")
        return True
    except Exception as e:
        logger.error(f"DNS Resolution failed: {e}")
        return False

def get_db_data(func, *args, **kwargs):
    """Tries to connect to DB server with improved retry logic."""
    for i in range(3):
        try:
            return "SUCCESS", func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Attempt {i+1} failed. Retrying... {e}")
            time.sleep(3)
    return "ERROR", None

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if we can connect to DB before starting
    if not resolve_db_host():
        await update.message.reply_text("⚠️ DB Connection issue detected. Trying to reconnect...")
    
    await update.message.reply_text("👋 Hi Ravindu! Send me your START station (e.g., Pfarrkirchen).")
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    status, stations = get_db_data(client.locations, text)

    if status == "ERROR" or not stations:
        await update.message.reply_text("❌ DB Server is still unresponsive. I'm retrying in the background...")
        return

    if step == 'start_station':
        context.user_data['start_id'] = stations[0].id
        context.user_data['start_name'] = stations[0].name
        await update.message.reply_text(f"✅ Start: *{stations[0].name}*\nNow send the **END** station.", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': stations[0].name,
            'active': True
        }
        await update.message.reply_text(f"🚀 Monitoring started for: *{context.user_data['start_name']}* ➔ *{stations[0].name}*", parse_mode='Markdown')
        context.user_data['step'] = None

async def check_delays(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        
        status, departures = get_db_data(client.departures, station=route['start_id'], date=datetime.datetime.now(), duration=45)
        
        if status == "SUCCESS" and departures:
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    platform = dep.platform if dep.platform else "N/A"
                    alert = (f"⚠️ *DELAY ALERT*\n\n"
                             f"🚆 Train: {dep.name}\n"
                             f"🕒 Time: {dep.dateTime.strftime('%H:%M')}\n"
                             f"⏳ Delay: +{int(delay)} mins\n"
                             f"🚉 Platform (Gleis): {platform}\n"
                             f"📍 Station: {route['start_name']}")
                    await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode='Markdown')

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    if application.job_queue:
        application.job_queue.run_repeating(check_delays, interval=300, first=10)
    
    application.run_polling()
