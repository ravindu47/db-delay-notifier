import os
import logging
import datetime
import asyncio
import time
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from pyhafas import HafasClient
from pyhafas.profile import DBProfile

# --- LOGGING SETUP ---
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

# --- CONFIG ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
client = HafasClient(DBProfile())
user_routes = {}
db_status = {"online": True} # DB සර්වර් එකේ තත්ත්වය තබා ගැනීමට

# --- DB RETRY & STATUS CHECK ---
def get_db_data(func, *args, **kwargs):
    """Tries to fetch data and tracks server status."""
    for i in range(3):
        try:
            result = func(*args, **kwargs)
            if not db_status["online"]:
                db_status["online"] = True
                return "SERVER_BACK_ONLINE", result
            return "SUCCESS", result
        except Exception as e:
            logger.warning(f"DB Attempt {i+1} failed: {e}")
            db_status["online"] = False
            time.sleep(2)
    return "ERROR", None

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ravindu! Send me your START station name (e.g., Pfarrkirchen).")
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    status, stations = get_db_data(client.locations, text)

    if status == "ERROR":
        await update.message.reply_text("⚠️ DB Server is currently down. I will notify you as soon as it's back up!")
        user_routes[chat_id] = {'pending_text': text, 'step': step, 'active': False}
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
        await update.message.reply_text(f"🚀 Monitoring started for: *{context.user_data['start_name']}*!", parse_mode='Markdown')
        context.user_data['step'] = None

async def check_delays(context: ContextTypes.DEFAULT_TYPE):
    """Background monitoring with Auto-Reconnect and Status Alerts."""
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        
        status, departures = get_db_data(client.departures, station=route['start_id'], date=datetime.datetime.now(), duration=45)
        
        if status == "SERVER_BACK_ONLINE":
            await context.bot.send_message(chat_id=chat_id, text="✅ **DB Server is back online!** Resuming monitoring...")

        if status == "SUCCESS" and departures:
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    alert = (f"⚠️ *DELAY ALERT*\n\n🚆 {dep.name}\n🕒 Time: {dep.dateTime.strftime('%H:%M')}\n"
                             f"⏳ Delay: +{int(delay)} mins\n🚉 From: {route['start_name']}")
                    await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode='Markdown')

# --- MAIN ---
if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    if application.job_queue:
        application.job_queue.run_repeating(check_delays, interval=300, first=10)
    
    application.run_polling()
