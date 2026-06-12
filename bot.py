import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]

async def search_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    body = {
        "filter": {
            "property": "Имя Гостя",
            "title": {"contains": name}
        }
    }

    res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=headers,
        json=body
    )

    results = res.json().get("results", [])

    if not results:
        await update.message.reply_text(f"❌ Гость «{name}» не найден. Проверьте имя.")
        return

    guest = results[0]["properties"]

    def get_text(prop):
        items = guest.get(prop, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else "не указано"

    def get_title(prop):
        items = guest.get(prop, {}).get("title", [])
        return items[0]["plain_text"] if items else "не указано"

    def get_date(prop):
        d = guest.get(prop, {}).get("date")
        return d["start"] if d else "не указана"

    def get_select(prop):
        s = guest.get(prop, {}).get("select")
        return s["name"] if s else "не указано"

    text = (
        f"👤 *{get_title('Имя Гостя')}*\n"
        f"📊 Частота: {get_select('Частота визитов')}\n"
        f"🗓 Последний визит: {get_date('Последний визит')}\n"
        f"🪄 Кальян: {get_text('Кальян — вкус и крепость')}\n"
        f"🍹 Напитки: {get_text('Напитки — предпочтения')}\n"
        f"⭐ Важно: {get_text('Что важно для гостя')}"
    )

    await update.message.reply_text(text, parse_mode="Markdown")

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_guest))
app.run_polling()
