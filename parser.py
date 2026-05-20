import argparse
import hashlib
import json
import mimetypes
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
IMAGES_DIR = "images/events"
CACHE_DIR = ".cache"
BATCH_SIZE = 10  # max posts per Claude call


def download_image(url: str):
    """Скачивает картинку локально, возвращает путь вида /images/events/<hash>.<ext>."""
    if not url:
        return None
    os.makedirs(IMAGES_DIR, exist_ok=True)
    url_hash = hashlib.md5(url.encode()).hexdigest()
    # Пробуем определить расширение из URL
    ext = "jpg"
    path_part = url.split("?")[0].split("/")[-1]
    if "." in path_part:
        guessed = path_part.rsplit(".", 1)[-1].lower()
        if guessed in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = guessed
    local_path = os.path.join(IMAGES_DIR, f"{url_hash}.{ext}")
    if os.path.exists(local_path):
        return f"/{local_path}"
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # Уточняем расширение по Content-Type если не определили из URL
        ct = resp.headers.get("content-type", "")
        guessed_ext = mimetypes.guess_extension(ct.split(";")[0].strip())
        if guessed_ext and guessed_ext.lstrip(".") in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = guessed_ext.lstrip(".")
            local_path = os.path.join(IMAGES_DIR, f"{url_hash}.{ext}")
        with open(local_path, "wb") as f:
            f.write(resp.content)
        return f"/{local_path}"
    except Exception:
        return url  # fallback: оставляем внешний URL


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cache_read(text: str):
    key = _cache_key(text)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _cache_write(text: str, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(text)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


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
        # Ищем тег с datetime — для видео-постов он вложен в .tgme_widget_message_date
        time_tag = msg.select_one(".tgme_widget_message_date time[datetime]") or msg.select_one("time[datetime]")
        text_tag = msg.select_one(".tgme_widget_message_text")

        if not time_tag or not text_tag:
            continue

        post_dt = datetime.fromisoformat(time_tag["datetime"])
        if post_dt < cutoff:
            continue

        image_urls = []
        thumbnail_url = None

        # Извлекаем ВСЕ картинки из поста (альбомы/карусели)
        for image_tag in msg.select(".tgme_widget_message_photo_wrap"):
            if image_tag and image_tag.get("style"):
                style = image_tag["style"]
                if "url(" in style:
                    img_url = style.split("url('")[-1].split("')")[0]
                    if img_url and img_url not in image_urls:
                        image_urls.append(img_url)

        video_tag = msg.select_one(".tgme_widget_message_video_thumb")
        if video_tag and video_tag.get("style"):
            style = video_tag["style"]
            if "url(" in style:
                thumbnail_url = style.split("url('")[-1].split("')")[0]

        data_post = msg.get("data-post")  # "channel_name/123"
        post_url = f"https://t.me/{data_post}" if data_post else None

        posts.append({
            "date": post_dt.isoformat(),
            "text": text_tag.get_text(separator="\n").strip(),
            "image": image_urls[0] if image_urls else None,
            "images": image_urls if len(image_urls) > 1 else None,
            "thumbnail": thumbnail_url,
            "url": post_url,
        })

    return posts


def _call_claude_text(prompt: str) -> str:
    cmd = ["claude", "-p", prompt, "--output-format", "text"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout.strip()


def _call_claude_vision(prompt: str, image_paths: list[str]) -> str:
    import base64
    content = []
    for p in image_paths:
        try:
            with open(p, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}})
        except Exception:
            pass
    content.append({"type": "text", "text": prompt})
    msg = json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": content,
        },
    })
    cmd = ["claude", "--print", "--verbose", "--input-format", "stream-json", "--output-format", "stream-json"]
    try:
        result = subprocess.run(cmd, input=msg, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return ""
    raw_parts = []
    for line in result.stdout.splitlines():
        try:
            obj = json.loads(line)
            if obj.get("type") == "assistant":
                for block in obj.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        raw_parts.append(block["text"])
        except json.JSONDecodeError:
            pass
    return "".join(raw_parts).strip()


def _parse_claude_json(raw: str):
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def extract_events_batch(posts: list[dict], channel_meta: dict) -> dict[str, list[dict]]:
    """Извлекает события из батча постов одним вызовом Claude.
    Возвращает dict: post_url -> [events...].
    """
    if not posts:
        return {}

    # Проверяем кэш — хэш по всем текстам постов
    cache_texts = [p["text"] for p in posts]
    cached = _cache_read("\n---\n".join(cache_texts))
    if cached is not None:
        print(f" [кэш]", end="")
        return cached

    # Скачиваем все картинки для vision
    vision_paths = []
    for post in posts:
        vision_url = post.get("image") or post.get("thumbnail")
        if vision_url:
            try:
                import tempfile
                resp = httpx.get(vision_url, timeout=10, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(resp.content)
                    vision_paths.append(tmp.name)
            except Exception:
                pass

    # Строим промпт для батча
    posts_section = ""
    for i, post in enumerate(posts):
        url = post.get("url") or f"post_{i}"
        posts_section += f"\n--- POST {i+1} (url: {url}) ---\n{post['text']}\n"

    image_note = "\nТакже приложены изображения из постов — прочитай текст с афиш/картинок, если они содержат детали мероприятий (дата, время, артист, цена)." if vision_paths else ""

    prompt_text = f"""Ты анализируешь посты из Telegram-канала крымского заведения.
Заведение: {channel_meta['title']}, город: {channel_meta['city']}.

{posts_section}
{image_note}

Для КАЖДОГО поста извлеки музыкальные мероприятия. Верни JSON-объект где ключи — url поста (точно как указано выше), а значения — массивы событий.

НЕ включай в результат:
- мастер-классы, интенсивы, курсы, обучение, танцевальные классы;
- «дни свободного творчества», открытые микрофоны без конкретных исполнителей;
- выставки, кинопоказы, лекции, ярмарки (если нет живой музыки);
- общие анонсы без конкретного исполнителя/группы на конкретную дату.
Если пост содержит расписание/афишу на несколько дней — извлеки отдельное мероприятие на каждую дату ТОЛЬКО если для неё указан конкретный исполнитель/группа или другие детали (время, цена).
Если по дням нет конкретных деталей — верни пустой массив [].
ВАЖНО: НЕ создавай события с пустыми/общими полями artist.
ВАЖНО: artist должен быть извлечён ИСКЛЮЧИТЕЛЬНО из текста поста. НЕ придумывай имена. Если не назван конкретный исполнитель — укажи null.
Каждое событие:
{{
  "date": "YYYY-MM-DD или null",
  "time": "HH:MM или null",
  "artist": "название группы/исполнителя или null",
  "event_type": "концерт / джем / трибьют / вечеринка / фестиваль / другое",
  "venue": "конкретное место проведения из текста или null",
  "city": "город Крыма или null",
  "price": "цена или бесплатно или null",
  "description": "1-2 предложения"
}}

Если мероприятий нет ни в одном посте — верни {{}}.
Верни только JSON, без пояснений, без markdown."""

    if vision_paths:
        raw = _call_claude_vision(prompt_text, vision_paths)
    else:
        raw = _call_claude_text(prompt_text)

    # Cleanup temp files
    for p in vision_paths:
        try:
            os.unlink(p)
        except OSError:
            pass

    result = _parse_claude_json(raw)
    if result is None:
        return {}

    # Валидируем структуру
    if not isinstance(result, dict):
        return {}

    _cache_write("\n---\n".join(cache_texts), result)
    return result


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
            "image": download_image(post.get("image")),
            "source_url": pre["source_url"],
        }
        all_events.append(event)
        count += 1
    print(f"  Найдено событий: {count}")


# Жанр по source_channel (если канал всегда одного жанра)
_CHANNEL_GENRES: dict[str, str] = {
    "skazhitejazz": "джаз",
}

# Правила определения жанра по ключевым словам (порядок важен — специфичные раньше)
_GENRE_RULES: list[tuple[list[str], str]] = [
    (["фолк-метал", "folk metal"],                                             "фолк-метал"),
    (["панк", "punk"],                                                         "панк-рок"),
    (["метал", "metal", "radio tapok", "blackened"],                           "метал"),
    (["хип-хоп", "hip-hop", "хип хоп", "рэп", "rap"],                        "хип-хоп"),
    (["джаз", "jazz", "свинг", "swing"],                                      "джаз"),
    (["блюз", "blues", "blues night"],                                        "блюз"),
    (["симфони", "камерн", "опер", "сонат", "классическ"],                    "классика"),
    (["хор сретен", "мужской хор", "женский хор", "детский хор", "хоровой"], "хоровая"),
    (["оркестр русских народных", "народный оркестр"],                         "классика"),
    (["духовой оркестр", "эстрадно-духовой", "духовой ансамбль"],              "классика"),
    (["этно", "этническ", "уутай"],                                           "этно"),
    (["народн", "народная", "фолк", "folk"],                                   "фолк"),
    (["авторская", "авторские", "авторской"],                                  "авторская"),
    (["музыкальное лото", "угадыванием хитов", "музыкальный квиз"],           "интерактив"),
    (["инди", "indie"],                                                        "инди"),
    (["лаунж", "lounge"],                                                      "лаунж"),
    (["при свечах", "легенды 90", "легенды мтв", "легенды mtv", "суперхиты 90"], "поп"),
    (["поп-рок", "рок-поп", "pop-rock"],                                      "поп-рок"),
    (["русский рок", "русских рок", "каверы на рок", "рок-хиты", "рок хиты"],"русский рок"),
    (["рок", "rock"],                                                          "рок"),
    (["поп", "pop"],                                                           "поп"),
    (["квн", "юмор", "комедия", "стендап"],                                   "юмор"),
    (["кавер", "cover"],                                                       "каверы"),
    # — расширенные правила —
    (["трибьют", "tribute"],                                                   "рок"),
    (["киномаёвка", "кинофест"],                                               "поп"),
    (["песни побед", "день побед", "9 мая", "военн", "катюш"],                "поп"),
    (["виолончель", "cello", "виолончели"],                                    "классика"),
    (["скрипач", "скрипка", "скрипк"],                                         "классика"),
    (["пианин", "фортепиано", "рояль"],                                        "классика"),
    (["балет", "танц"],                                                        "другое"),
    (["кельтск", "средневеков", "барбакан"],                                   "фолк"),
    (["drum'n'bass", "drum and bass", "dnb", "breakbeat"],                    "поп"),
    (["trance", "goa trance", "транс"],                                        "поп"),
    (["jungle", "джангл"],                                                     "поп"),
    (["house", "хаус", "mtv hits", "mtv хиты"],                                "поп"),
    (["диско", "disco", "disco time"],                                         "поп"),
    (["dj-сет", "dj сет", "dj"],                                               "поп"),
    (["живая музыка на пляже", "живая музыка на набережной"],                  "поп"),
    (["настойк", "дегустац"],                                                  "другое"),
    (["сказки с оркестром", "незнайк"],                                        "классика"),
    (["чехов в музыке"],                                                       "классика"),
    (["песни любимого кино", "песни из кино"],                                 "поп"),
    (["самая красивая музыка"],                                                "классика"),
    (["танцуем все", "танцевальная вечеринка"],                                "поп"),
    (["открытие фестиваля", "открытие сезона"],                                "поп"),
]


def detect_genre(event: dict) -> "str | None":
    """Определяет жанр события по ключевым словам. Возвращает None если не удалось."""
    # 1. По каналу
    ch = (event.get("source_channel") or "").lower()
    for key, genre in _CHANNEL_GENRES.items():
        if key in ch:
            return genre

    # 2. По тексту — ищем в описании + артисте + event_type (в нижнем регистре)
    text = " ".join(filter(None, [
        event.get("description") or "",
        event.get("artist") or "",
        event.get("event_type") or "",
    ])).lower()

    for keywords, genre in _GENRE_RULES:
        if any(kw in text for kw in keywords):
            return genre

    # 3. Фолбэк по event_type
    etype = (event.get("event_type") or "").lower()
    if etype in ("трибьют", "tribute"):
        return "рок"
    if etype == "вечеринка":
        return "поп"
    if etype == "фестиваль":
        return "рок"
    if etype == "концерт":
        return "поп"

    return None


def _extract_artist_from_description(desc: str) -> "str | None":
    """Пытается извлечь имя артиста из описания когда artist=null."""
    if not desc:
        return None
    import re

    # Паттерны: "Выступление X", "X выступает", "Концерт X", "Живая музыка X"
    patterns = [
        r"[Вв]ыступление\s+([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)(?:\s+в\s+|\s+на\s+|\s+—\s+|\s+—\s+|\s+исполняет|\s+с\s+лидером|\s+—\s+|\s+\(|$)",
        r"([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)\s+выступает",
        r"[Кк]онцерт\s+(?:дуэта\s+)?(?:группы\s+)?([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)(?:\s+в\s+|\s+на\s+|\s+—\s+|\s+от\s+|$)",
        r"[Жж]ивая\s+музыка[:\s]+([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)(?:\s+—\s+|\s+на\s+|\s+в\s+|$)",
        r"DJ\s+([А-ЯЁA-Za-z][А-Яа-яёA-Za-z0-9\s\-\,]+?)(?:\s+—\s+|\s+сет|\s+в\s+|$)",
        r"DJ-сет\s+(?:с\s+)?([А-ЯЁA-Za-z][А-Яа-яёA-Za-z0-9\s\-\,]+?)(?:\s+с\s+|\s+до\s+|$)",
        r"группа\s+«([^»]+)»",
        r"«([^»]+)»\s+исполняет",
    ]

    for pat in patterns:
        m = re.search(pat, desc)
        if m:
            artist = m.group(1).strip().rstrip(".,")
            if len(artist) > 2 and len(artist) < 80:
                return artist

    return None


def _fallback_artist(event: dict) -> "str | None":
    """Фолбэк артиста по event_type и описанию."""
    import re
    etype = (event.get("event_type") or "").lower()
    desc = event.get("description") or ""
    desc_lower = desc.lower()

    # Музыкальное лото / квиз
    if "музыкальное лото" in desc_lower or "музыкальный квиз" in desc_lower:
        return "Музыкальное лото"

    # DJ-сеты без имени
    if etype == "вечеринка" and ("dj" in desc_lower or "диджей" in desc_lower):
        return "DJ-сет"

    # Звукотерапия / медитация
    if "звукотерап" in desc_lower or "тибетск" in desc_lower or "гонг" in desc_lower:
        return "Звукотерапия"

    # Квартирник / акустика без имени
    if "квартирник" in desc_lower:
        return "Квартирник"

    # Театральная постановка / спектакль
    if "спектакль" in desc_lower or "театральная постановка" in desc_lower:
        m = re.search(r"«([^»]+)»", desc)
        if m:
            return f"Спектакль «{m.group(1)}»"
        return "Спектакль"

    # Фестиваль — берём название из описания
    if etype == "фестиваль":
        m = re.search(r"«([^»]+)»", desc)
        if m:
            return m.group(1)
        return "Фестиваль"

    # Концерт — ищем название в кавычках
    if etype == "концерт":
        m = re.search(r"[Кк]онцерт\s+«([^»]+)»", desc)
        if m:
            return m.group(1)
        m = re.search(r"«([^»]+)»", desc)
        if m:
            return m.group(1)
        # "Живой концерт X" / "Летний концерт"
        m = re.search(r"[Жж]ивой\s+концерт\s+«([^»]+)»", desc)
        if m:
            return m.group(1)
        if "живой концерт" in desc_lower:
            return "Живой концерт"
        if "музыкальный вечер" in desc_lower:
            return "Музыкальный вечер"
        if "летний концерт" in desc_lower:
            return "Летний концерт"
        if "живой звук" in desc_lower or "живого звука" in desc_lower:
            return "Живой звук"
        if "открытие сезона" in desc_lower:
            return "Открытие сезона"
        if "литературно-музыкальная" in desc_lower:
            m = re.search(r"«([^»]+)»", desc)
            if m:
                return m.group(1)
            return "Литературно-музыкальная гостиная"
        if "открытие летнего" in desc_lower:
            return "Открытие летнего сезона"

    # Вечеринка — можно взять тему
    if etype == "вечеринка":
        m = re.search(r"в\s+стиле\s+([А-ЯЁA-Za-z][А-Яа-яёA-Za-z0-9\s\-]+?)(?:\s+в\s+|\s+на\s+|\.)", desc_lower)
        if m:
            return f"Вечеринка {m.group(1).strip().title()}"
        return "Вечеринка"

    # Дегустация
    if "дегустац" in desc_lower:
        return "Дегустация"

    # Акция / массовое мероприятие
    if "акция" in desc_lower or "массовое" in desc_lower:
        return "Массовое мероприятие"

    # Этнокультурный проект / показы
    if "этнокультурн" in desc_lower or "показ" in desc_lower:
        m = re.search(r"«([^»]+)»", desc)
        if m:
            return m.group(1)
        return "Этно-проект"

    return None


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
    text = re.sub(r"[«»\"'']", "", text)
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_venue(text: str) -> str:
    """Нормализует название площадки: убирает тип (отель, resort, spa, palace)."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[«»\"'']", "", text)
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    stops = {"отель", "resort", "spa", "palace", "дворец", "гостиница", "inn", "hotel", "club", "дк", "кдк", "дк ", "кдк ", "дом культуры", "дворец культуры", "театральный", "зал"}
    words = [w for w in text.split() if w not in stops]
    return " ".join(words).strip()


def _venue_match(v1: str, v2: str) -> bool:
    """Проверяет, относятся ли названия площадок к одному месту."""
    w1 = set(_normalize_venue(v1).split())
    w2 = set(_normalize_venue(v2).split())
    if not w1 or not w2:
        return False
    common = w1 & w2
    # достаточно одного общего значимого слова
    return len(common) >= 1


def _artist_parts(name: str) -> list[str]:
    """Разбивает строку артиста на отдельные имена по разделителям."""
    # Режем только по « и », « & », « + » с пробелами.
    # Запятую НЕ трогаем — она может быть частью названия или перечисления инструментов.
    result = re.split(r'\s+(и|&|\+)\s+', name)
    return [p.strip() for p in result if p.strip() and p.strip() not in ("и", "&", "+")]


def _artist_set(event: dict) -> set:
    """Множество нормализованных имён артистов из события."""
    artist = event.get("artist") or ""
    names = set()
    for raw in artist.split(","):
        for name in _artist_parts(raw.strip()):
            n = _normalize(name)
            # убираем префиксы «группа», «band» для лучшего сравнения
            for prefix in ("группа ", "band ", "группа «", "«"):
                if n.startswith(prefix):
                    n = n[len(prefix):].strip()
            if n:
                names.add(n)
    return names


def _field_count(e: dict) -> int:
    """Сколько непустых полей у события."""
    fields = ("date", "time", "artist", "event_type", "venue", "price", "description", "source_city")
    return sum(1 for f in fields if e.get(f))


def _merge_events(group: list[dict]) -> dict:
    group_sorted = sorted(group, key=lambda e: e.get("post_date") or "", reverse=True)
    most_recent = group_sorted[0]

    # Выбираем источник с самой полной информацией
    best = max(group, key=_field_count)

    merged = {}
    for field in ("date", "time", "artist", "event_type", "venue", "price", "description", "source_city", "source_channel", "genre"):
        for e in group_sorted:
            v = e.get(field)
            if v and str(v).strip():
                merged[field] = v
                break
        else:
            merged[field] = None
    merged["source_url"] = best.get("source_url") or most_recent.get("source_url")

    # Собираем все постеры
    all_images = []
    for e in group_sorted:
        img = e.get("image")
        if img and img not in all_images:
            all_images.append(img)
    # сначала картинка из лучшего источника
    best_img = best.get("image")
    if best_img and best_img in all_images:
        all_images.remove(best_img)
        all_images.insert(0, best_img)
    merged["images"] = all_images if all_images else None
    merged["image"] = all_images[0] if all_images else None

    merged["post_date"] = most_recent.get("post_date")
    return merged


def _bare_artist_key(text: str) -> str:
    """Нормализованное имя без префиксов группа/band."""
    k = _normalize(text)
    for p in ("группа", "band"):
        if k.startswith(p):
            k = k[len(p):].strip()
    return k


def _merge_group(group: list[dict]) -> dict:
    """Мёрджит группу событий: объединяет артистов, берёт лучшие поля."""
    merged = _merge_events(group)
    seen: set = set()
    artists: list = []
    for e in group:
        for a in (e.get("artist") or "").split(","):
            for name in _artist_parts(a.strip()):
                key = _normalize(name)
                bare = _bare_artist_key(name)
                if not name or bare in seen:
                    continue
                seen.add(bare)
                # проверяем, не является ли это имя вариацией уже добавленного
                is_sub = False
                for other in artists[:]:
                    obare = _bare_artist_key(other)
                    if bare and obare and (bare in obare or obare in bare):
                        if len(bare) >= len(obare):
                            artists.remove(other)
                        else:
                            is_sub = True
                            break
                if not is_sub:
                    artists.append(name)
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
                vi = stage1[i].get("venue") or ""
                vj = stage1[j].get("venue") or ""
                ti = stage1[i].get("time") or ""
                tj = stage1[j].get("time") or ""
                if ai and aj and ai & aj:
                    # Есть хотя бы один общий артист → одно событие
                    union(i, j)
                elif vi and vj and _venue_match(vi, vj) and ti and tj and ti == tj:
                    # Одинаковые площадка + время → одно событие (даже если артисты названы по-разному)
                    union(i, j)

    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(stage1[i])

    return [_merge_group(g) if len(g) > 1 else g[0] for g in groups.values()]


def _download_all_images(posts: list[dict]) -> dict[str, list[str]]:
    """Скачивает все картинки из постов. Возвращает url -> [local_paths...]."""
    result = {}
    for post in posts:
        urls = list(post.get("images") or [])
        if post.get("image") and post["image"] not in urls:
            urls.insert(0, post["image"])
        if post.get("thumbnail") and post["thumbnail"] not in urls:
            urls.append(post["thumbnail"])
        if urls:
            local = []
            for u in urls:
                p = download_image(u)
                if p:
                    local.append(p)
            result[post.get("url") or ""] = local
    return result


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

        if not posts:
            print(f"  Найдено событий: 0          ")
            continue

        # Скачиваем все картинки заранее
        images_map = _download_all_images(posts)

        # Батчим посты
        batches = [posts[i:i + BATCH_SIZE] for i in range(0, len(posts), BATCH_SIZE)]
        channel_events = 0

        for bi, batch in enumerate(batches):
            print(f"  Батч {bi + 1}/{len(batches)} ({len(batch)} постов)...", end="")

            batch_result = extract_events_batch(batch, channel)

            for post in batch:
                post_url = post.get("url") or ""
                events = batch_result.get(post_url, [])

                local_images = images_map.get(post_url, [])

                for idx, event in enumerate(events):
                    event["source_channel"] = label
                    city = channel["city"]
                    if city == "Крым":
                        city = (
                            event.get("city") or
                            _detect_city(event.get("venue") or "") or
                            _detect_city(event.get("description") or "") or
                            city
                        )
                    event["source_city"] = city
                    event.pop("city", None)
                    if not event.get("venue"):
                        event["venue"] = channel["title"]
                    event["post_date"] = post["date"]

                    if local_images:
                        event["image"] = local_images[idx % len(local_images)]
                        event["images"] = local_images if len(local_images) > 1 else None
                    else:
                        event["image"] = None
                        event["images"] = None

                    event["source_url"] = post_url
                    all_events.append(event)
                    channel_events += 1

            print(f" +{len([e for p in batch for e in batch_result.get(p.get('url', ''), [])])}")

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
    ig_proxy = os.environ.get("IG_PROXY", "")
    if ig_channels and ig_user and ig_pass:
        print("\nInstagram — пропускаю (долго и нестабильно)")
        # process_channels(
        #     ig_channels, all_events, lambda ch: fetch_instagram_posts_wrapper(ch["username"])
        # )
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
    merged_raw = existing + new_events

    before2 = len(merged_raw)
    merged = deduplicate_events(merged_raw)
    after2 = len(merged)
    if before2 != after2:
        print(f"Дедупликация с архивом: {before2} → {after2} (убрано: {before2 - after2})")

    print(f"Новых событий: {len(new_events)}, уже было: {len(existing)}, итого: {len(merged)}")

    # Убираем события-призраки: одинаковое описание + общий артист (афиши без деталей)
    ghost_before = len(merged)
    ghost_artists = {"живой звук", "музыкальный вечер", "концерт", "живой концерт"}
    by_source: dict[str, list] = {}
    for i, e in enumerate(merged):
        by_source.setdefault(e.get("source_url") or "", []).append(i)
    keep = set(range(len(merged)))
    for url, indices in by_source.items():
        if len(indices) < 2 or not url:
            continue
        descs = {merged[i].get("description", "") for i in indices}
        if len(descs) == 1:
            artists = {_normalize(merged[i].get("artist") or "") for i in indices}
            if artists & ghost_artists:
                print(f"  призрак: {url} — {list(artists)}")
                for i in indices:
                    keep.discard(i)
    merged = [e for i, e in enumerate(merged) if i in keep]
    ghost_removed = ghost_before - len(merged)
    if ghost_removed:
        print(f"Убрано событий-призраков: {ghost_removed}")

    # Чистим артистов: убираем дубли где одно имя — часть другого, оставляем самое короткое
    for e in merged:
        if not e.get("artist"):
            continue
        parts = _artist_parts(e["artist"])
        # группируем по bare-ключу, выбираем самое короткое имя
        by_bare: dict[str, list[str]] = {}
        for name in parts:
            bare = _bare_artist_key(name)
            if bare:
                by_bare.setdefault(bare, []).append(name)
        cleaned = []
        seen_bare = set()
        for bare in sorted(by_bare, key=len):
            candidates = by_bare[bare]
            # выбираем самое короткое имя (без «, лишнего)
            best = min(candidates, key=lambda n: len(n))
            # проверяем, не является ли это имя частью уже выбранного
            is_sub = False
            for other in cleaned[:]:
                obare = _bare_artist_key(other)
                if bare in obare or obare in bare:
                    if len(bare) < len(obare):
                        cleaned.remove(other)
                    else:
                        is_sub = True
                    break
            if not is_sub:
                cleaned.append(best)
        e["artist"] = ", ".join(cleaned) if cleaned else None

    # Проставляем жанр и артиста там, где их ещё нет
    genre_added = 0
    artist_extracted = 0
    artist_fallback = 0
    for e in merged:
        # Фолбэк артиста из описания
        if not e.get("artist"):
            extracted = _extract_artist_from_description(e.get("description") or "")
            if extracted:
                e["artist"] = extracted
                artist_extracted += 1
            else:
                # Фолбэк по типу события
                fb = _fallback_artist(e)
                if fb:
                    e["artist"] = fb
                    artist_fallback += 1
        # Жанр
        if not e.get("genre"):
            g = detect_genre(e)
            if g:
                e["genre"] = g
                genre_added += 1
    if artist_extracted:
        print(f"Артист извлечён из описания: {artist_extracted} событий")
    if artist_fallback:
        print(f"Артист-фолбэк по типу: {artist_fallback} событий")
    if genre_added:
        print(f"Жанр определён автоматически: {genre_added} событий")

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
