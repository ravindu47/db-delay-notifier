import os
import logging
import requests
import datetime
import time
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, Application

# --- CONFIGURATION ---
TOKEN = "8309743097:AAEtIPBmiknxtiEb9_WphCHmb0G_ozeN7cY"
ADMIN_ID = 1238096007 

# Default Station on Restart (Bad Birnbach = 8000858)
PERMANENT_USERS = {
    1238096007: "8000858", 
}

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 DB Pro Bot with Buttons is LIVE!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- GLOBAL VARS ---
user_routes = {}
sent_alerts = {}
bot_state = {"sleeping": False, "last_check": time.time()}

# --- API FUNCTIONS ---
def get_station_suggestions(name):
    """ස්ටේෂන් කිහිපයක් සොයා බලා ලිස්ට් එකක් දෙයි"""
    try:
        url = f"https://v6.db.transport.rest/locations?query={name}&results=5"
        res = requests.get(url, timeout=10)
        data = res.json()
        
        suggestions = []
        for item in data:
            if item.get('type') in ['stop', 'station']:
                suggestions.append({'id': item['id'], 'name': item['name']})
        return suggestions
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

def get_delay_data(station_id):
    try:
        url = f"https://v6.db.transport.rest/stops/{station_id}/departures?duration=120&results=15"
        res = requests.get(url, timeout=15)
        return res.json().get('departures', [])
    except: return []

def get_germany_time():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Hello!**\n\n"
        "I am currently monitoring **Bad Birnbach** (Default).\n"
        "To change the station, just type the name (e.g., `Eggenfelden`). I will give you buttons to choose from!", 
        parse_mode='Markdown'
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    
    await context.bot.send_chat_action(chat_id, action="typing")
    
    # ස්ටේෂන් කිහිපයක් හොයනවා
    suggestions = get_station_suggestions(text)

    if not suggestions:
        await update.message.reply_text("❌ Station not found. Please check spelling.")
        return

    # ස්ටේෂන් 1ක් පමණක් හම්බුණොත් කෙලින්ම සෙට් කරනවා
    if len(suggestions) == 1:
        s = suggestions[0]
        user_routes[chat_id] = {'start_id': s['id'], 'start_name': s['name'], 'active': True}
        sent_alerts[chat_id] = set()
        await update.message.reply_text(f"✅ Monitoring set to: *{s['name']}*", parse_mode='Markdown')
        return

    # ස්ටේෂන් කිහිපයක් තිබේ නම් බටන්ස් හදනවා
    keyboard = []
    for s in suggestions:
        # Button Data Format: "set:STATION_ID"
        keyboard.append([InlineKeyboardButton(s['name'], callback_data=f"set:{s['id']}:{s['name']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"🔍 Found {len(suggestions)} stations. Please select one:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """බටන් එක එබුවම වැඩ කරන කොටස"""
    query = update.callback_query
    await query.answer() # බටන් එක එබූ බව ටෙලිග්‍රෑම් එකට කියනවා
    
    data = query.data.split(':')
    s_id = data[1]
    s_name = data[2]
    chat_id = query.message.chat_id

    # අලුත් ස්ටේෂන් එක සෙට් කිරීම
    user_routes[chat_id] = {'start_id': s_id, 'start_name': s_name, 'active': True}
    sent_alerts[chat_id] = set()
    
    # පරණ මැසේජ් එක Edit කරනවා
    await query.edit_message_text(text=f"✅ **Station Updated!**\nNow monitoring: *{s_name}*", parse_mode='Markdown')

async def check_updates(context: ContextTypes.DEFAULT_TYPE):
    # System Monitor
    bot_state["last_check"] = time.time()
    
    now = get_germany_time()
    # Sleep Mode (01:00 - 06:00)
    if 1 <= now.hour < 6:
        if not bot_state["sleeping"]:
            bot_state["sleeping"] = True
            for cid in user_routes: 
                try: await context.bot.send_message(cid, "😴 **Goodnight!** Pausing alerts until 06:00.")
                except: pass
        return

    if bot_state["sleeping"]:
        bot_state["sleeping"] = False
        for cid in user_routes: 
            try: await context.bot.send_message(cid, "☀️ **Good Morning!** Resuming monitoring.")
            except: pass

    # Check Trains
    for chat_id, route in user_routes.items():
        if not route.get('active'): continue
        deps = get_delay_data(route['start_id'])
        
        for dep in deps:
            trip_id = dep.get('tripId', dep.get('when'))
            is_can = dep.get('cancelled', False)
            delay = dep.get('delay', 0)
            
            alert_key = f"{trip_id}_{is_can}_{delay}"
            if alert_key in sent_alerts.get(chat_id, set()): continue
            
            line = dep.get('line', {}).get('name', 'Train')
            t = dep.get('when', '')[11:16]
            plat = dep.get('platform', 'N/A')
            load = dep.get('loadFactor', '')
            crowd = "🟢" if load == 'low' else "🟡" if load == 'medium' else "🔴" if load in ['high', 'very-high'] else "⚪"
            
            msg = ""
            if is_can:
                msg = f"❌ *CANCELLED*\n🚆 {line} ({t})\n📍 {route['start_name']}\n⚠️ Trip Cancelled!"
            elif delay and delay >= 300:
                msg = f"⚠️ *DELAY ALERT*\n🚆 {line} ({t})\n⏳ +{int(delay/60)} min\n🚉 Plat: {plat}\n👥 Load: {crowd}\n📍 {route['start_name']}"
            
            if msg:
                try:
                    await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
                    if chat_id not in sent_alerts: sent_alerts[chat_id] = set()
                    sent_alerts[chat_id].add(alert_key)
                except: pass

async def post_init(application: Application):
    # Auto-Resume Logic
    for chat_id, s_id in PERMANENT_USERS.items():
        user_routes[chat_id] = {'start_id': s_id, 'start_name': "Bad Birnbach (Auto)", 'active': True}
        sent_alerts[chat_id] = set()
    
    try:
        await application.bot.send_message(ADMIN_ID, "🤖 **System Auto-Resumed!**\nButtons & Selection Logic Active.", parse_mode='Markdown')
    except: pass

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(CallbackQueryHandler(button_callback)) # Button Clicks Handle කිරීමට
    
    if app.job_queue:
        app.job_queue.run_repeating(check_updates, interval=120, first=10)
    
    app.run_polling()
