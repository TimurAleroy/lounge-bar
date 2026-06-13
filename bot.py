import os
import requests
from collections import Counter
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

GUEST_NAME, SELECT_GUEST = range(2)

def query_all(db_id, body={}):
    results = []
    payload = {**body, "page_size": 100}
    while True:
        res = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=HEADERS,
            json=payload
        ).json()
        results.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        payload["start_cursor"] = res["next_cursor"]
    return results

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🛑 Остановлено. Напиши имя гостя чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove()
    )
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
        await show_guest(update, context, results[0])
        return ConversationHandler.END

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
        return ConversationHandler.END

async def select_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Никто из них":
        await update.message.reply_text("Напиши имя гостя:", reply_markup=ReplyKeyboardRemove())
        return GUEST_NAME

    for g in context.user_data.get("search_results", []):
        if g["name"] == text:
            res = requests.get(f"https://api.notion.com/v1/pages/{g['id']}", headers=HEADERS)
            guest = res.json()
            await show_guest(update, context, guest)
            return ConversationHandler.END

    await update.message.reply_text("Не понял выбор. Попробуй ещё раз.")
    return SELECT_GUEST

async def show_guest(update, context, guest):
    props = guest["properties"]
    guest_page_id = guest["id"]

    def get_text(prop):
        items = props.get(prop, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else "не указано"
    def get_title(prop):
        items = props.get(prop, {}).get("title", [])
        return items[0]["plain_text"] if items else "не указано"
    def get_select(prop):
        s = props.get(prop, {}).get("select")
        return s["name"] if s else "не указано"

    text = (
        f"👤 *{get_title('Имя Гостя')}*\n"
        f"📊 Частота: {get_select('Частота визитов')}\n"
        f"🪄 Кальян: {get_text('Кальян — вкус и крепость')}\n"
        f"🍹 Напитки: {get_text('Напитки — предпочтения')}\n"
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

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Собираю статистику, подожди секунду...")

    all_visits = query_all(NOTION_VISITS_DB_ID)
    all_guests = query_all(NOTION_DB_ID)

    this_month = date.today().strftime("%Y-%m")
    month_visits = []
    guest_visit_count = Counter()
    hookah_counter = Counter()
    drinks_counter = Counter()

    for v in all_visits:
        vp = v["properties"]
        d = vp.get("Дата", {}).get("date")
        visit_date = d["start"] if d else ""
        if visit_date.startswith(this_month):
            month_visits.append(v)

        relations = vp.get("Гость", {}).get("relation", [])
        if relations:
            guest_visit_count[relations[0]["id"]] += 1

        hookah_items = vp.get("Кальян", {}).get("rich_text", [])
        if hookah_items:
            hookah = hookah_items[0]["plain_text"].strip()
            if hookah and hookah != "—":
                hookah_counter[hookah] += 1

        drinks_items = vp.get("Напитки", {}).get("rich_text", [])
        if drinks_items:
            drink = drinks_items[0]["plain_text"].strip()
            if drink and drink != "—":
                drinks_counter[drink] += 1

    guest_names = {}
    for g in all_guests:
        gp = g["properties"]
        title = gp.get("Имя Гостя", {}).get("title", [])
        if title:
            guest_names[g["id"]] = title[0]["plain_text"]

    new_guests_month = sum(
        1 for g in all_guests if g.get("created_time", "").startswith(this_month)
    )

    top_guests = guest_visit_count.most_common(5)
    top_guests_text = ""
    for i, (gid, count) in enumerate(top_guests, 1):
        gname = guest_names.get(gid, "Неизвестный")
        top_guests_text += f"  {i}. {gname} — {count} визитов\n"

    top_hookah = hookah_counter.most_common(3)
    top_hookah_text = "".join(f"  {i}. {n} — {c}x\n" for i, (n, c) in enumerate(top_hookah, 1))

    top_drinks = drinks_counter.most_common(3)
    top_drinks_text = "".join(f"  {i}. {n} — {c}x\n" for i, (n, c) in enumerate(top_drinks, 1))

    text = (
        f"📊 *Статистика заведения*\n"
        f"_{date.today().strftime('%B %Y')}_\n\n"
        f"📅 Визитов в этом месяце: *{len(month_visits)}*\n"
        f"🆕 Новых гостей: *{new_guests_month}*\n"
        f"👥 Всего гостей в базе: *{len(all_guests)}*\n\n"
        f"🏆 *Топ гостей по визитам:*\n{top_guests_text or '  Нет данных'}\n"
        f"🪄 *Популярный кальян:*\n{top_hookah_text or '  Нет данных'}\n"
        f"🍹 *Популярные напитки:*\n{top_drinks_text or '  Нет данных'}"
    )

    await update.message.reply_text(text, parse_mode="Markdown")

conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, get_guest_name)],
    states={
        GUEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guest_name)],
        SELECT_GUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_guest)],
    },
    fallbacks=[
        CommandHandler("stop", stop),
        CommandHandler("cancel", stop),
    ],
)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("stats", stats))
app.add_handler(conv_handler)
app.run_polling()
