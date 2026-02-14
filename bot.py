import os
import logging
import datetime
import time
import asyncio
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from pyhafas import HafasClient
from pyhafas.profile import DBProfile

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (For Render 24/7) ---
server = Flask(__name__)

@server.route('/')
def index():
    return "🚆 DB Delay Bot is Online & Monitoring!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- BOT CONFIG ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
client = HafasClient(DBProfile())
user_routes = {}

# --- HELPER: AUTO-RECONNECT LOGIC ---
def get_db_data(func, *args, **kwargs):
    """Tries to connect to DB server up to 3 times if it fails."""
    for i in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"DB Connection attempt {i+1} failed: {e}")
            time.sleep(2) # Wait 2 seconds before retry
    return None

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ravindu! Send me the name of your START station (e.g., Pfarrkirchen).")
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text

    if step == 'start_station':
        # Using auto-reconnect logic to find station
        stations = get_db_data(client.locations, text)
        
        if not stations:
            await update.message.reply_text("❌ DB Server busy or Station not found. Please try again.")
            return
            
        context.user_data['start_id'] = stations[0].id
        context.user_data['start_name'] = stations[0].name
        await update.message.reply_text(f"✅ Start: *{stations[0].name}*\nNow send the **END** station name.", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        stations = get_db_data(client.locations, text)
        if not stations:
            await update.message.reply_text("❌ DB Server busy. Please try again.")
            return
            
        user_routes[update.message.chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': stations[0].name,
            'active': True
        }
        await update.message.reply_text(f"🚀 Monitoring started for: *{context.user_data['start_name']}* ➔ *{stations[0].name}*", parse_mode='Markdown')
        context.user_data['step'] = None

async def check_delays(context: ContextTypes.DEFAULT_TYPE):
    """Background task with Auto-Reconnect."""
    for chat_id, route in user_routes.items():
        if not route['active']: continue
        
        # Try to get departures with auto-reconnect
        departures = get_db_data(client.departures, station=route['start_id'], date=datetime.datetime.now(), duration=45)
        
        if departures:
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    alert = (f"⚠️ *DELAY ALERT*\n\n"
                             f"🚆 Train: {dep.name}\n"
                             f"🕒 Time: {dep.dateTime.strftime('%H:%M')}\n"
                             f"⏳ Delay: +{int(delay)} mins\n"
                             f"🚉 From: {route['start_name']}")
                    await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode='Markdown')

# --- MAIN ---
if __name__ == '__main__':
    # 1. Start Web Server
    Thread(target=run_web_server, daemon=True).start()
    
    # 2. Build Bot
    application = ApplicationBuilder().token(TOKEN).build()
    
    # 3. Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # 4. Job Queue (Check every 5 mins)
    if application.job_queue:
        application.job_queue.run_repeating(check_delays, interval=300, first=10)
    
    logger.info("Bot is Live on Render!")
    application.run_polling()
