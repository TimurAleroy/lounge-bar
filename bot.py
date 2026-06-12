import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
NOTION_VISITS_DB_ID = os.environ["NOTION_VISITS_DB_ID"]

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

async def search_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()

    # Поиск гостя
    res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=HEADERS,
        json={"filter": {"property": "Имя Гостя", "title": {"contains": name}}}
    )
    results = res.json().get("results", [])

    if not results:
        await update.message.reply_text(f"❌ Гость «{name}» не найден.")
        return

    guest = results[0]
    props = guest["properties"]
    guest_page_id = guest["id"]

    def get_text(prop):
        items = props.get(prop, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else "не указано"

    def get_title(prop):
        items = props.get(prop, {}).get("title", [])
        return items[0]["plain_text"] if items else "не указано"

    def get_date(prop):
        d = props.get(prop, {}).get("date")
        return d["start"] if d else "не указана"

    def get_select(prop):
        s = props.get(prop, {}).get("select")
        return s["name"] if s else "не указано"

    # Основная карточка
    text = (
        f"👤 *{get_title('Имя Гостя')}*\n"
        f"📊 Частота: {get_select('Частота визитов')}\n"
        f"🪄 Кальян: {get_text('Кальян — вкус и крепость')}\n"
        f"🍹 Напитки: {get_text('Напитки — предпочтения')}\n"
        f"⭐ Важно: {get_text('Что важно для гостя')}\n"
    )

    # Последние 3 визита
    visits_res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_VISITS_DB_ID}/query",
        headers=HEADERS,
        json={
            "filter": {
                "property": "Гость",
                "relation": {"contains": guest_page_id}
            },
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

    await update.message.reply_text(text, parse_mode="Markdown")

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_guest))
app.run_polling()
