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

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (To keep Render alive) ---
server = Flask(__name__)

@server.route('/')
def index():
    return "🚆 DB Delay Notifier is Running!"

def run_web_server():
    # Render uses port 10000 by default
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- BOT CONFIGURATION ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
client = HafasClient(DBProfile())
user_routes = {}

# --- DB DATA FETCH WITH DNS RETRY ---
def get_db_data(func, *args, **kwargs):
    """Tries to connect to DB server and handles DNS/Connection errors."""
    for i in range(4): # 4 attempts
        try:
            result = func(*args, **kwargs)
            return "SUCCESS", result
        except Exception as e:
            logger.warning(f"Attempt {i+1} failed: {e}")
            if i < 3:
                time.sleep(5) # Wait 5 seconds before retrying
            else:
                return "ERROR", None
    return "ERROR", None

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Hello Ravindu!**\n\n"
        "I will monitor your train delays. Please send me your **START** station (e.g., Pfarrkirchen)."
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    # Show "Typing..." action while fetching data
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    status, stations = get_db_data(client.locations, text)

    if status == "ERROR" or not stations:
        await update.message.reply_text("⚠️ DB Server is currently unreachable. Please try again in a minute.")
        return

    if step == 'start_station':
        selected = stations[0]
        context.user_data['start_id'] = selected.id
        context.user_data['start_name'] = selected.name
        await update.message.reply_text(f"✅ Start: *{selected.name}*\nNow send the **END** station.", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        selected = stations[0]
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': selected.name,
            'active': True
        }
        await update.message.reply_text(
            f"🚀 **Monitoring Started!**\n\n"
            f"📍 Route: {context.user_data['start_name']} ➔ {selected.name}\n"
            f"🔔 I'll notify you if a train is delayed by 5+ mins.",
            parse_mode='Markdown'
        )
        context.user_data['step'] = None

async def check_delays(context: ContextTypes.DEFAULT_TYPE):
    """Background job to check delays every 5 mins."""
    for chat_id, route in user_routes.items():
        if not route.get('active'):
            continue
            
        status, departures = get_db_data(
            client.departures, 
            station=route['start_id'], 
            date=datetime.datetime.now(), 
            duration=45
        )
        
        if status == "SUCCESS" and departures:
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    platform = dep.platform if dep.platform else "N/A"
                    alert = (
                        f"⚠️ **DELAY ALERT**\n\n"
                        f"🚆 Train: {dep.name}\n"
                        f"🕒 Time: {dep.dateTime.strftime('%H:%M')}\n"
                        f"⏳ Delay: +{int(delay)} mins\n"
                        f"🚉 Platform (Gleis): {platform}\n"
                        f"📍 Station: {route['start_name']}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode='Markdown')

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    # 1. Start Flask Thread
    flask_thread = Thread(target=run_web_server, daemon=True)
    flask_thread.start()
    
    # 2. Setup Telegram Bot
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # 3. Schedule Background Check
    if application.job_queue:
        application.job_queue.run_repeating(check_delays, interval=300, first=10)
        logger.info("Background Job Queue started.")

    logger.info("Bot is initializing...")
    application.run_polling()
