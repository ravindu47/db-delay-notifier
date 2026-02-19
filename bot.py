import os
import logging
import requests
import datetime
import psycopg2
from flask import Flask
from threading import Thread
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, Application

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
DB_URL = os.environ.get("DATABASE_URL") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER ---
server = Flask(__name__)
@server.route('/')
def index(): return "🚆 Hybrid CommuteBot Pro is Active!"

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server.run(host='0.0.0.0', port=port)

# --- DATABASE FUNCTIONS ---
def get_db_connection():
    return psycopg2.connect(DB_URL, connect_timeout=10)

def upsert_user(chat_id, home_id=None, home_name=None, work_id=None, work_name=None, uni_id=None, uni_name=None, shift_type=None, start_hour=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (chat_id,))
        if home_id: cur.execute("UPDATE users SET home_id=%s, home_name=%s WHERE chat_id=%s", (home_id, home_name, chat_id))
        if work_id: cur.execute("UPDATE users SET work_id=%s, work_name=%s WHERE chat_id=%s", (work_id, work_name, chat_id))
        if uni_id:  cur.execute("UPDATE users SET uni_id=%s, uni_name=%s WHERE chat_id=%s", (uni_id, uni_name, chat_id))
        if shift_type: cur.execute("UPDATE users SET shift_type=%s WHERE chat_id=%s", (shift_type, chat_id))
        if start_hour is not None: cur.execute("UPDATE users SET start_hour=%s WHERE chat_id=%s", (start_hour, chat_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ DB Error: {e}")
        return False

# --- STATION SEARCH LOGIC ---

async def search_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    command = update.message.text.split()[0][1:] # Get command without / (sethome, setwork, etc)
    
    # Handle empty input
    if not query:
        await update.message.reply_text(
            f"⚠️ **Usage Error**\n\nPlease provide a station name.\nExample: `/{command} Pfarrkirchen`",
            parse_mode='Markdown'
        )
        return

    url = f"https://v6.db.transport.rest/locations?query={quote(query)}&results=3"
    
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        res = response.json()
        
        if not res:
            await update.message.reply_text(
                f"🔍 **Station Not Found**\n\nCould not find any station named '{query}'. Please check the spelling and try again.",
                parse_mode='Markdown'
            )
            return

        btns = [[InlineKeyboardButton(s['name'], callback_data=f"{command}:{s['id']}:{s['name']}")] for s in res if 'id' in s]
        
        if not btns:
            await update.message.reply_text("⚠️ No valid stations found. Try a different name.")
            return
            
        await update.message.reply_text(
            "📍 **Select the correct station:**",
            reply_markup=InlineKeyboardMarkup(btns),
            parse_mode='Markdown'
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"API Connection Error: {e}")
        await update.message.reply_text(
            "🛑 **Service Unavailable**\n\nThe Deutsche Bahn API is currently unreachable. Please try again in a few minutes.",
            parse_mode='Markdown'
        )

# --- SYSTEM NOTIFICATION ---

async def post_init(application: Application):
    # Notify Admin when server is up
    if ADMIN_ID != 0:
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID, 
                text="🚀 **System Online**\nHybrid CommuteBot Pro is up and running. Connection to DB and API established."
            )
        except Exception as e:
            logger.error(f"Failed to send bootup alert: {e}")
    
    commands = [
        BotCommand("start", "Start & Register"),
        BotCommand("check", "Instant Check"),
        BotCommand("sethome", "Set Home Station"),
        BotCommand("setwork", "Set Work Station"),
        BotCommand("setuni", "Set Uni Station"),
        BotCommand("time", "Set Work Hour (/time 8)"),
        BotCommand("mode", "Toggle Day/Night Shift")
    ]
    await application.bot.set_my_commands(commands)

# --- MAIN APP SETUP ---

if __name__ == '__main__':
    Thread(target=run_web_server, daemon=True).start()
    
    # Initialize Application
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    # Add Handlers
    app.add_handler(CommandHandler('start', start)) # Reference your existing start function
    app.add_handler(CommandHandler('sethome', search_station))
    app.add_handler(CommandHandler('setwork', search_station))
    app.add_handler(CommandHandler('setuni', search_station))
    # ... Add your other handlers (set_time, toggle_mode, button_callback, etc.) ...
    
    app.run_polling()
