import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, RPCError

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, FORCE_CHANNEL
from database import init_db, save_user, toggle_item, get_items, stats
from manga_api import search_manga, MangaAPIError

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('manga-virus')
app = Client('manga_virus', api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

HOME = InlineKeyboardMarkup([
    [InlineKeyboardButton('🔎 بحث عن مانجا', callback_data='search'), InlineKeyboardButton('🆕 أحدث الفصول', callback_data='latest')],
    [InlineKeyboardButton('⭐ المفضلة', callback_data='favorites'), InlineKeyboardButton('🔔 المتابَعة', callback_data='follows')],
    [InlineKeyboardButton('📚 التصنيفات', callback_data='categories'), InlineKeyboardButton('💬 اقتراح / شكوى', callback_data='feedback')],
    [InlineKeyboardButton('ℹ️ حول البوت', callback_data='about')]
])

async def subscribed(client, user_id: int) -> bool:
    if not FORCE_CHANNEL:
        return True
    try:
        member = await client.get_chat_member(FORCE_CHANNEL, user_id)
        return member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    except UserNotParticipant:
        return False
    except RPCError as e:
        log.warning('Subscription check failed: %s', e)
        return False

@app.on_message(filters.command('start') & filters.private)
async def start(client, message):
    save_user(message.from_user)
    if not await subscribed(client, message.from_user.id):
        channel = FORCE_CHANNEL if FORCE_CHANNEL.startswith('@') else FORCE_CHANNEL
        await message.reply_text('🔒 للاستخدام، اشترك بالقناة أولاً ثم اضغط تحقق.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📢 فتح القناة', url=f'https://t.me/{channel.lstrip("@")}')],
                                               [InlineKeyboardButton('تحقق من الاشتراك', callback_data='check_sub')]]))
        return
    await message.reply_text('🖤 أهلاً بك في Manga Virus 🦠\nبوابتك لعالم المانجا والمانهوا\n\nاختر من القائمة:', reply_markup=HOME)

@app.on_message(filters.command('id') & filters.private)
async def my_id(client, message):
    await message.reply_text(f'Your ID: `{message.from_user.id}`')

@app.on_message(filters.command('admin') & filters.private)
async def admin_panel(client, message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.reply_text('هذا الأمر للمشرف فقط.')
    s = stats()
    await message.reply_text(f'🛠 لوحة الإدارة\n👥 المستخدمون: {s["users"]}\n⭐ المفضلة: {s["favorites"]}\n🔔 المتابعات: {s["follows"]}')

@app.on_callback_query()
async def callbacks(client, query):
    data = query.data or ''
    uid = query.from_user.id
    if data == 'check_sub':
        if await subscribed(client, uid):
            await query.message.edit_text('🖤 أهلاً بك في Manga Virus 🦠', reply_markup=HOME)
        else:
            await query.answer('لم يظهر اشتراكك بعد. اشترك ثم أعد التحقق.', show_alert=True)
        return
    if data == 'search':
        await query.message.reply_text('أرسل اسم المانجا الذي تريد البحث عنه.\n(سيتم تفعيل البحث بعد تثبيت عقد API الفعلي.)')
    elif data == 'latest':
        await query.answer('ميزة أحدث الفصول تحتاج تثبيت مسار API أولاً.', show_alert=True)
    elif data == 'categories':
        await query.answer('التصنيفات ستُربط مع بيانات المصدر بعد التحقق من API.', show_alert=True)
    elif data == 'feedback':
        await query.message.reply_text('أرسل اقتراحك أو شكواك برسالة واحدة هنا.')
    elif data == 'about':
        await query.message.reply_text('Manga Virus | V1.0\nبوت للمانجا والمانهوا.')
    elif data in ('favorites', 'follows'):
        table = 'favorites' if data == 'favorites' else 'follows'
        rows = get_items(table, uid)
        label = 'المفضلة' if data == 'favorites' else 'المتابَعة'
        body = '\n'.join(f'• {r["title"]} (`{r["manga_id"]}`)' for r in rows) or 'القائمة فارغة حالياً.'
        await query.message.reply_text(f'{label}:\n{body}')
    await query.answer()

@app.on_message(filters.private & filters.text & ~filters.command(['start','admin','id']))
async def text_handler(client, message):
    text = (message.text or '').strip()
    if not text:
        return
    if not await subscribed(client, message.from_user.id):
        return await message.reply_text('🔒 اشترك بالقناة أولاً ثم أرسل /start للتحقق.')
    try:
        await search_manga(text)
    except MangaAPIError as e:
        await message.reply_text(f'⚠️ {e}')
    except Exception:
        log.exception('Unhandled text handler error')
        await message.reply_text('حدث خطأ غير متوقع. حاول لاحقاً.')

async def main():
    init_db()
    log.info('Starting Manga Virus...')
    await app.start()
    me = await app.get_me()
    log.info('Bot started: @%s', me.username)
    await asyncio.Event().wait()

if __name__ == '__main__':
    app.run(main())
