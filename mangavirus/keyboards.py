from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 بحث عن مانجا", callback_data="menu:search"),
         InlineKeyboardButton("🆕 أحدث الفصول", callback_data="menu:latest")],
        [InlineKeyboardButton("⭐ المفضلة", callback_data="menu:favs"),
         InlineKeyboardButton("📚 المصادر", callback_data="menu:sources")],
        [InlineKeyboardButton("ℹ️ المساعدة", callback_data="menu:help")],
    ])

def manga_results(rows):
    buttons = []
    for token, item in rows:
        title = item["title"][:48]
        buttons.append([InlineKeyboardButton(title, callback_data=f"manga:{token}")])
    return InlineKeyboardMarkup(buttons) if buttons else None

def chapter_buttons(token, chapters, page=0, per_page=8):
    start = page * per_page
    buttons = [[InlineKeyboardButton(str(c["title"])[:48], callback_data=f"chapter:{token}:{start+i}")]
               for i, c in enumerate(chapters[start:start+per_page])]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"chapters:{token}:{page-1}"))
    if start + per_page < len(chapters):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"chapters:{token}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("⭐ إضافة للمفضلة", callback_data=f"favorite:{token}")])
    buttons.append([InlineKeyboardButton("🏠 القائمة", callback_data="menu:home")])
    return InlineKeyboardMarkup(buttons)
