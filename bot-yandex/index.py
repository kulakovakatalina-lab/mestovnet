# -*- coding: utf-8 -*-
"""
Телеграм-бот «Местов.Нет» для Yandex Cloud Functions.

Бесплатная serverless-версия:
  • webhook  — Telegram шлёт апдейты на публичный URL функции;
  • таймер   — триггер будит функцию в 13:20 UTC (16:20 Крым) для рассылки;
  • хранилище — подписки лежат в Object Storage (S3) как JSON-объекты.

Точка входа: index.handler

Переменные окружения (задаются в настройках функции):
  BOT_TOKEN, WEBHOOK_SECRET, ADMIN_ID,
  BUCKET                — имя бакета Object Storage,
  AWS_ACCESS_KEY_ID,
  AWS_SECRET_ACCESS_KEY — статический ключ сервисного аккаунта (для S3).
"""
import base64
import json
import os
import socket
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3

# В Yandex Cloud Functions исходящий IPv6 не работает, а api.telegram.org
# имеет IPv6-адрес — из-за этого соединение висит до таймаута. Принудительно
# используем только IPv4 для всех исходящих соединений.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only(host, *args, **kwargs):
    res = _orig_getaddrinfo(host, *args, **kwargs)
    ipv4 = [r for r in res if r[0] == socket.AF_INET]
    return ipv4 or res


socket.getaddrinfo = _ipv4_only

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------
TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "267459702"))
BUCKET = os.environ["BUCKET"]

SITE = "https://mestov.net"
EVENTS_URL = f"{SITE}/events.json"
SETTINGS_URL = f"{SITE}/settings.json"
API = f"https://api.telegram.org/bot{TOKEN}/"
CRIMEA_TZ = timezone(timedelta(hours=3))
MAX_EVENTS = 25
HORIZON_DAYS = 7

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
GENRE_LABELS = {"jazz": "Джаз", "rock": "Рок", "folk": "Фолк",
                "blues": "Блюз", "classic": "Классика", "pop": "Поп"}
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

BTN_MENU = "☰ Меню"
BTN_DIGEST = "📩 Подборка сейчас"


def map_genre(raw):
    return GENRE_MAP.get((raw or "").lower(), "pop")


def map_city(raw):
    return CITY_MAP.get(raw, "all")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def crimea_today():
    return datetime.now(CRIMEA_TZ).date()


# ---------------------------------------------------------------------------
# Telegram API (через urllib, без лишних зависимостей)
# ---------------------------------------------------------------------------
def tg(method, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        API + method, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except Exception as e:
        print("tg error:", method, e)
        return None


def send(chat_id, text, reply_markup=None, html=True):
    p = {"chat_id": chat_id, "text": text,
         "link_preview_options": {"is_disabled": True}}
    if html:
        p["parse_mode"] = "HTML"
    if reply_markup is not None:
        p["reply_markup"] = reply_markup
    return tg("sendMessage", **p)


def edit_text(chat_id, msg_id, text, reply_markup=None, html=True):
    p = {"chat_id": chat_id, "message_id": msg_id, "text": text,
         "link_preview_options": {"is_disabled": True}}
    if html:
        p["parse_mode"] = "HTML"
    if reply_markup is not None:
        p["reply_markup"] = reply_markup
    return tg("editMessageText", **p)


def edit_markup(chat_id, msg_id, reply_markup):
    return tg("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
              reply_markup=reply_markup)


def answer_cb(cb_id, text=None, alert=False):
    p = {"callback_query_id": cb_id}
    if text:
        p["text"] = text
        p["show_alert"] = alert
    return tg("answerCallbackQuery", **p)


# ---------------------------------------------------------------------------
# Хранилище (Object Storage / S3)
# ---------------------------------------------------------------------------
s3 = boto3.client("s3", endpoint_url="https://storage.yandexcloud.net",
                  region_name="ru-central1")


def s3_get(key, default=None):
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        return default


def s3_put(key, value):
    s3.put_object(Bucket=BUCKET, Key=key,
                  Body=json.dumps(value, ensure_ascii=False).encode())


def s3_del(key):
    try:
        s3.delete_object(Bucket=BUCKET, Key=key)
    except Exception:
        pass


def get_sub(chat_id):
    return s3_get(f"sub/{chat_id}.json")


def set_sub(chat_id, sub):
    s3_put(f"sub/{chat_id}.json", sub)


def del_sub(chat_id):
    s3_del(f"sub/{chat_id}.json")


def get_draft(chat_id):
    return s3_get(f"draft/{chat_id}.json",
                  {"genres": [], "cities": [], "freq": "ondemand", "weekday": 4})


def set_draft(chat_id, draft):
    s3_put(f"draft/{chat_id}.json", draft)


def iter_subs():
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix="sub/"):
        for item in page.get("Contents", []):
            key = item["Key"]
            chat_id = int(key[len("sub/"):-len(".json")])
            sub = s3_get(key)
            if sub:
                yield chat_id, sub


def bump_counter(name):
    stats = s3_get("stats.json", {})
    stats[name] = stats.get(name, 0) + 1
    s3_put("stats.json", stats)


def get_counter(name):
    return s3_get("stats.json", {}).get(name, 0)


# ---------------------------------------------------------------------------
# События: загрузка, фильтр, форматирование
# ---------------------------------------------------------------------------
def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mestov-bot"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def fetch_events():
    data = http_json(EVENTS_URL)
    try:
        settings = http_json(SETTINGS_URL)
    except Exception:
        settings = {}
    hidden = set(settings.get("hidden", []))
    ov_names = settings.get("names", {})
    ov_times = settings.get("times", {})
    ov_prices = settings.get("prices", {})
    ov_cities = settings.get("cities", {})
    ov_venues = settings.get("venues", {})
    ov_genres = settings.get("genres", {})
    today = crimea_today().isoformat()
    out = []
    for e in data:
        url = e.get("source_url", "")
        date = e.get("date")
        if url in hidden or not date or date < today:
            continue
        raw_genre = ov_genres.get(url, e.get("genre"))
        raw_city = ov_cities.get(url, e.get("source_city"))
        out.append({
            "id": e.get("id"),
            "date": date,
            "time": ov_times.get(url, e.get("time")) or "",
            "artist": ov_names.get(url, e.get("artist")) or "Концерт",
            "venue": ov_venues.get(url, e.get("venue")) or "",
            "price": ov_prices.get(url, e.get("price")) or "",
            "source_city": raw_city or "",
            "genre": map_genre(raw_genre),
            "city": map_city(raw_city),
        })
    out.sort(key=lambda x: (x["date"], x["time"]))
    return out


def filter_events(events, genres, cities):
    today = crimea_today()
    horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
    today_iso = today.isoformat()
    all_g = not genres or "all" in genres
    all_c = not cities or "all" in cities
    out = []
    for e in events:
        if not all_g and e["genre"] not in genres:
            continue
        if not all_c and e["city"] != "all" and e["city"] not in cities:
            continue
        if today_iso <= e["date"] <= horizon:
            out.append(e)
    return out


def price_text(p):
    low = (p or "").lower()
    if not p or "бесплат" in low or low == "вход свободный":
        return "бесплатно"
    return p


def format_digest(events, genres, cities):
    if not events:
        return ("На ближайшую неделю по твоим фильтрам событий не нашлось 🤷\n"
                "Загляни позже или измени подписку — /start\n\n"
                f'👉 <a href="{SITE}">Больше на Местов.Нет</a>')
    g_label = ("любые жанры" if not genres or "all" in genres
               else ", ".join(GENRE_LABELS[g] for g in GENRE_ORDER if g in genres))
    c_label = ("весь Крым" if not cities or "all" in cities
               else ", ".join(CITY_LABELS[c] for c in CITY_ORDER if c in cities))
    lines = ["🎶 <b>Подборка живой музыки</b>",
             f"<i>{esc(g_label)} · {esc(c_label)}</i>", ""]
    for e in events[:MAX_EVENTS]:
        y, m, d = (int(x) for x in e["date"].split("-"))
        wd = datetime(y, m, d).weekday()
        when = f"{d:02d} {MONTHS_GEN[m - 1]} ({DOW[wd]})"
        if e["time"]:
            when += f" {e['time']}"
        place = " · ".join(esc(x) for x in
                           [e["source_city"], e["venue"], price_text(e["price"])] if x)
        link = f"{SITE}/event/{e['id']}"
        lines.append(f'📅 {when} — <a href="{link}"><b>{esc(e["artist"])}</b></a>\n'
                     f"📍 {place}\n")
    if len(events) > MAX_EVENTS:
        lines.append(f"…и ещё {len(events) - MAX_EVENTS}. "
                     f'Все события — <a href="{SITE}">Местов.Нет</a>')
    if genres and "all" not in genres:
        glinks = " · ".join(
            f'<a href="{SITE}/genres/{g}.html">{GENRE_LABELS[g]}</a>'
            for g in GENRE_ORDER if g in genres)
        lines.append(f"\n🔎 На сайте: {glinks}")
    lines.append(f'\n👉 <a href="{SITE}">Больше на Местов.Нет</a>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
def btn(text, data):
    return {"text": text, "callback_data": data}


MAIN_KB = {"keyboard": [[{"text": BTN_MENU}, {"text": BTN_DIGEST}]],
           "resize_keyboard": True, "is_persistent": True}


def main_menu_kb():
    return {"inline_keyboard": [
        [btn("✏️ Настроить подписку", "cfg:start")],
        [btn("📩 Прислать подборку сейчас", "digest:now")],
        [btn("👀 Моя подписка", "sub:show")],
        [btn("🔕 Отписаться", "sub:stop")],
    ]}


def genres_kb(selected):
    rows, row = [], []
    for g in GENRE_ORDER:
        mark = "✅ " if g in selected else ""
        row.append(btn(f"{mark}{GENRE_LABELS[g]}", f"g:{g}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn(("✅ " if "all" in selected else "") + "Все жанры", "g:all")])
    rows.append([btn("Далее ▶", "g:next")])
    return {"inline_keyboard": rows}


def cities_kb(selected):
    rows, row = [], []
    for c in CITY_ORDER:
        mark = "✅ " if c in selected else ""
        row.append(btn(f"{mark}{CITY_LABELS[c]}", f"c:{c}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn(("✅ " if "all" in selected else "") + "Весь Крым", "c:all")])
    rows.append([btn("Далее ▶", "c:next")])
    return {"inline_keyboard": rows}


def freq_kb():
    return {"inline_keyboard": [
        [btn("📅 Каждый день", "f:daily")],
        [btn("🗓 Раз в неделю", "f:weekly")],
        [btn("✋ Только по запросу", "f:ondemand")],
    ]}


def weekday_kb():
    return {"inline_keyboard": [[btn(WEEKDAY_LABELS[i], f"w:{i}")] for i in range(7)]}


def toggle(selected, value):
    if value == "all":
        return ["all"] if "all" not in selected else []
    selected = [x for x in selected if x != "all"]
    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)
    return selected


def summary_text(sub):
    g = ("любые" if "all" in sub["genres"] or not sub["genres"]
         else ", ".join(GENRE_LABELS[x] for x in GENRE_ORDER if x in sub["genres"]))
    c = ("весь Крым" if "all" in sub["cities"] or not sub["cities"]
         else ", ".join(CITY_LABELS[x] for x in CITY_ORDER if x in sub["cities"]))
    if sub["freq"] == "daily":
        when = "каждый день в 16:20"
    elif sub["freq"] == "weekly":
        when = f"по {WEEKDAY_PLURAL[sub['weekday']]} в 16:20"
    else:
        when = "только по запросу (/digest)"
    return (f"📋 <b>Твоя подписка</b>\nЖанры: {esc(g)}\n"
            f"Города: {esc(c)}\nЧастота: {when}")


# ---------------------------------------------------------------------------
# Логика бота
# ---------------------------------------------------------------------------
WELCOME = (
    "Привет! Я бот <b>Местов.Нет</b> 🎸\n"
    "Присылаю подборки живой музыки Крыма под твой вкус.\n\n"
    "Выбери жанры, города и как часто слать — а дальше я сам.\n"
    f"Источник: {SITE}")


def send_digest(chat_id, sub):
    genres = sub["genres"] if sub else ["all"]
    cities = sub["cities"] if sub else ["all"]
    try:
        events = fetch_events()
    except Exception as e:
        print("fetch failed:", e)
        send(chat_id, "Не удалось загрузить события с сайта, попробуй позже 🙏")
        return
    send(chat_id, format_digest(filter_events(events, genres, cities), genres, cities))


def finish_sub(chat_id, msg_id, draft):
    if get_sub(chat_id) is None:
        bump_counter("total_subscribed")
    sub = {"genres": draft["genres"], "cities": draft["cities"],
           "freq": draft["freq"], "weekday": draft.get("weekday", 4)}
    set_sub(chat_id, sub)
    s3_del(f"draft/{chat_id}.json")
    tail = ("\n\nБуду ждать команды /digest 👌" if sub["freq"] == "ondemand"
            else "\n\nГотово! Первая подборка придёт по расписанию. Прислать сейчас — /digest")
    edit_text(chat_id, msg_id, summary_text(sub) + tail)


def on_command(chat_id, user_id, text):
    cmd = text.split()[0].lstrip("/").split("@")[0]
    if cmd == "start":
        send(chat_id, WELCOME, reply_markup=MAIN_KB)
        send(chat_id, "Что хочешь сделать?", reply_markup=main_menu_kb(), html=False)
    elif cmd == "help":
        send(chat_id, "Команды:\n/start — меню\n/digest — подборка сейчас\n/stop — отписаться",
             reply_markup=main_menu_kb(), html=False)
    elif cmd == "digest":
        send_digest(chat_id, get_sub(chat_id))
    elif cmd == "stop":
        if get_sub(chat_id):
            del_sub(chat_id)
            bump_counter("total_unsubscribed")
            send(chat_id, "Отписал. Вернуться — /start", html=False)
        else:
            send(chat_id, "У тебя и не было подписки. /start", html=False)
    elif cmd == "stats":
        on_stats(chat_id, user_id)


def on_stats(chat_id, user_id):
    if user_id != ADMIN_ID:
        send(chat_id, "Команда доступна только администратору.", html=False)
        return
    total = 0
    freq = {"daily": 0, "weekly": 0, "ondemand": 0}
    gc = {g: 0 for g in GENRE_ORDER}
    cc = {c: 0 for c in CITY_ORDER}
    g_all = c_all = 0
    for _cid, s in iter_subs():
        total += 1
        freq[s["freq"]] = freq.get(s["freq"], 0) + 1
        if "all" in s["genres"] or not s["genres"]:
            g_all += 1
        else:
            for g in s["genres"]:
                if g in gc:
                    gc[g] += 1
        if "all" in s["cities"] or not s["cities"]:
            c_all += 1
        else:
            for c in s["cities"]:
                if c in cc:
                    cc[c] += 1
    lines = ["📊 <b>Статистика</b>", "",
             f"👥 Активных подписчиков: <b>{total}</b>",
             f"➕ Всего подписалось: {get_counter('total_subscribed')}",
             f"➖ Всего отписалось: {get_counter('total_unsubscribed')}", "",
             "<b>По частоте:</b>",
             f"• каждый день: {freq['daily']}",
             f"• раз в неделю: {freq['weekly']}",
             f"• по запросу: {freq['ondemand']}", "",
             "<b>По жанрам:</b>", f"• любые: {g_all}"]
    lines += [f"• {GENRE_LABELS[g]}: {gc[g]}" for g in GENRE_ORDER]
    lines += ["", "<b>По городам:</b>", f"• весь Крым: {c_all}"]
    lines += [f"• {CITY_LABELS[c]}: {cc[c]}" for c in CITY_ORDER]
    send(chat_id, "\n".join(lines))


def on_callback(cb):
    data = cb["data"]
    cb_id = cb["id"]
    msg = cb["message"]
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    user_id = cb["from"]["id"]
    answer_cb(cb_id)

    if data == "cfg:start":
        sub = get_sub(chat_id)
        draft = dict(sub) if sub else {"genres": [], "cities": [],
                                       "freq": "ondemand", "weekday": 4}
        set_draft(chat_id, draft)
        edit_text(chat_id, msg_id,
                  "Шаг 1/3. Какие <b>жанры</b> интересны? Можно несколько. Потом нажми «Далее».",
                  reply_markup=genres_kb(draft["genres"]))
    elif data.startswith("g:"):
        val = data[2:]
        draft = get_draft(chat_id)
        if val == "next":
            if not draft["genres"]:
                answer_cb(cb_id, "Выбери хотя бы один жанр (или «Все жанры»)", True)
                return
            edit_text(chat_id, msg_id, "Шаг 2/3. В каких <b>городах</b>? Можно несколько.",
                      reply_markup=cities_kb(draft["cities"]))
        else:
            draft["genres"] = toggle(draft["genres"], val)
            set_draft(chat_id, draft)
            edit_markup(chat_id, msg_id, genres_kb(draft["genres"]))
    elif data.startswith("c:"):
        val = data[2:]
        draft = get_draft(chat_id)
        if val == "next":
            if not draft["cities"]:
                answer_cb(cb_id, "Выбери хотя бы один город (или «Весь Крым»)", True)
                return
            edit_text(chat_id, msg_id, "Шаг 3/3. Как часто присылать подборку?",
                      reply_markup=freq_kb())
        else:
            draft["cities"] = toggle(draft["cities"], val)
            set_draft(chat_id, draft)
            edit_markup(chat_id, msg_id, cities_kb(draft["cities"]))
    elif data.startswith("f:"):
        draft = get_draft(chat_id)
        draft["freq"] = data[2:]
        set_draft(chat_id, draft)
        if draft["freq"] == "weekly":
            edit_text(chat_id, msg_id, "В какой день недели присылать?",
                      reply_markup=weekday_kb(), html=False)
        else:
            finish_sub(chat_id, msg_id, draft)
    elif data.startswith("w:"):
        draft = get_draft(chat_id)
        draft["weekday"] = int(data[2:])
        finish_sub(chat_id, msg_id, draft)
    elif data == "digest:now":
        send_digest(chat_id, get_sub(chat_id))
    elif data == "sub:show":
        sub = get_sub(chat_id)
        edit_text(chat_id, msg_id,
                  summary_text(sub) if sub else "Подписки пока нет. Нажми «Настроить подписку».",
                  reply_markup=main_menu_kb())
    elif data == "sub:stop":
        if get_sub(chat_id):
            del_sub(chat_id)
            bump_counter("total_unsubscribed")
            edit_text(chat_id, msg_id, "Отписал. Вернуться — /start", html=False)
        else:
            edit_text(chat_id, msg_id, "Подписки и не было. /start", html=False)


def process_update(update):
    if "callback_query" in update:
        on_callback(update["callback_query"])
        return
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id", 0)
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if text.startswith("/"):
        on_command(chat_id, user_id, text)
    elif text == BTN_DIGEST:
        send_digest(chat_id, get_sub(chat_id))
    else:
        send(chat_id, "Что хочешь сделать?", reply_markup=main_menu_kb(), html=False)


def run_cron():
    """Рассылка: каждый день в 16:20 Крыма; еженедельным — в их день."""
    weekday = datetime.now(CRIMEA_TZ).weekday()
    for chat_id, sub in iter_subs():
        if sub["freq"] == "daily" or (sub["freq"] == "weekly" and sub["weekday"] == weekday):
            try:
                send_digest(chat_id, sub)
            except Exception as e:
                print("digest failed for", chat_id, e)


# ---------------------------------------------------------------------------
# Точка входа Yandex Cloud Functions
# ---------------------------------------------------------------------------
def handler(event, context):
    # Таймер-триггер (рассылка по расписанию)
    if isinstance(event, dict) and event.get("messages") and "httpMethod" not in event:
        run_cron()
        return {"statusCode": 200, "body": "cron ok"}

    # Webhook от Telegram
    if isinstance(event, dict) and event.get("httpMethod") == "POST":
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if WEBHOOK_SECRET and headers.get("x-telegram-bot-api-secret-token") != WEBHOOK_SECRET:
            return {"statusCode": 403, "body": "forbidden"}
        body = event.get("body", "") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        try:
            update = json.loads(body)
            process_update(update)
        except Exception as e:
            print("update error:", e)
        return {"statusCode": 200, "body": "ok"}

    return {"statusCode": 200, "body": "Местов.Нет бот работает 🎸"}
