from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import FORCE_SUB_CHANNEL

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.bot_data["db"].touch_user(user)
    if FORCE_SUB_CHANNEL:
        try:
            member = await context.bot.get_chat_member(FORCE_SUB_CHANNEL, user.id)
            if member.status not in ("member", "administrator", "creator"):
                await update.message.reply_text(
                    "🔒 يجب الاشتراك بالقناة أولاً ثم أرسل /start مجدداً.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("الاشتراك بالقناة", url=f"https://t.me/{FORCE_SUB_CHANNEL.lstrip('@')}")]])
                )
                return
        except Exception:
            await update.message.reply_text("تعذر التحقق من الاشتراك. تأكد أن البوت مشرف بالقناة.")
            return
    keyboard = [
        [InlineKeyboardButton("🔎 البحث عن مانجا", callback_data="menu:search"),
         InlineKeyboardButton("🆕 أحدث المانجا", callback_data="menu:latest")],
        [InlineKeyboardButton("📚 المصادر", callback_data="menu:sources"),
         InlineKeyboardButton("⭐ المفضلة", callback_data="menu:favorites")],
        [InlineKeyboardButton("❤️ المتابعة", callback_data="menu:follows")]
    ]
    await update.message.reply_text(
        "🖤 أهلاً بك في Manga Virus 🦠\nبوابتك لعالم المانجا والمانهوا.\n\n"
        "للبحث أرسل: /search اسم المانجا",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
