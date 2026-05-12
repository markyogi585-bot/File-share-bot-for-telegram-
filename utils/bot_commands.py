"""
╔══════════════════════════════════════════════════════════════╗
║             AUTOMATIC BOT COMMAND MENU SETUP                 ║
║      Ye file '/' dabate hi popup menu show karegi            ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
from telegram import BotCommand
from telegram.ext import Application

logger = logging.getLogger(__name__)

async def setup_bot_commands(app: Application):
    """
    Ye function bot start hote hi automatically commands set kar dega.
    Icons aur clear description ke saath taaki UI premium lage.
    """
    
    # 🌟 Aam Janta (Normal Users) Ke Liye Commands
    # Ye wo commands hain jo sabko popup menu mein dikhengi
    commands = [
        BotCommand("start", "🚀 Bot ko start ya restart karo"),
        BotCommand("myfiles", "📁 Meri upload ki hui saari files"),
        BotCommand("search", "🔍 Koi specific file dhundo"),
        BotCommand("share", "📤 File ka shareable link nikalo"),
        BotCommand("profile", "👤 Mera account aur stats dekho"),
        BotCommand("leaderboard", "🏆 Top uploaders ki list"),
        BotCommand("help", "❓ Bot ko kaise use karna hai?"),
        
        # 👑 Admin Commands (Ye list mein niche rahengi)
        BotCommand("admin", "👑 Open Admin Panel (Only Owner)"),
        BotCommand("broadcast", "📢 Sabko notification bhejo (Only Owner)"),
        BotCommand("forcejoin", "🔒 Force Join ON/OFF karo (Only Owner)"),
        BotCommand("logs", "📄 Bot ke errors check karo (Only Owner)")
    ]

    try:
        # Telegram API ko command bhej rahe hain set karne ke liye
        await app.bot.set_my_commands(commands)
        logger.info("✅ PREMIUM FEATURE: Bot Command Menu (/) successfully set ho gaya!")
    except Exception as e:
        logger.error(f"❌ Command menu set karne mein error aaya: {e}")

