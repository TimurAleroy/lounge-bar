import os
import requests
from datetime import date
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes, ConversationHandler

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
NOTION_VISITS_DB_ID = os.environ["NOTION_VISITS_DB_ID"]

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

GUEST_NAME, SELECT_GUEST, AFTER_CARD, EDIT_CHOICE, EDIT_VALUE = range(5)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🛑 Остановлено. Напиши имя гостя чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def get_guest_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=HEADERS,
        json={"filter": {"property": "Имя Гостя", "title": {"contains": name}}}
    )
    results = res.json().get("results", [])

    if len(results) == 1:
        return await show_guest(update, context, results[0])
    elif len(results) > 1:
        context.user_data["search_results"] = [
            {"id": g["id"], "name": g["properties"]["Имя Гостя"]["title"][0]["plain_text"]}
            for g in results
        ]
        names = [g["name"] for g in context.user_data["search_results"]]
        keyboard = [[n] for n in names] + [["❌ Никто из них"]]
        await update.message.reply_text(
            f"Нашёл {len(results)} гостей с именем «{name}».\nВыбери нужного:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return SELECT_GUEST
    else:
        await update.message.reply_text(f"❌ Гость «{name}» не найден. Проверьте имя.")
        return GUEST_NAME

async def select_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "❌ Никто из них":
        await update.message.reply_text("Напиши имя гостя:", reply_markup=ReplyKeyboardRemove())
        return GUEST_NAME
    for g in context.user_data.get("search_results", []):
        if g["name"] == text:
            res = requests.get(f"https://api.notion.com/v1/pages/{g['id']}", headers=HEADERS)
            return await show_guest(update, context, res.json())
    await update.message.reply_text("Не понял выбор. Попробуй ещё раз.")
    return SELECT_GUEST

async def show_guest(update, context, guest):
    props = guest["properties"]
    guest_page_id = guest["id"]
    context.user_data["current_guest_id"] = guest_page_id

    def get_text(prop):
        items = props.get(prop, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else "не указано"
    def get_title(prop):
        items = props.get(prop, {}).get("title", [])
        return items[0]["plain_text"] if items else "не указано"
    def get_select(prop):
        s = props.get(prop, {}).get("select")
        return s["name"] if s else "не указано"
    def get_date(prop):
        d = props.get(prop, {}).get("date")
        return d["start"] if d else "не указана"
    def get_phone(prop):
        return props.get(prop, {}).get("phone_number") or "не указан"

    birthday_raw = get_date("Дата рождения")
    birthday = birthday_raw
    if birthday_raw != "не указана":
        try:
            parts = birthday_raw.split("-")
            if len(parts) == 3:
                birthday = f"{parts[2]}.{parts[1]}.{parts[0]}"
        except:
            pass
    birthday_alert = ""
    if birthday_raw != "не указана":
        try:
            bd_month_day = birthday_raw[5:]
            today_month_day = date.today().strftime("%m-%d")
            if bd_month_day == today_month_day:
                birthday_alert = "\n\n🎂🎉 *СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ ГОСТЯ!* 🎉🎂"
        except:
            pass

    text = (
        f"👤 *{get_title('Имя Гостя')}*\n"
        f"🏷 Статус: {get_select('Частота визитов')}\n"
        f"🎂 День рождения: {birthday}\n"
        f"📱 Телефон: {get_phone('Телефон')}\n"
        f"⭐ Важно: {get_text('Что важно для гостя')}\n"
    )

    visits_res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_VISITS_DB_ID}/query",
        headers=HEADERS,
        json={
            "filter": {"property": "Гость", "relation": {"contains": guest_page_id}},
            "sorts": [{"property": "Дата", "direction": "descending"}],
            "page_size": 3
        }
    )
    visits = visits_res.json().get("results", [])

    if visits:
        text += "\n📋 *Последние визиты:*\n"
        for v in visits:
            vp = v["properties"]
            def vget_text(p):
                items = vp.get(p, {}).get("rich_text", [])
                return items[0]["plain_text"] if items else "—"
            def vget_date(p):
                d = vp.get(p, {}).get("date")
                return d["start"] if d else "—"
            text += (
                f"🗓 {vget_date('Дата')}\n"
                f"   🪄 {vget_text('Кальян')}  🍹 {vget_text('Напитки')}\n"
                f"   📝 {vget_text('Заметки')}\n"
            )
    else:
        text += "\n📋 Визитов пока нет."

    text += birthday_alert

    keyboard = [["✏️ Редактировать карточку"], ["🔍 Новый поиск"]]
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return AFTER_CARD

# ─── ПОСЛЕ ПОКАЗА КАРТОЧКИ ────────────────────────────

async def after_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "✏️ Редактировать карточку":
        keyboard = [
            ["🏷 Статус", "🎂 День рождения"],
            ["📱 Телефон", "⭐ Что важно"],
            ["❌ Отмена"]
        ]
        await update.message.reply_text("Что редактируем?", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return EDIT_CHOICE
    elif text == "🔍 Новый поиск":
        await update.message.reply_text("Напиши имя гостя:", reply_markup=ReplyKeyboardRemove())
        return GUEST_NAME
    else:
        # Считаем что это новое имя для поиска
        return await get_guest_name(update, context)

# ─── РЕДАКТИРОВАНИЕ ───────────────────────────────────

async def edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Отмена":
        await update.message.reply_text("Отменено. Напиши имя гостя для нового поиска.", reply_markup=ReplyKeyboardRemove())
        return GUEST_NAME

    field_map = {
        "🏷 Статус": "status",
        "🎂 День рождения": "birthday",
        "📱 Телефон": "phone",
        "⭐ Что важно": "important"
    }

    if text not in field_map:
        await update.message.reply_text("Не понял выбор.")
        return EDIT_CHOICE

    context.user_data["edit_field"] = field_map[text]

    if field_map[text] == "status":
        keyboard = [["VIP", "Постоянный"], ["Редкий", "Новый"]]
        await update.message.reply_text("Новый статус?", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    elif field_map[text] == "birthday":
        await update.message.reply_text("Новая дата рождения?\n(Например: 15.06.1990)", reply_markup=ReplyKeyboardRemove())
    elif field_map[text] == "phone":
        await update.message.reply_text("Новый номер телефона?", reply_markup=ReplyKeyboardRemove())
    elif field_map[text] == "important":
        await update.message.reply_text("Что важно для гостя?", reply_markup=ReplyKeyboardRemove())

    return EDIT_VALUE

async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    field = context.user_data["edit_field"]
    guest_id = context.user_data["current_guest_id"]

    properties = {}

    if field == "status":
        properties["Частота визитов"] = {"select": {"name": text}}
    elif field == "birthday":
        try:
            parts = text.split(".")
            if len(parts) == 3:
                iso_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                properties["Дата рождения"] = {"date": {"start": iso_date}}
            else:
                await update.message.reply_text("❌ Неверный формат. Используй: 15.06.1990")
                return EDIT_VALUE
        except:
            await update.message.reply_text("❌ Неверный формат. Используй: 15.06.1990")
            return EDIT_VALUE
    elif field == "phone":
        properties["Телефон"] = {"phone_number": text}
    elif field == "important":
        properties["Что важно для гостя"] = {"rich_text": [{"text": {"content": text}}]}

    res = requests.patch(f"https://api.notion.com/v1/pages/{guest_id}", headers=HEADERS, json={"properties": properties})

    if res.status_code == 200:
        await update.message.reply_text("✅ Обновлено! Напиши имя гостя для нового поиска.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("❌ Ошибка при обновлении.", reply_markup=ReplyKeyboardRemove())

    context.user_data.clear()
    return GUEST_NAME

conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, get_guest_name)],
    states={
        GUEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guest_name)],
        SELECT_GUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_guest)],
        AFTER_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, after_card)],
        EDIT_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_choice)],
        EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
    },
    fallbacks=[
        CommandHandler("stop", stop),
        CommandHandler("cancel", stop),
    ],
)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(conv_handler)
app.run_polling()
