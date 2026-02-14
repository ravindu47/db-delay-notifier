import logging
import datetime
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from pyhafas import HafasClient
from pyhafas.profile import DBProfile

# --- CONFIGURATION ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
USER_CHAT_ID = 1238096007

client = HafasClient(DBProfile())
user_routes = {}  # Stores {chat_id: {'start': ID, 'end': ID, 'active': bool}}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi Ravindu! Please send me the name of your START station (e.g., Pfarrkirchen).")
    context.user_data['step'] = 'start_station'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text

    if step == 'start_station':
        locations = client.locations(text)
        if not locations:
            await update.message.reply_text("Station not found. Try again.")
            return
        context.user_data['start_id'] = locations[0].id
        context.user_data['start_name'] = locations[0].name
        await update.message.reply_text(f"Start: {locations[0].name}. Now send the END station name.")
        context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        locations = client.locations(text)
        if not locations:
            await update.message.reply_text("Station not found. Try again.")
            return
        
        start_id = context.user_data['start_id']
        end_id = locations[0].id
        user_routes[update.message.chat_id] = {'start': start_id, 'end': end_id, 'active': True}
        
        await update.message.reply_text(f"Route Set! Monitoring {context.user_data['start_name']} to {locations[0].name} for delays.")
        context.user_data['step'] = None

async def monitor_delays(context: ContextTypes.DEFAULT_TYPE):
    """Background task to check for delays every 5 minutes."""
    for chat_id, route in user_routes.items():
        if not route['active']: continue
        try:
            departures = client.departures(station=route['start'], date=datetime.datetime.now(), duration=30)
            for dep in departures:
                delay = dep.delay.total_seconds() / 60 if dep.delay else 0
                if delay >= 5:
                    msg = f"⚠️ DELAY ALERT\nTrain: {dep.name}\nScheduled: {dep.dateTime.strftime('%H:%M')}\nDelay: +{int(delay)} mins"
                    await context.bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logging.error(f"Error checking DB: {e}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # Run the delay check every 300 seconds (5 minutes)
    job_queue = application.job_queue
    job_queue.run_repeating(monitor_delays, interval=300, first=10)
    
    application.run_polling()
