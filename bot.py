"""
CityPostBot — помощник по постингу La Ciudad de los Sentidos
Отслеживает группы, напоминает о публикациях, ведёт статистику.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ─── Настройки ───────────────────────────────────────────────
TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # твой Telegram ID
DB_FILE = "data.json"
GAME_DATE = "13 июня"
DAYS_BETWEEN_POSTS = 4  # пауза между публикациями в одну группу
DEAD_THRESHOLD = 3       # после N публикаций без отклика — мёртвая

logging.basicConfig(level=logging.INFO)

# ─── Тексты объявлений ───────────────────────────────────────
ADS = {
    "A": """Привет! 👋

Учите испанский, но не хватает живой практики?

В разговорном клубе *La Ciudad de los Sentidos* играем в детективную игру на испанском — 5 человек, у каждого своя роль.

Следующие игры — *{game_date}*, уровень A1–A2.
Присоединяйтесь, чтобы выбрать удобное время 👉 {link}

Внутри клуба — тренажёр для подготовки к роли 🎮""",

    "B": """Привет! 👋

Живёте в Испании, но говорить по-испански всё ещё страшно?

*La Ciudad de los Sentidos* — разговорный клуб, где практика спрятана внутри детективной игры. 5 человек, у каждого роль, всё на испанском.

Следующие игры — *{game_date}*, уровень A1–A2.
Присоединяйтесь, чтобы выбрать удобное время 👉 {link}

Внутри клуба — тренажёр для подготовки к роли 🎮""",

    "C": """Привет! 👋

Испанский нужен уже сейчас — а говорить всё ещё страшно?

*La Ciudad de los Sentidos* — разговорный клуб, детективная игра на испанском. 5 человек, у каждого своя роль.

Следующие игры — *{game_date}*, уровень A1–A2.
Присоединяйтесь, чтобы выбрать удобное время 👉 {link}

Тренажёр для подготовки к роли — внутри клуба 🎮"""
}

# ─── База данных (JSON) ──────────────────────────────────────
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "groups": [],
        "publications": [],
        "link": "https://t.me/lacataciegas",
        "game_date": GAME_DATE
    }

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_next_ad_version(group_id: str, db: dict) -> str:
    """Возвращает следующую версию объявления по ротации A→B→C→A"""
    pubs = [p for p in db["publications"] if p["group_id"] == group_id]
    versions = ["A", "B", "C"]
    if not pubs:
        return "A"
    last_version = pubs[-1].get("version", "A")
    idx = versions.index(last_version)
    return versions[(idx + 1) % 3]

def get_group_status(group_id: str, db: dict) -> str:
    """Проверяет статус группы по откликам"""
    pubs = [p for p in db["publications"] if p["group_id"] == group_id]
    if not pubs:
        return "new"
    recent = pubs[-DEAD_THRESHOLD:]
    if len(recent) >= DEAD_THRESHOLD and all(not p.get("reaction") for p in recent):
        return "dead"
    return "active"

# ─── Команды ─────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID and ADMIN_ID != 0:
        return
    await update.message.reply_text(
        "👋 Привет! Я CityPostBot.\n\n"
        "Команды:\n"
        "/groups — список групп\n"
        "/add — добавить группу\n"
        "/post — получить текст для публикации\n"
        "/stats — статистика\n"
        "/setlink — изменить ссылку\n"
        "/setdate — изменить дату игры"
    )

async def show_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db["groups"]:
        await update.message.reply_text("Групп пока нет. Добавь через /add")
        return

    text = "📋 *Список групп:*\n\n"
    for g in db["groups"]:
        status = get_group_status(g["id"], db)
        emoji = {"new": "🔲", "active": "✅", "dead": "❌"}.get(status, "🔲")
        pubs = [p for p in db["publications"] if p["group_id"] == g["id"]]
        reactions = sum(1 for p in pubs if p.get("reaction"))
        text += (
            f"{emoji} *{g['name']}*\n"
            f"   📱 {g['platform']} | 🖼 {g['format']}\n"
            f"   🔗 {g.get('handle', '—')}\n"
            f"   📊 Публикаций: {len(pubs)} | Откликов: {reactions}\n\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Отправь данные группы в формате:\n\n"
        "`название | @handle | Telegram или Facebook | текст или картинка`\n\n"
        "Пример:\n"
        "`Испания чат СНГ | @spainchats | Telegram | текст`"
    )
    context.user_data["awaiting_group"] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_group"):
        parts = [p.strip() for p in update.message.text.split("|")]
        if len(parts) != 4:
            await update.message.reply_text("❌ Неверный формат. Попробуй снова через /add")
            context.user_data["awaiting_group"] = False
            return

        db = load_db()
        group_id = f"g{len(db['groups']) + 1}"
        db["groups"].append({
            "id": group_id,
            "name": parts[0],
            "handle": parts[1],
            "platform": parts[2],
            "format": parts[3]
        })
        save_db(db)
        context.user_data["awaiting_group"] = False
        await update.message.reply_text(f"✅ Группа *{parts[0]}* добавлена!", parse_mode="Markdown")

    elif context.user_data.get("awaiting_link"):
        db = load_db()
        db["link"] = update.message.text.strip()
        save_db(db)
        context.user_data["awaiting_link"] = False
        await update.message.reply_text(f"✅ Ссылка обновлена: {db['link']}")

    elif context.user_data.get("awaiting_date"):
        db = load_db()
        db["game_date"] = update.message.text.strip()
        save_db(db)
        context.user_data["awaiting_date"] = False
        await update.message.reply_text(f"✅ Дата игры обновлена: {db['game_date']}")

async def post_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    active_groups = [
        g for g in db["groups"]
        if get_group_status(g["id"], db) != "dead"
    ]
    if not active_groups:
        await update.message.reply_text("Нет активных групп. Добавь через /add")
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{'✅' if get_group_status(g['id'], db) == 'active' else '🔲'} {g['name']} ({g['platform']})",
            callback_data=f"post_{g['id']}"
        )]
        for g in active_groups
    ]
    await update.message.reply_text(
        "📢 Выбери группу для публикации:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_post_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.replace("post_", "")

    db = load_db()
    group = next((g for g in db["groups"] if g["id"] == group_id), None)
    if not group:
        await query.edit_message_text("Группа не найдена.")
        return

    version = get_next_ad_version(group_id, db)
    text = ADS[version].format(
        game_date=db.get("game_date", GAME_DATE),
        link=db.get("link", "https://t.me/lacataciegas")
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Отправила", callback_data=f"sent_{group_id}_{version}"),
            InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_{group_id}")
        ]
    ]

    await query.edit_message_text(
        f"📢 *{group['name']}* ({group['platform']})\n"
        f"Версия объявления: *{version}*\n"
        f"Формат: {group['format']}\n\n"
        f"{'─' * 30}\n\n"
        f"{text}\n\n"
        f"{'─' * 30}\n\n"
        f"Скопируй текст выше и опубликуй в группу.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, group_id, version = query.data.split("_")

    db = load_db()
    group = next((g for g in db["groups"] if g["id"] == group_id), None)

    # Записываем публикацию без отклика пока
    db["publications"].append({
        "group_id": group_id,
        "version": version,
        "date": datetime.now().isoformat(),
        "reaction": False
    })
    save_db(db)

    keyboard = [[
        InlineKeyboardButton("👍 Был отклик", callback_data=f"reaction_{group_id}_yes"),
        InlineKeyboardButton("👎 Тишина", callback_data=f"reaction_{group_id}_no")
    ]]

    await query.edit_message_text(
        f"✅ Записала публикацию в *{group['name'] if group else group_id}*\n\n"
        f"Был ли отклик на предыдущую публикацию в этой группе?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, group_id, result = query.data.split("_")

    db = load_db()
    # Обновляем последнюю публикацию этой группы
    group_pubs = [p for p in db["publications"] if p["group_id"] == group_id]
    if len(group_pubs) >= 2:
        prev = group_pubs[-2]
        prev["reaction"] = (result == "yes")
        save_db(db)

    status = get_group_status(group_id, db)
    if status == "dead":
        msg = "❌ Группа помечена как мёртвая — 3 публикации без отклика. Убрана из ротации."
    else:
        msg = "👍 Записала! Следующая публикация в эту группу — через 4 дня."

    await query.edit_message_text(msg)

async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏭ Пропустили. Возвращайся через /post")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    total = len(db["publications"])
    reactions = sum(1 for p in db["publications"] if p.get("reaction"))
    dead = sum(1 for g in db["groups"] if get_group_status(g["id"], db) == "dead")
    active = len(db["groups"]) - dead

    version_counts = {"A": 0, "B": 0, "C": 0}
    for p in db["publications"]:
        v = p.get("version", "A")
        version_counts[v] = version_counts.get(v, 0) + 1

    version_reactions = {"A": 0, "B": 0, "C": 0}
    for p in db["publications"]:
        if p.get("reaction"):
            v = p.get("version", "A")
            version_reactions[v] = version_reactions.get(v, 0) + 1

    text = (
        f"📊 *Статистика CityPostBot*\n\n"
        f"Групп всего: {len(db['groups'])}\n"
        f"Активных: {active} | Мёртвых: {dead}\n\n"
        f"Публикаций всего: {total}\n"
        f"С откликом: {reactions} ({round(reactions/total*100) if total else 0}%)\n\n"
        f"*По версиям:*\n"
        f"A: {version_counts['A']} публ. / {version_reactions['A']} откл.\n"
        f"B: {version_counts['B']} публ. / {version_reactions['B']} откл.\n"
        f"C: {version_counts['C']} публ. / {version_reactions['C']} откл.\n\n"
        f"🔗 Текущая ссылка: {db.get('link', '—')}\n"
        f"📅 Дата игры: {db.get('game_date', '—')}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def set_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь новую ссылку для объявлений:")
    context.user_data["awaiting_link"] = True

async def set_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь новую дату игры (например: 27 июня):")
    context.user_data["awaiting_date"] = True

# ─── Запуск ──────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("groups", show_groups))
    app.add_handler(CommandHandler("add", add_group_start))
    app.add_handler(CommandHandler("post", post_menu))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("setlink", set_link))
    app.add_handler(CommandHandler("setdate", set_date))

    app.add_handler(CallbackQueryHandler(handle_post_select, pattern="^post_"))
    app.add_handler(CallbackQueryHandler(handle_sent, pattern="^sent_"))
    app.add_handler(CallbackQueryHandler(handle_reaction, pattern="^reaction_"))
    app.add_handler(CallbackQueryHandler(handle_skip, pattern="^skip_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 CityPostBot запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
