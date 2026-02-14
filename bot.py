import os
import logging
import datetime
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
    return "🚆 Train Delay Bot is Live!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- BOT CONFIG ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
client = HafasClient(DBProfile())
user_routes = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ravindu! Send me your START station name.")
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text

    if step == 'start_station':
        stations = client.locations(text)
        if not stations:
            await update.message.reply_text("❌ Station not found.")
            return
        context.user_data['start_id'] = stations[0].id
        context.user_data['start_name'] = stations[0].name
        await update.message.reply_text(f"✅ Start: {stations[0].name}. Now send END station.")
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        stations = client.locations(text)
        if not stations:
            await update.message.reply_text("❌ Station not found.")
            return
        user_routes[update.message.chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'active': True
        }
        await update.message.reply_text(f"🚀 Monitoring started for {context.user_data['start_name']}!")
        context.user_data['step'] = None

async def check_delays(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, route in user_routes.items():
        if not route['active']: continue
        try:
            departures = client.departures(station=route['start_id'], date=datetime.datetime.now(), duration=30)
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    alert = f"⚠️ DELAY: {dep.name} (+{int(delay)}m) at {route['start_name']}"
                    await context.bot.send_message(chat_id=chat_id, text=alert)
        except Exception as e:
            logger.error(f"Error: {e}")

if __name__ == '__main__':
    # 1. Start Web Server
    Thread(target=run_web_server, daemon=True).start()
    
    # 2. Build Bot
    application = ApplicationBuilder().token(TOKEN).build()
    
    # 3. Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # 4. Job Queue Setup (Error checking included)
    if application.job_queue:
        application.job_queue.run_repeating(check_delays, interval=300, first=10)
        logger.info("Job Queue started successfully.")
    else:
        logger.error("Job Queue is NOT available!")

    application.run_polling()
