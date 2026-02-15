import os
import logging
import requests
import datetime
import time
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
    return "🚆 DB Pro Bot is Active!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- CONFIG ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
user_routes = {}
sent_alerts = {} # දැනුම් දීම් ඉතිහාසය
bot_state = {"sleeping": False} # Bot නිදිද කියලා බලන්න

# --- API FUNCTIONS ---
def get_station_data(name):
    try:
        url = f"https://v6.db.transport.rest/locations?query={name}&results=1"
        response = requests.get(url, timeout=15)
        data = response.json()
        if data: return data[0]['id'], data[0]['name']
    except Exception as e: logger.error(f"Location Error: {e}")
    return None, None

def get_delay_data(station_id):
    try:
        # විනාඩි 120ක් (පැය 2ක්) ඉදිරියට ඇති කෝච්චි බලනවා
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?duration=120&results=15"
        response = requests.get(url, timeout=15)
        return response.json().get('departures', [])
    except Exception as e: logger.error(f"Departure Error: {e}")
    return []

def get_germany_time():
    # Render Server එක UTC නිසා ජර්මන් වෙලාවට (UTC+1) හරවා ගනී
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 **DB Pro Bot Activated!**\n\nSend me your START station (e.g., Pfarrkirchen).", parse_mode='Markdown')
    context.user_data['step'] = 'start_station'

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in user_routes:
        s_name = user_routes[chat_id]['start_name']
        link = "https://www.bahn.de/service/fahrplaene/live-tracking"
        await update.message.reply_text(f"📍 **Live Map for {s_name}:**\n[Click Here]({link})", parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ Please start monitoring first.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text
    chat_id = update.message.chat_id

    if step == 'start_station':
        s_id, s_name = get_station_data(text)
        if s_id:
            context.user_data['start_id'] = s_id
            context.user_data['start_name'] = s_name
            await update.message.reply_text(f"✅ Start: *{s_name}*\nNow send the **END** station.", parse_mode='Markdown')
            context.user_data['step'] = 'end_station'

    elif step == 'end_station':
        # End station එක නමට විතරක් ගත්තා (API එකට start station එක ඇති)
        user_routes[chat_id] = {
            'start_id': context.user_data['start_id'],
            'start_name': context.user_data['start_name'],
            'end_name': text, 
            'active': True
        }
        sent_alerts[chat_id] = set() # ඉතිහාසය Reset කිරීම
        await update.message.reply_text(f"🚀 **Monitoring Started!**\n\n🟢 From: {context.user_data['start_name']}\n🔴 To: {text}\n\n_I will sleep at 01:00 and wake up at 06:00._", parse_mode='Markdown')
        context.user_data['step'] = None

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    # 1. වෙලාව පරීක්ෂා කිරීම (Sleep Logic)
    now = get_germany_time()
    current_hour = now.hour
    
    # පාන්දර 1 සිට උදේ 6 දක්වා නිදාගනී
    if 1 <= current_hour < 6:
        if not bot_state["sleeping"]:
            bot_state["sleeping"] = True
            for chat_id in user_routes:
                await context.bot.send_message(chat_id, "😴 **Goodnight!** Pausing monitoring until 06:00.", parse_mode='Markdown')
        return # Function එක මෙතනින් නවතී

    # උදේ 6 පසුවී ඇත්නම් අවදි වේ
    if bot_state["sleeping"]:
        bot_state["sleeping"] = False
        for chat_id in user_routes:
            await context.bot.send_message(chat_id, "☀️ **Good Morning!** Resuming train monitoring...", parse_mode='Markdown')

    # 2. සාමාන්‍ය Monitoring
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        departures = get_delay_data(route['start_id'])
        
        for dep in departures:
            line_name = dep.get('line', {}).get('name', 'Train')
            trip_id = dep.get('tripId', line_name) # කෝච්චිය හඳුනාගැනීම
            is_cancelled = dep.get('cancelled', False)
            delay = dep.get('delay', 0)
            
            # --- SMART ALERT LOGIC ---
            # අපි Alert යවන්නේ:
            # 1. කෝච්චිය Cancel නම්
            # 2. Delay එක වෙනස් වුණොත් (උදා: කලින් 5min දැන් 10min)
            # 3. Platform එක වෙනස් වුණොත්
            
            alert_key = f"{trip_id}_{is_cancelled}_{delay}"
            
            # කලින් යැවූ Alert එකම නම් ආයෙත් යවන්නේ නෑ
            if alert_key in sent_alerts.get(chat_id, set()):
                continue

            time_str = dep.get('when', '')[11:16]
            platform = dep.get('platform', 'N/A')
            
            # Crowd Level (සෙනඟ)
            load_factor = dep.get('loadFactor', 'unknown')
            crowd_icon = "⚪"
            if load_factor == 'low': crowd_icon = "🟢 Low Crowd"
            elif load_factor == 'medium': crowd_icon = "🟡 Medium Crowd"
            elif load_factor == 'high': crowd_icon = "🔴 High Crowd"
            elif load_factor == 'very-high': crowd_icon = "⚫ Full"

            msg = ""
            if is_cancelled:
                msg = (f"❌ *CANCELLATION ALERT*\n\n"
                       f"🚆 Train: {line_name}\n"
                       f"🕒 Time: {time_str}\n"
                       f"⚠️ Status: **CANCELLED**\n"
                       f"📍 Station: {route['start_name']}")
            
            elif delay and delay >= 300: # විනාඩි 5ට වැඩි නම්
                msg = (f"⚠️ *DELAY UPDATE*\n\n"
                       f"🚆 Train: {line_name}\n"
                       f"🕒 Time: {time_str}\n"
                       f"⏳ Delay: +{int(delay/60)} mins\n"
                       f"🚉 Platform: {platform}\n"
                       f"👥 Load: {crowd_icon}\n"
                       f"📍 Station: {route['start_name']}")
            
            if msg:
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                # Alert එක යැවූ බව සටහන් කරගන්න (Duplicate වැළැක්වීමට)
                if chat_id not in sent_alerts: sent_alerts[chat_id] = set()
                sent_alerts[chat_id].add(alert_key)

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('link', get_link))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    
    # සෑම විනාඩි 2කට වරක්ම චෙක් කරනවා (ඉක්මන් වෙනස්කම් අල්ලගන්න)
    if application.job_queue:
        application.job_queue.run_repeating(check_updates, interval=120, first=10)
    
    application.run_polling()
