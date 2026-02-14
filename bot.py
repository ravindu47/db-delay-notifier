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

# --- FLASK SERVER (For Render 24/7) ---
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
db_online_status = True 

# --- DB RETRY LOGIC ---
def get_db_data(func, *args, **kwargs):
    """Tries to fetch data and tracks server status with retries."""
    global db_online_status
    for i in range(3):
        try:
            result = func(*args, **kwargs)
            if not db_online_status:
                db_online_status = True
                return "SERVER_BACK_ONLINE", result
            return "SUCCESS", result
        except Exception as e:
            logger.warning(f"DB Attempt {i+1} failed: {e}")
            db_online_status = False
            time.sleep(3) # Wait 3 seconds before next try
    return "ERROR", None

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello Ravindu! Send me your START station (e.g., Pfarrkirchen).")
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    # Try to get station data from DB
    status, stations = get_db_data(client.locations, text)

    if status == "ERROR":
        await update.message.reply_text("⚠️ DB Server is busy or down. Please try again in a moment.")
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
    """Background monitoring with Platform (Gleis) info."""
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        
        status, departures = get_db_data(client.departures, station=route['start_id'], date=datetime.datetime.now(), duration=45)
        
        if status == "SERVER_BACK_ONLINE":
            await context.bot.send_message(chat_id=chat_id, text="✅ **DB Server is back online!**")

        if status == "SUCCESS" and departures:
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    # Platform (Gleis) number
                    platform = dep.platform if dep.platform else "N/A"
                    
                    alert = (f"⚠️ *DELAY ALERT*\n\n"
                             f"🚆 Train: {dep.name}\n"
                             f"🕒 Time: {dep.dateTime.strftime('%H:%M')}\n"
                             f"⏳ Delay: +{int(delay)} mins\n"
                             f"🚉 Platform (Gleis): {platform}\n"
                             f"📍 Station: {route['start_name']}")
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
