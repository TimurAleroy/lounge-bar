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
CSI_SHEETS_ID = "1SOKanELXstuJ0W75fsWpbmYRibk-mWkHLF5XHz4KHYc"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

GUEST_NAME, SELECT_GUEST, AFTER_CARD, EDIT_CHOICE, EDIT_VALUE = range(5)

def query_all(db_id, body={}):
    results = []
    payload = {**body, "page_size": 100}
    while True:
        res = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=HEADERS, json=payload).json()
        results.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        payload["start_cursor"] = res["next_cursor"]
    return results

def get_csi_nps_data():
    url = f"https://docs.google.com/spreadsheets/d/{CSI_SHEETS_ID}/gviz/tq?tqx=out:csv&sheet=Sheet1"
    res = requests.get(url)
    if res.status_code != 200:
        return None
    lines = res.text.strip().split("\n")
    if len(lines) < 2:
        return None
    rows = []
    for line in lines[1:]:
        cols = line.replace('"', '').split(",")
        if len(cols) >= 7:
            rows.append(cols)
    if not rows:
        return None
    this_month = date.today().strftime("%m.%Y")
    month_rows = [r for r in rows if r[0].endswith(this_month[:2] + "." + this_month[3:])]
    use_rows = month_rows if month_rows else rows
    total = len(use_rows)
    if total == 0:
        return None

    def avg(col_idx):
        vals = []
        for r in use_rows:
            try:
                vals.append(float(r[col_idx].strip().replace(",", ".")))
            except:
                pass
        return round(sum(vals) / len(vals), 1) if vals else 0

    promoters = neutrals = critics = 0
    for r in use_rows:
        try:
            score = float(r[6].strip().replace(",", "."))
            if score >= 9: promoters += 1
            elif score >= 7: neutrals += 1
            else: critics += 1
        except:
            pass
    nps = round(((promoters - critics) / total) * 100) if total > 0 else 0

    comments = []
    for r in use_rows:
        if len(r) > 7 and r[7].strip():
            comments.append(r[7].strip())

    return {
        "total": total, "mood": avg(1), "hookah": avg(2), "drinks": avg(3), "food": avg(4), "team": avg(5),
        "nps": nps, "promoters": promoters, "neutrals": neutrals, "critics": critics,
        "comments": comments[-3:], "period": "этот месяц" if month_rows else "всё время"
    }

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

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Собираю статистику...")

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
            h = hookah_items[0]["plain_text"].strip()
            if h and h != "—":
                hookah_counter[h] += 1
        drinks_items = vp.get("Напитки", {}).get("rich_text", [])
        if drinks_items:
            dr = drinks_items[0]["plain_text"].strip()
            if dr and dr != "—":
                drinks_counter[dr] += 1

    guest_names = {}
    for g in all_guests:
        title = g["properties"].get("Имя Гостя", {}).get("title", [])
        if title:
            guest_names[g["id"]] = title[0]["plain_text"]

    new_guests_month = sum(1 for g in all_guests if g.get("created_time", "").startswith(this_month))

    top_guests_text = ""
    for i, (gid, count) in enumerate(guest_visit_count.most_common(5), 1):
        top_guests_text += f"  {i}. {guest_names.get(gid, '?')} — {count} визитов\n"

    top_hookah_text = "".join(f"  {i}. {n} — {c}x\n" for i, (n, c) in enumerate(hookah_counter.most_common(3), 1))
    top_drinks_text = "".join(f"  {i}. {n} — {c}x\n" for i, (n, c) in enumerate(drinks_counter.most_common(3), 1))

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

    csi = get_csi_nps_data()
    if csi:
        def bar(score):
            filled = int(score / 2)
            return "🟩" * filled + "⬜" * (5 - filled)

        text += f"\n\n━━━━━━━━━━━━━━\n"
        text += f"⭐ *CSI / NPS — {csi['period']}* ({csi['total']} отзывов)\n\n"
        text += f"😊 Вечер в целом: *{csi['mood']}/10* {bar(csi['mood'])}\n"
        text += f"🪄 Кальян: *{csi['hookah']}/10* {bar(csi['hookah'])}\n"
        text += f"🍹 Напитки: *{csi['drinks']}/10* {bar(csi['drinks'])}\n"
        text += f"🍽 Еда: *{csi['food']}/10* {bar(csi['food'])}\n"
        text += f"👨‍💼 Команда: *{csi['team']}/10* {bar(csi['team'])}\n\n"
        text += f"🎯 *NPS: {csi['nps']}*\n"
        text += f"  👍 Промоутеры: {csi['promoters']}\n"
        text += f"  😐 Нейтралы: {csi['neutrals']}\n"
        text += f"  👎 Критики: {csi['critics']}\n"
        if csi['comments']:
            text += f"\n💬 *Последние отзывы:*\n"
            for c in csi['comments']:
                text += f"  • {c}\n"
    else:
        text += "\n\n⭐ *CSI/NPS:* нет данных"

    await update.message.reply_text(text, parse_mode="Markdown")

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
app.add_handler(CommandHandler("stats", stats))
app.add_handler(conv_handler)
app.run_polling()
