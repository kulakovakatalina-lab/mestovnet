import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

CHANNELS_FILE = "channels.json"
OUTPUT_FILE = "events.json"
DAYS_BACK = 2


def load_channels():
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return (
        data["channels"],
        data.get("max_channels", []),
        data.get("vk_channels", []),
        data.get("instagram_channels", []),
    )


def fetch_posts(username: str, days_back: int) -> list[dict]:
    url = f"https://t.me/s/{username}"
    headers = {"User-Agent": "Mozilla/5.0"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    response = httpx.get(url, headers=headers, follow_redirects=True, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    posts = []

    for msg in soup.select(".tgme_widget_message"):
        time_tag = msg.select_one("time")
        text_tag = msg.select_one(".tgme_widget_message_text")

        if not time_tag or not text_tag:
            continue

        if not time_tag.get("datetime"):
            continue
        post_dt = datetime.fromisoformat(time_tag["datetime"])
        if post_dt < cutoff:
            continue

        image_tag = msg.select_one(".tgme_widget_message_photo_wrap")
        image_url = None
        if image_tag and image_tag.get("style"):
            style = image_tag["style"]
            if "url(" in style:
                image_url = style.split("url('")[-1].split("')")[0]

        data_post = msg.get("data-post")  # "channel_name/123"
        post_url = f"https://t.me/{data_post}" if data_post else None

        posts.append({
            "date": post_dt.isoformat(),
            "text": text_tag.get_text(separator="\n").strip(),
            "image": image_url,
            "url": post_url,
        })

    return posts


def extract_events(post_text: str, channel_meta: dict) -> list[dict]:
    prompt = f"""Ты анализируешь пост из Telegram-канала крымского заведения.
Заведение: {channel_meta['title']}, город: {channel_meta['city']}.

Текст поста:
\"\"\"
{post_text}
\"\"\"

Если в посте анонсируется живая музыка или музыкальное мероприятие — верни JSON-массив объектов.
Каждый объект:
{{
  "date": "YYYY-MM-DD или null",
  "time": "HH:MM или null",
  "artist": "название группы/исполнителя или null",
  "event_type": "концерт / джем / трибьют / вечеринка / фестиваль / другое",
  "venue": "конкретное место проведения из текста (кафе, ресторан, винодельня и т.п.) или null если не указано",
  "city": "конкретный город Крыма (Ялта / Симферополь / Севастополь / Алушта / Судак / Керчь / Феодосия / Евпатория / Коктебель / Бахчисарай / Гурзуф / Саки и т.п.) — определи по названию площадки или контексту, null если не ясно",
  "price": "цена или бесплатно или null",
  "description": "1-2 предложения"
}}

Если мероприятий нет — верни только [].
Верни только JSON, без пояснений, без markdown."""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        print(" [таймаут]", end="")
        return []

    raw = result.stdout.strip()
    # убираем markdown-обёртку если модель всё равно добавила
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def fetch_max_posts(chat_id: int, token: str) -> list[dict]:
    from fetch_max import fetch_max_posts as _fetch
    return _fetch(chat_id, token, DAYS_BACK)


def fetch_vk_posts(domain: str, token: str) -> list[dict]:
    from fetch_vk import fetch_vk_posts as _fetch
    return _fetch(domain, token, DAYS_BACK)


def fetch_instagram_posts_wrapper(username: str) -> list[dict]:
    from fetch_instagram import fetch_instagram_posts as _fetch
    return _fetch(username, DAYS_BACK)


def process_yandex_afisha(all_events: list):
    from fetch_yandex_afisha import fetch_all_crimea, CITIES
    print("\nЯндекс.Афиша — крымские города...")
    posts = fetch_all_crimea()
    count = 0
    for post in posts:
        pre = post["_prefilled"]
        event = {
            "date": pre["date"],
            "time": pre["time"],
            "artist": pre["artist"],
            "venue": pre["venue"],
            "event_type": pre["event_type"],
            "price": pre["price"],
            "description": pre["description"],
            "source_channel": "yandex_afisha",
            "source_city": post["_city"],
            "post_date": post["date"],
            "image": post.get("image"),
            "source_url": pre["source_url"],
        }
        all_events.append(event)
        count += 1
    print(f"  Найдено событий: {count}")


# Ключевые слова для определения города когда канал охватывает весь Крым
_CITY_HINTS = [
    ("Ялт",         "Ялта"),
    ("Массандр",    "Ялта"),
    ("Мисхор",      "Ялта"),
    ("Дюльбер",     "Ялта"),
    ("Ливади",      "Ялта"),
    ("Мрия",        "Ялта"),
    ("Симферополь", "Симферополь"),
    ("Севастополь", "Севастополь"),
    ("Керч",        "Керчь"),
    ("Феодоси",     "Феодосия"),
    ("Судак",       "Судак"),
    ("Евпатори",    "Евпатория"),
    ("Алушт",       "Алушта"),
    ("Коктебель",   "Коктебель"),
    ("Бахчисарай",  "Бахчисарай"),
    ("Саки",        "Саки"),
    ("Гурзуф",      "Гурзуф"),
]

def _detect_city(text: str):
    low = text.lower()
    for hint, city in _CITY_HINTS:
        if hint.lower() in low:
            return city
    return None


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()



def _merge_events(group: list[dict]) -> dict:
    group_sorted = sorted(group, key=lambda e: e.get("post_date") or "", reverse=True)
    most_recent = group_sorted[0]
    merged = {}
    for field in ("date", "time", "artist", "event_type", "venue", "price", "description", "source_city", "source_channel"):
        for e in group_sorted:
            v = e.get(field)
            if v and str(v).strip():
                merged[field] = v
                break
        else:
            merged[field] = None
    merged["source_url"] = most_recent.get("source_url")
    merged["image"] = most_recent.get("image")
    merged["post_date"] = most_recent.get("post_date")
    return merged


def _artist_set(event: dict) -> set:
    """Множество нормализованных имён артистов из события."""
    artist = event.get("artist") or ""
    return {_normalize(a) for a in artist.split(",") if a.strip()}


def _merge_group(group: list[dict]) -> dict:
    """Мёрджит группу событий: объединяет артистов, берёт лучшие поля."""
    merged = _merge_events(group)
    seen: set = set()
    artists: list = []
    for e in group:
        for a in (e.get("artist") or "").split(","):
            a = a.strip()
            key = _normalize(a)
            if a and key not in seen:
                seen.add(key)
                artists.append(a)
    merged["artist"] = ", ".join(artists) if artists else None
    return merged


def deduplicate_events(events: list[dict]) -> list[dict]:
    # Этап 1: события из одного поста с одной датой → одна карточка
    by_post: dict[tuple, list] = {}
    no_url: list[dict] = []
    for event in events:
        url = event.get("source_url") or ""
        date = event.get("date") or ""
        if url and date:
            by_post.setdefault((date, url), []).append(event)
        else:
            no_url.append(event)

    stage1: list[dict] = []
    for group in by_post.values():
        stage1.append(_merge_group(group) if len(group) > 1 else group[0])
    stage1.extend(no_url)

    # Этап 2: Union-Find — объединяем события с пересекающимися артистами на одну дату.
    # Это ловит случаи когда разные каналы перечисляют артистов одного фестиваля в разном порядке.
    n = len(stage1)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    # Индексируем по дате для эффективности
    by_date: dict[str, list[int]] = {}
    for i, e in enumerate(stage1):
        by_date.setdefault(e.get("date") or "", []).append(i)

    for indices in by_date.values():
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                i, j = indices[a], indices[b]
                ai = _artist_set(stage1[i])
                aj = _artist_set(stage1[j])
                if ai and aj and ai & aj:
                    # Есть хотя бы один общий артист → одно событие
                    union(i, j)
                elif not ai and not aj:
                    # Оба без артиста → совпадение площадки
                    vi = _normalize(stage1[i].get("venue") or "")
                    vj = _normalize(stage1[j].get("venue") or "")
                    if vi and vj and vi == vj:
                        union(i, j)

    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(stage1[i])

    return [_merge_group(g) if len(g) > 1 else g[0] for g in groups.values()]


def process_channels(channels, all_events, get_posts_fn):
    for channel in channels:
        label = channel.get("username") or channel.get("domain") or str(channel.get("chat_id"))
        print(f"\nЧитаю {label} ({channel['title']})...")
        try:
            posts = get_posts_fn(channel)
            print(f"  Постов за {DAYS_BACK} дней: {len(posts)}")
        except Exception as e:
            print(f"  Ошибка: {e}")
            continue

        channel_events = 0
        for i, post in enumerate(posts):
            print(f"  Пост {i+1}/{len(posts)}...", end="\r")
            events = extract_events(post["text"], channel)
            for event in events:
                event["source_channel"] = label
                city = channel["city"]
                if city == "Крым":
                    # Приоритет: Claude-поле city → venue → description → keyword
                    city = (
                        event.get("city") or
                        _detect_city(event.get("venue") or "") or
                        _detect_city(event.get("description") or "") or
                        city
                    )
                event["source_city"] = city
                event.pop("city", None)  # убираем из финального объекта
                if not event.get("venue"):
                    event["venue"] = channel["title"]
                event["post_date"] = post["date"]
                event["image"] = post.get("image")
                event["source_url"] = post.get("url")
                all_events.append(event)
                channel_events += 1
        print(f"  Найдено событий: {channel_events}          ")


def main():
    tg_channels, max_channels, vk_channels, ig_channels = load_channels()

    all_events = []

    process_channels(tg_channels, all_events, lambda ch: fetch_posts(ch["username"], DAYS_BACK))

    max_token = os.environ.get("MAX_BOT_TOKEN", "")
    active_max = [c for c in max_channels if c.get("chat_id")]
    if active_max and max_token:
        process_channels(
            active_max, all_events, lambda ch: fetch_max_posts(ch["chat_id"], max_token)
        )
    elif active_max:
        print("\nMax-каналы настроены, но MAX_BOT_TOKEN не задан — пропускаю.")

    vk_token = os.environ.get("VK_SERVICE_TOKEN", "")
    if vk_channels and vk_token:
        process_channels(
            vk_channels, all_events, lambda ch: fetch_vk_posts(ch["domain"], vk_token)
        )
    elif vk_channels:
        print("\nVK-каналы настроены, но VK_SERVICE_TOKEN не задан — пропускаю.")

    ig_user = os.environ.get("IG_USERNAME", "")
    ig_pass = os.environ.get("IG_PASSWORD", "")
    if ig_channels and ig_user and ig_pass:
        process_channels(
            ig_channels, all_events, lambda ch: fetch_instagram_posts_wrapper(ch["username"])
        )
    elif ig_channels:
        print("\nInstagram-каналы настроены, но IG_USERNAME / IG_PASSWORD не заданы — пропускаю.")

    process_yandex_afisha(all_events)

    before = len(all_events)
    all_events = deduplicate_events(all_events)
    after = len(all_events)
    print(f"\nДедупликация: {before} → {after} событий (убрано дублей: {before - after})")

    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_urls = {e["source_url"] for e in existing if e.get("source_url")}
    new_events = [e for e in all_events if e.get("source_url") not in existing_urls]
    merged = existing + new_events

    print(f"Новых событий: {len(new_events)}, уже было: {len(existing)}, итого: {len(merged)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Готово. Сохранено в {OUTPUT_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Глубина парсинга в днях (по умолчанию: DAYS_BACK)")
    args = parser.parse_args()
    if args.days:
        DAYS_BACK = args.days
        print(f"Глубина парсинга: {DAYS_BACK} дней")
    main()
