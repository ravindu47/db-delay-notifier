import os
import logging
import datetime
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from pyhafas import HafasClient
from pyhafas.profile import DBProfile

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- FLASK SERVER (TO KEEP RENDER ALIVE) ---
server = Flask(__name__)

@server.route('/')
def index():
    return "🚆 Train Delay Bot is Live and Running!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    server.run(host='0.0.0.0', port=port)

# --- BOT CONFIGURATION ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
USER_CHAT_ID = 1238096007

client = HafasClient(DBProfile())
user_routes = {}

# --- BOT FUNCTIONS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initializes the bot and greets Ravindu."""
    welcome_text = (
        "👋 Hello Ravindu!\n\n"
        "I can monitor DB train delays for you 24/7.\n"
        "Please send me the name of your **START** station (e.g., Pfarrkirchen)."
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
    context.user_data['step'] = 'start_station'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles station inputs and route setup."""
    step = context.user_data.get('step')
    input_text = update.message.text

    if step == 'start_station':
        stations = client.locations(input_text)
        if not stations:
            await update.message.reply_text("❌ Station not found. Please try again with a correct name.")
            return
        
        selected = stations[0]
        context.user_data['start_id'] = selected.id
        context.user_data['start_name'] = selected.name
        
        await update.message.reply_text(f"✅ Start Station: *{selected.name}*\nNow, please send the **END** station name.", parse_mode='Markdown')
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        stations = client.locations(input_text)
        if not stations:
            await update.message.reply_text("❌ Station not found. Please try again.")
            return
        
        end_station = stations[0]
        chat_id = update.message.chat_id
        
        # Save route globally for monitoring
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': end_station.name,
            'active': True
        }
        
        success_msg = (
            f"🚀 **Monitoring Started!**\n\n"
            f"📍 Route: {context.user_data['start_name']} ➔ {end_station.name}\n"
            f"🔔 I will notify you if your train is delayed by 5+ minutes."
        )
        await update.message.reply_text(success_msg, parse_mode='Markdown')
        context.user_data['step'] = None

async def check_for_delays(context: ContextTypes.DEFAULT_TYPE):
    """Background task to fetch DB data and alert user."""
    for chat_id, route in user_routes.items():
        if not route['active']:
            continue
            
        try:
            # Check departures for the next 45 minutes
            departures = client.departures(
                station=route['start_id'], 
                date=datetime.datetime.now(), 
                duration=45
            )
            
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                
                if delay >= 5:
                    alert = (
                        f"⚠️ **DELAY ALERT**\n\n"
                        f"🚆 Train: {dep.name}\n"
                        f"🕒 Scheduled: {dep.dateTime.strftime('%H:%M')}\n"
                        f"⏳ Delay: +{int(delay)} mins\n"
                        f"🚉 Station: {route['start_name']}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=alert, parse_mode='Markdown')
                    
        except Exception as e:
            logger.error(f"DB Fetch Error: {e}")

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    # 1. Start Flask (Web) Thread
    web_thread = Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    # 2. Start Telegram Bot
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # 3. Schedule Background Check (Every 5 minutes)
    job_queue = application.job_queue
    job_queue.run_repeating(check_for_delays, interval=300, first=10)
    
    logger.info("Bot is initializing...")
    application.run_polling()
