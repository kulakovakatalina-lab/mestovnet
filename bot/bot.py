"""
Телеграм-бот «Местов.Нет»: подборки живой музыки Крыма.

Пользователь выбирает жанры, города и частоту — бот по расписанию
присылает подборку ссылок на события с https://mestov.net.

Данные берутся напрямую с сайта (events.json + settings.json), маппинг
жанров и городов повторяет логику genre.html — бот всегда показывает
ровно то же, что и сайт.

Запуск: python bot.py  (нужна переменная окружения BOT_TOKEN)
"""
import html
import logging
import os
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()  # подхватывает bot/.env при локальном запуске
except ImportError:
    pass

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("mestov-bot")

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------
SITE = "https://mestov.net"
EVENTS_URL = f"{SITE}/events.json"
SETTINGS_URL = f"{SITE}/settings.json"
TZ = ZoneInfo("Europe/Simferopol")  # время Крыма (МСК, UTC+3)
# Telegram ID администратора — кому доступна /stats. Можно задать через env.
ADMIN_ID = int(os.environ.get("ADMIN_ID", "267459702"))
DATA_DIR = os.environ.get("DATA_DIR", ".")
PERSIST_PATH = os.path.join(DATA_DIR, "bot_data.pickle")
MAX_EVENTS = 25  # сколько событий максимум в одной подборке

# Маппинг «сырых» жанров в канонические — копия GENRE_MAP из genre.html
GENRE_MAP = {
    "джаз": "jazz",
    "рок": "rock", "русский рок": "rock", "панк-рок": "rock",
    "инди-рок": "rock", "метал": "rock", "инди": "rock", "авторская": "rock",
    "классика": "classic", "хоровая": "classic", "медитативная": "classic",
    "поп": "pop", "поп-рок": "pop", "лаунж": "pop", "хип-хоп": "pop",
    "каверы": "pop", "юмор": "pop", "шоу": "pop", "интерактив": "pop",
    "этно": "folk", "фолк-метал": "folk", "народная": "folk",
    "блюз": "blues",
}
GENRE_LABELS = {
    "jazz": "Джаз", "rock": "Рок", "folk": "Фолк",
    "blues": "Блюз", "classic": "Классика", "pop": "Поп",
}
GENRE_ORDER = ["jazz", "rock", "folk", "blues", "classic", "pop"]

CITY_MAP = {
    "Севастополь": "sevastopol", "Симферополь": "simferopol", "Ялта": "yalta",
    "Судак": "sudak", "Керчь": "kerch", "Коктебель": "koktebel",
    "Бахчисарай": "bakhchisaray", "Евпатория": "evpatoria", "Крым": "all",
}
CITY_LABELS = {
    "sevastopol": "Севастополь", "simferopol": "Симферополь", "yalta": "Ялта",
    "sudak": "Судак", "kerch": "Керчь", "koktebel": "Коктебель",
    "bakhchisaray": "Бахчисарай", "evpatoria": "Евпатория",
}
CITY_ORDER = ["sevastopol", "simferopol", "yalta", "evpatoria",
              "kerch", "sudak", "koktebel", "bakhchisaray"]

MONTHS_GEN = ["янв", "фев", "мар", "апр", "мая", "июн",
              "июл", "авг", "сен", "окт", "ноя", "дек"]
DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAY_LABELS = ["Понедельник", "Вторник", "Среда", "Четверг",
                  "Пятница", "Суббота", "Воскресенье"]
WEEKDAY_PLURAL = ["понедельникам", "вторникам", "средам", "четвергам",
                  "пятницам", "субботам", "воскресеньям"]
SEND_TIME = "16:20"  # фиксированное время рассылки (по Крыму)


def map_genre(raw):
    return GENRE_MAP.get((raw or "").lower(), "pop")


def map_city(raw):
    return CITY_MAP.get(raw, "all")


# ---------------------------------------------------------------------------
# Загрузка и фильтрация событий
# ---------------------------------------------------------------------------
async def fetch_events():
    """Скачивает события с сайта, применяет settings.json, возвращает
    список будущих событий с проставленными canonical genre/city."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        ev_resp = await client.get(EVENTS_URL)
        ev_resp.raise_for_status()
        data = ev_resp.json()
        try:
            settings = (await client.get(SETTINGS_URL)).json()
        except Exception:
            settings = {}

    hidden = set(settings.get("hidden", []))
    ov_names = settings.get("names", {})
    ov_times = settings.get("times", {})
    ov_prices = settings.get("prices", {})
    ov_cities = settings.get("cities", {})
    ov_venues = settings.get("venues", {})
    ov_genres = settings.get("genres", {})

    today = datetime.now(TZ).date()
    events = []
    for e in data:
        url = e.get("source_url", "")
        if url in hidden or not e.get("date"):
            continue
        raw_genre = ov_genres.get(url, e.get("genre"))
        raw_city = ov_cities.get(url, e.get("source_city"))
        try:
            ev_date = date.fromisoformat(e["date"])
        except ValueError:
            continue
        if ev_date < today:
            continue
        events.append({
            "id": e.get("id"),
            "date": ev_date,
            "time": ov_times.get(url, e.get("time")) or "",
            "artist": ov_names.get(url, e.get("artist")) or "Концерт",
            "venue": ov_venues.get(url, e.get("venue")) or "",
            "price": ov_prices.get(url, e.get("price")) or "",
            "source_city": raw_city,
            "genre": map_genre(raw_genre),
            "city": map_city(raw_city),
        })
    events.sort(key=lambda x: (x["date"], x["time"]))
    return events


def filter_events(events, genres, cities, horizon_days=None):
    """genres / cities — списки canonical-ключей или ['all']."""
    today = datetime.now(TZ).date()
    all_genres = not genres or "all" in genres
    all_cities = not cities or "all" in cities
    out = []
    for e in events:
        if not all_genres and e["genre"] not in genres:
            continue
        # Крым-wide события (city == 'all') показываем всегда
        if not all_cities and e["city"] != "all" and e["city"] not in cities:
            continue
        if horizon_days is not None and (e["date"] - today).days > horizon_days:
            continue
        out.append(e)
    return out


def price_text(p):
    low = (p or "").lower()
    if not p or "бесплат" in low or low == "вход свободный":
        return "бесплатно"
    return p


def format_digest(events, genres, cities):
    """Возвращает текст подборки (HTML)."""
    if not events:
        return ("На ближайшую неделю по твоим фильтрам событий не нашлось 🤷\n"
                "Загляни позже или измени подписку — /start\n\n"
                f'👉 <a href="{SITE}">Больше на Местов.Нет</a>')

    g_label = ("любые жанры" if not genres or "all" in genres
               else ", ".join(GENRE_LABELS[g] for g in GENRE_ORDER if g in genres))
    c_label = ("весь Крым" if not cities or "all" in cities
               else ", ".join(CITY_LABELS[c] for c in CITY_ORDER if c in cities))

    lines = [f"🎶 <b>Подборка живой музыки</b>",
             f"<i>{html.escape(g_label)} · {html.escape(c_label)}</i>", ""]

    shown = events[:MAX_EVENTS]
    for e in shown:
        d = e["date"]
        when = f"{d.day:02d} {MONTHS_GEN[d.month - 1]} ({DOW[d.weekday()]})"
        if e["time"]:
            when += f" {e['time']}"
        artist = html.escape(e["artist"])
        place_bits = []
        city_name = e["source_city"] or ""
        if city_name:
            place_bits.append(html.escape(city_name))
        if e["venue"]:
            place_bits.append(html.escape(e["venue"]))
        place_bits.append(price_text(e["price"]))
        place = " · ".join(place_bits)
        link = f"{SITE}/event.html?id={e['id']}"
        lines.append(f'📅 {when} — <a href="{link}"><b>{artist}</b></a>\n'
                     f"📍 {place}\n")

    if len(events) > MAX_EVENTS:
        lines.append(f"…и ещё {len(events) - MAX_EVENTS}. "
                     f'Все события — <a href="{SITE}">Местов.Нет</a>')

    # ссылки на жанровые страницы сайта
    if genres and "all" not in genres:
        glinks = " · ".join(
            f'<a href="{SITE}/genre.html?g={g}">{GENRE_LABELS[g]}</a>'
            for g in GENRE_ORDER if g in genres)
        lines.append(f"\n🔎 На сайте: {glinks}")

    lines.append(f'\n👉 <a href="{SITE}">Больше на Местов.Нет</a>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Хранилище подписок (в bot_data, переживает рестарты через PicklePersistence)
# ---------------------------------------------------------------------------
def get_subs(context):
    return context.application.bot_data.setdefault("subs", {})


def get_sub(context, chat_id):
    return get_subs(context).get(chat_id)


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
# Постоянная клавиатура под полем ввода — всегда доступна
BTN_MENU = "☰ Меню"
BTN_DIGEST = "📩 Подборка сейчас"
MAIN_KB = ReplyKeyboardMarkup(
    [[BTN_MENU, BTN_DIGEST]], resize_keyboard=True, is_persistent=True)


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Настроить подписку", callback_data="cfg:start")],
        [InlineKeyboardButton("📩 Прислать подборку сейчас", callback_data="digest:now")],
        [InlineKeyboardButton("👀 Моя подписка", callback_data="sub:show")],
        [InlineKeyboardButton("🔕 Отписаться", callback_data="sub:stop")],
    ])


def genres_kb(selected):
    rows, row = [], []
    for g in GENRE_ORDER:
        mark = "✅ " if g in selected else ""
        row.append(InlineKeyboardButton(f"{mark}{GENRE_LABELS[g]}",
                                        callback_data=f"g:{g}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    all_mark = "✅ " if "all" in selected else ""
    rows.append([InlineKeyboardButton(f"{all_mark}Все жанры", callback_data="g:all")])
    rows.append([InlineKeyboardButton("Далее ▶", callback_data="g:next")])
    return InlineKeyboardMarkup(rows)


def cities_kb(selected):
    rows, row = [], []
    for c in CITY_ORDER:
        mark = "✅ " if c in selected else ""
        row.append(InlineKeyboardButton(f"{mark}{CITY_LABELS[c]}",
                                        callback_data=f"c:{c}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    all_mark = "✅ " if "all" in selected else ""
    rows.append([InlineKeyboardButton(f"{all_mark}Весь Крым", callback_data="c:all")])
    rows.append([InlineKeyboardButton("Далее ▶", callback_data="c:next")])
    return InlineKeyboardMarkup(rows)


def freq_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Каждый день", callback_data="f:daily")],
        [InlineKeyboardButton("🗓 Раз в неделю", callback_data="f:weekly")],
        [InlineKeyboardButton("✋ Только по запросу", callback_data="f:ondemand")],
    ])


def weekday_kb():
    rows = [[InlineKeyboardButton(WEEKDAY_LABELS[i], callback_data=f"w:{i}")]
            for i in range(7)]
    return InlineKeyboardMarkup(rows)


async def finish_message(q, sub):
    await q.edit_message_text(
        summary_text(sub) + "\n\nГотово! Первая подборка придёт по расписанию. "
        "Прислать сейчас — /digest",
        parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------
WELCOME = (
    "Привет! Я бот <b>Местов.Нет</b> 🎸\n"
    "Присылаю подборки живой музыки Крыма под твой вкус.\n\n"
    "Выбери жанры, города и как часто слать — а дальше я сам.\n"
    "Источник: " + SITE
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # закрепляем постоянную клавиатуру (☰ Меню / Подборка сейчас)
    await update.effective_message.reply_html(WELCOME, reply_markup=MAIN_KB)
    await update.effective_message.reply_text(
        "Что хочешь сделать?", reply_markup=main_menu_kb())


async def on_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий постоянной клавиатуры."""
    text = (update.effective_message.text or "").strip()
    if text == BTN_DIGEST:
        await send_digest(context, update.effective_chat.id, on_demand=True,
                          reply_to=update.effective_message)
    else:  # ☰ Меню или любой другой текст
        await update.effective_message.reply_text(
            "Что хочешь сделать?", reply_markup=main_menu_kb())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_html(
        "Команды:\n"
        "/start — меню и настройка подписки\n"
        "/digest — прислать подборку прямо сейчас\n"
        "/stop — отписаться от рассылки\n",
        reply_markup=main_menu_kb())


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_digest(context, update.effective_chat.id, on_demand=True,
                      reply_to=update.effective_message)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("Команда доступна только администратору.")
        return
    bd = context.application.bot_data
    subs = bd.get("subs", {})
    total_sub = bd.get("total_subscribed", 0)
    total_unsub = bd.get("total_unsubscribed", 0)

    freq_count = {"daily": 0, "weekly": 0, "ondemand": 0}
    genre_count = {g: 0 for g in GENRE_ORDER}
    genre_all = 0
    city_count = {c: 0 for c in CITY_ORDER}
    city_all = 0
    for s in subs.values():
        freq_count[s.get("freq", "ondemand")] = freq_count.get(s.get("freq"), 0) + 1
        if "all" in s["genres"] or not s["genres"]:
            genre_all += 1
        else:
            for g in s["genres"]:
                if g in genre_count:
                    genre_count[g] += 1
        if "all" in s["cities"] or not s["cities"]:
            city_all += 1
        else:
            for c in s["cities"]:
                if c in city_count:
                    city_count[c] += 1

    lines = [
        "📊 <b>Статистика</b>", "",
        f"👥 Активных подписчиков: <b>{len(subs)}</b>",
        f"➕ Всего подписалось: {total_sub}",
        f"➖ Всего отписалось: {total_unsub}", "",
        "<b>По частоте:</b>",
        f"• каждый день: {freq_count['daily']}",
        f"• раз в неделю: {freq_count['weekly']}",
        f"• по запросу: {freq_count['ondemand']}", "",
        "<b>По жанрам:</b>",
        f"• любые: {genre_all}",
    ]
    lines += [f"• {GENRE_LABELS[g]}: {genre_count[g]}" for g in GENRE_ORDER]
    lines += ["", "<b>По городам:</b>", f"• весь Крым: {city_all}"]
    lines += [f"• {CITY_LABELS[c]}: {city_count[c]}" for c in CITY_ORDER]
    await update.effective_message.reply_html("\n".join(lines))


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if record_unsubscribe(context, chat_id):
        await update.effective_message.reply_text("Отписал. Вернуться — /start")
    else:
        await update.effective_message.reply_text("У тебя и не было подписки. /start")


# ---------------------------------------------------------------------------
# Обработка инлайн-кнопок
# ---------------------------------------------------------------------------
def toggle(selected, value):
    """Мультивыбор с взаимоисключающим 'all'."""
    if value == "all":
        return ["all"] if "all" not in selected else []
    selected = [x for x in selected if x != "all"]
    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)
    return selected


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat_id
    draft = context.chat_data.setdefault("draft", {})

    if data == "cfg:start":
        sub = get_sub(context, chat_id) or {}
        draft["genres"] = list(sub.get("genres", []))
        draft["cities"] = list(sub.get("cities", []))
        await q.edit_message_text(
            "Шаг 1/3. Какие <b>жанры</b> интересны? "
            "Можно несколько. Потом нажми «Далее».",
            parse_mode=ParseMode.HTML, reply_markup=genres_kb(draft["genres"]))
        return

    if data.startswith("g:"):
        val = data[2:]
        if val == "next":
            if not draft.get("genres"):
                await q.answer("Выбери хотя бы один жанр (или «Все жанры»)",
                               show_alert=True)
                return
            await q.edit_message_text(
                "Шаг 2/3. В каких <b>городах</b>? Можно несколько.",
                parse_mode=ParseMode.HTML, reply_markup=cities_kb(draft["cities"]))
            return
        draft["genres"] = toggle(draft.get("genres", []), val)
        await q.edit_message_reply_markup(reply_markup=genres_kb(draft["genres"]))
        return

    if data.startswith("c:"):
        val = data[2:]
        if val == "next":
            if not draft.get("cities"):
                await q.answer("Выбери хотя бы один город (или «Весь Крым»)",
                               show_alert=True)
                return
            await q.edit_message_text(
                "Шаг 3/3. Как часто присылать подборку?",
                parse_mode=ParseMode.HTML, reply_markup=freq_kb())
            return
        draft["cities"] = toggle(draft.get("cities", []), val)
        await q.edit_message_reply_markup(reply_markup=cities_kb(draft["cities"]))
        return

    if data.startswith("f:"):
        freq = data[2:]
        draft["freq"] = freq
        if freq == "ondemand":
            save_and_finish(context, chat_id, draft)
            await q.edit_message_text(
                summary_text(get_sub(context, chat_id)) +
                "\n\nБуду ждать команды /digest 👌",
                parse_mode=ParseMode.HTML)
            return
        if freq == "weekly":
            await q.edit_message_text("В какой день недели присылать?",
                                      reply_markup=weekday_kb())
            return
        # daily — время фиксированное (16:20), сразу сохраняем
        save_and_finish(context, chat_id, draft)
        await finish_message(q, get_sub(context, chat_id))
        return

    if data.startswith("w:"):
        draft["weekday"] = int(data[2:])
        save_and_finish(context, chat_id, draft)
        await finish_message(q, get_sub(context, chat_id))
        return

    if data == "digest:now":
        await send_digest(context, chat_id, on_demand=True)
        return

    if data == "sub:show":
        sub = get_sub(context, chat_id)
        if sub:
            await q.edit_message_text(summary_text(sub),
                                      parse_mode=ParseMode.HTML,
                                      reply_markup=main_menu_kb())
        else:
            await q.edit_message_text("Подписки пока нет. Нажми «Настроить подписку».",
                                      reply_markup=main_menu_kb())
        return

    if data == "sub:stop":
        if record_unsubscribe(context, chat_id):
            await q.edit_message_text("Отписал. Вернуться — /start")
        else:
            await q.edit_message_text("Подписки и не было. /start")
        return


# ---------------------------------------------------------------------------
# Сохранение подписки + расписание
# ---------------------------------------------------------------------------
def save_and_finish(context, chat_id, draft):
    sub = {
        "genres": list(draft.get("genres", [])),
        "cities": list(draft.get("cities", [])),
        "freq": draft.get("freq", "ondemand"),
        "weekday": draft.get("weekday", 4),  # по умолчанию пятница
        "time": SEND_TIME,
    }
    subs = get_subs(context)
    if chat_id not in subs:  # новая подписка — считаем
        context.application.bot_data["total_subscribed"] = \
            context.application.bot_data.get("total_subscribed", 0) + 1
    subs[chat_id] = sub
    context.chat_data.pop("draft", None)
    schedule_sub(context.application, chat_id, sub)


def record_unsubscribe(context, chat_id):
    """Удаляет подписку, ведёт счётчик отписок. True, если была подписка."""
    if get_subs(context).pop(chat_id, None) is None:
        return False
    context.application.bot_data["total_unsubscribed"] = \
        context.application.bot_data.get("total_unsubscribed", 0) + 1
    unschedule(context.application, chat_id)
    return True


def summary_text(sub):
    g = ("любые" if "all" in sub["genres"] or not sub["genres"]
         else ", ".join(GENRE_LABELS[x] for x in GENRE_ORDER if x in sub["genres"]))
    c = ("весь Крым" if "all" in sub["cities"] or not sub["cities"]
         else ", ".join(CITY_LABELS[x] for x in CITY_ORDER if x in sub["cities"]))
    if sub["freq"] == "daily":
        when = f"каждый день в {sub['time']}"
    elif sub["freq"] == "weekly":
        when = f"по {WEEKDAY_PLURAL[sub['weekday']]} в {sub['time']}"
    else:
        when = "только по запросу (/digest)"
    return (f"📋 <b>Твоя подписка</b>\n"
            f"Жанры: {html.escape(g)}\n"
            f"Города: {html.escape(c)}\n"
            f"Частота: {when}")


def job_name(chat_id):
    return f"sub:{chat_id}"


def unschedule(app, chat_id):
    for job in app.job_queue.get_jobs_by_name(job_name(chat_id)):
        job.schedule_removal()


def schedule_sub(app, chat_id, sub):
    unschedule(app, chat_id)
    if sub["freq"] not in ("daily", "weekly"):
        return
    hh, mm = (int(x) for x in sub["time"].split(":"))
    run_at = time(hour=hh, minute=mm, tzinfo=TZ)
    days = tuple(range(7)) if sub["freq"] == "daily" else (sub["weekday"],)
    app.job_queue.run_daily(
        scheduled_digest, time=run_at, days=days,
        chat_id=chat_id, name=job_name(chat_id),
    )
    log.info("Scheduled %s: freq=%s time=%s days=%s",
             chat_id, sub["freq"], sub["time"], days)


# ---------------------------------------------------------------------------
# Отправка подборки
# ---------------------------------------------------------------------------
def _update_last_sent(context, chat_id):
    """Записывает текущее время как метку последней плановой рассылки."""
    sub = get_sub(context, chat_id)
    if sub:
        sub["last_sent_at"] = datetime.now(timezone.utc).isoformat()
        get_subs(context)[chat_id] = sub


async def send_digest(context, chat_id, on_demand=False, reply_to=None):
    sub = get_sub(context, chat_id)
    if not sub and not on_demand:
        return
    genres = sub["genres"] if sub else ["all"]
    cities = sub["cities"] if sub else ["all"]
    horizon = 7  # только события на ближайшую неделю

    try:
        events = await fetch_events()
    except Exception as e:
        log.exception("fetch failed")
        msg = "Не удалось загрузить события с сайта, попробуй позже 🙏"
        if reply_to:
            await reply_to.reply_text(msg)
        else:
            await context.bot.send_message(chat_id, msg)
        return

    filtered = filter_events(events, genres, cities, horizon_days=horizon)

    # Для плановых рассылок — только события, изменившиеся/появившиеся с прошлого раза
    new_only = not on_demand and sub is not None
    if new_only:
        last_sent_at = sub.get("last_sent_at")
        if last_sent_at:
            filtered = [e for e in filtered
                        if (e.get("updated_at") or "") >= last_sent_at]
            if not filtered:
                log.info("No new events for %s since %s, skipping", chat_id, last_sent_at)
                _update_last_sent(context, chat_id)
                return
        # Обновляем метку времени последней рассылки
        _update_last_sent(context, chat_id)

    text = format_digest(filtered, genres, cities)
    target = reply_to.reply_html if reply_to else None
    if target:
        await target(text, disable_web_page_preview=True)
    else:
        await context.bot.send_message(
            chat_id, text, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)


async def scheduled_digest(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await send_digest(context, chat_id, on_demand=False)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
async def post_init(app: Application):
    """Восстанавливаем расписание для всех подписок после рестарта."""
    subs = app.bot_data.get("subs", {})
    for chat_id, sub in subs.items():
        sub["time"] = SEND_TIME  # время рассылки всегда фиксированное
        schedule_sub(app, chat_id, sub)
    log.info("Restored %d subscriptions", len(subs))
    # команды бота (синяя кнопка «Меню» рядом с полем ввода)
    await app.bot.set_my_commands([
        BotCommand("start", "Меню и настройка подписки"),
        BotCommand("digest", "Прислать подборку сейчас"),
        BotCommand("stop", "Отписаться от рассылки"),
    ])


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан BOT_TOKEN (см. .env.example)")

    persistence = PicklePersistence(filepath=PERSIST_PATH)
    app = (Application.builder()
           .token(token)
           .persistence(persistence)
           .post_init(post_init)
           .build())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_menu_text))

    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
