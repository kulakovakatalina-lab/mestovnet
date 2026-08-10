import argparse
import hashlib
import json
import mimetypes
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

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
    groups = (
        data["channels"],
        data.get("max_channels", []),
        data.get("vk_channels", []),
        data.get("instagram_channels", []),
    )
    # Сверяем города каналов со справочником cities.json — предупреждаем о незнакомых.
    unknown = sorted({
        ch["city"] for group in groups for ch in group
        if ch.get("city") and _canon_city(ch["city"]) is None
    })
    if unknown:
        print(f"⚠️  Города каналов вне справочника cities.json: {', '.join(unknown)}")
    return groups


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


# --- LLM (OpenAI-совместимый API, по умолчанию Yandex AI Studio) ---

_SYSTEM_PROMPT = """Ты анализируешь посты из Telegram-канала крымского заведения.
Извлекай музыкальные мероприятия из текста поста.

ГЛАВНОЕ ПРАВИЛО: если в посте НЕТ музыкального мероприятия — верни пустой массив [].
НЕ создавай объект-заглушку с пустыми полями и пояснением в description.
НЕ пиши в description фразы вида «нет мероприятий», «не содержит анонса», «информации о мероприятии нет» —
такие описания запрещены, это значит, что события нет, и нужно вернуть [].

НЕ включай в результат:
- мастер-классы, интенсивы, курсы, обучение, танцевальные классы;
- «дни свободного творчества», открытые микрофоны без конкретных исполнителей;
- выставки, кинопоказы, лекции, ярмарки (если нет живой музыки);
- общие анонсы без конкретного исполнителя/группы на конкретную дату;
- экскурсии, музеи, прогулки, спортивные забеги, вечеринки без музыки, рекламу отеля;
- рассказы путешественников, новости заведения без анонса события.

ВАЖНО: правило для поля date.
- В каждом запросе указана дата публикации поста. Ориентируйся на неё, а не на свои знания.
- Если год события в тексте не указан — это анонс: бери год из даты публикации; если полученная дата оказывается раньше даты публикации — бери следующий год.
- Никогда не ставь год раньше года публикации поста.

ВАЖНО: поле artist должно быть заполнено всегда.
- Если в тексте назван конкретный исполнитель/группа — используй его.
- Если исполнитель не назван, но из текста понятно что за событие — придумай короткое название-описание (1-4 слова), например: «Живая музыка», «Джазовый вечер», «Акустический концерт», «Кавер-вечер», «Вечер романса», «Фолк-концерт» и т.п.
- НЕ оставляй artist: null — всегда генерируй осмысленное название из контекста.
- Если для события невозможно придумать осмысленное название артиста — события НЕТ, верни [].

Поля события:
- date: "YYYY-MM-DD" или null
- time: "HH:MM" или null
- artist: название группы/исполнителя или null
- event_type: "концерт" / "джем" / "трибьют" / "вечеринка" / "фестиваль" / "другое"
- venue: конкретное место проведения или null
- city: город Крыма или null
- price: цена, "бесплатно" или null
- description: 1-2 предложения"""


def _call_llm(prompt: str, max_retries: int = 2) -> str:
    """Вызывает OpenAI-совместимый LLM API (по умолчанию Yandex AI Studio).

    Настройки через env:
      LLM_API_URL   — endpoint /v1/chat/completions (дефолт: Yandex AI Studio)
      LLM_API_KEY   — API-ключ (Yandex: Authorization: Api-Key <key>)
      LLM_MODEL     — id модели (Yandex: gpt://<folder>/yandexgpt-lite/latest)
    Возвращает текст ответа или пустую строку при ошибке.
    """
    api_key = os.environ.get("LLM_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
    if not api_key:
        print(" [LLM_API_KEY не задан]", end="")
        return ""

    api_url = os.environ.get("LLM_API_URL", "https://ai.api.cloud.yandex.net/v1/chat/completions")
    model = os.environ.get("LLM_MODEL", "")
    if not model:
        folder = os.environ.get("YANDEX_FOLDER_ID", "")
        model = f"gpt://{folder}/yandexgpt-lite/latest" if folder else "yandexgpt-lite/latest"

    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
    }

    for attempt in range(max_retries + 1):
        try:
            resp = httpx.post(api_url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
        except httpx.TimeoutException:
            if attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
                continue
            print(" [llm timeout]", end="")
            return ""
        except httpx.HTTPStatusError as e:
            print(f" [llm error: {e.response.status_code} {e.response.text[:200]}]", end="")
            if attempt < max_retries:
                time.sleep(2 ** (attempt + 1))
                continue
            return ""
        except Exception as e:
            print(f" [llm exception: {e}]", end="")
            return ""
    return ""


def _parse_claude_json(raw: str):
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


_SCALAR_FIELDS = (
    "artist", "venue", "event_type", "genre", "price", "description",
    "date", "time", "source_channel", "source_city",
)


def _to_scalar(value):
    """Приводит значение поля к строке, если LLM вернул список/число."""
    if isinstance(value, str):
        if value.strip().lower() in ("null", "none", "undefined", "nan"):
            return None
        return value
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, "") and str(v).lower() not in ("null", "none"))
    if value is None:
        return None
    return str(value)


_REFUSAL_MARKERS = (
    "нет музыкальных", "нет музыкального", "нет мероприятий", "не содержит анонса",
    "не содержит музыкальных", "информации о музыкальном мероприятии нет",
    "не является музыкальным", "не анонсирует", "без музыкального сопровождения",
    "нет информации о музыкальном", "музыкальных мероприятий не",
    "без конкретного музыкального",
)

# Не-музыкальные форматы, которые yandexgpt-lite упорно извлекает как события,
# несмотря на запрет в системном промпте: кино, забеги, экскурсии, премьеры.
_NON_MUSIC_MARKERS = (
    "кино под открытым небом", "кинопоказ", "кино на стене",
    "премьера драмеди", "премьера фильма", "арт-забег", "утренний забег",
    "групповая экскурсия", "спортивный забег", "велоэкскурсия", "пешая экскурсия",
)


def _is_refusal_event(e: dict) -> bool:
    """True, если LLM вернул объект-заглушку вместо []: в description он сам
    признался, что мероприятия нет. Такие события отбрасываем всегда."""
    desc = (e.get("description") or "").lower()
    if any(m in desc for m in _REFUSAL_MARKERS):
        return True
    if any(m in desc for m in _NON_MUSIC_MARKERS):
        return True
    # Пустая заглушка: нет ни описания, ни артиста, ни площадки, ни даты
    if not desc and not e.get("artist") and not e.get("venue") and not e.get("date") and not e.get("time"):
        return True
    return False


def _only_event_dicts(events) -> list[dict]:
    """Отбрасывает элементы массива, которые не являются словарями событий.
    LLM изредка возвращает вместо объекта строку (например «нет событий»)."""
    cleaned = []
    for e in events:
        if not isinstance(e, dict):
            continue
        for field in _SCALAR_FIELDS:
            if field in e:
                e[field] = _to_scalar(e[field])
        if _is_refusal_event(e):
            continue
        cleaned.append(e)
    return cleaned


def _clean_batch_result(result: dict) -> dict:
    """Чистит результат батча: значение каждого url — массив словарей событий."""
    cleaned = {}
    for url, events in result.items():
        if isinstance(events, list):
            cleaned[url] = _only_event_dicts(events)
    return cleaned


def _post_date_str(post: dict) -> str:
    """Дата публикации поста в формате YYYY-MM-DD (для промпта и кэш-ключа)."""
    return (post.get("date") or "")[:10]


def fix_event_year(event: dict, post_date_iso: str) -> None:
    """Страховка от неверно угаданного года: анонс не может быть сильно раньше поста.

    Если дата события отстаёт от даты публикации больше чем на 60 дней —
    год угадан неверно; подставляем год публикации (или следующий).
    Небольшое отставание не трогаем: пост о только что прошедшем событии
    отфильтруется дальше как прошедший.
    """
    d = event.get("date")
    if not d or not post_date_iso:
        return
    try:
        ev = date.fromisoformat(str(d)[:10])
        pd = date.fromisoformat(post_date_iso[:10])
    except ValueError:
        return
    if (pd - ev).days <= 60:
        return
    for year in (pd.year, pd.year + 1):
        try:
            cand = ev.replace(year=year)
        except ValueError:  # 29 февраля в невисокосном году
            cand = date(year, 2, 28)
        if (pd - cand).days <= 60:
            event["date"] = cand.isoformat()
            return


def extract_events_single(post: dict, channel_meta: dict, image_path: str) -> list[dict]:
    """Извлекает события из одного поста. image_path сохраняется в кэш-ключе для уникальности."""
    text = post["text"]
    post_date = _post_date_str(post)
    cache_key = hashlib.sha256(("single:" + post_date + ":" + text + ":" + image_path).encode("utf-8")).hexdigest()[:16]
    cached = _cache_read(cache_key)
    if cached is not None:
        return cached

    user_text = f"""Заведение: {channel_meta['title']}, город: {channel_meta['city']}.
Дата публикации поста: {post_date}.

Текст поста:
\"\"\"
{text}
\"\"\"

Если пост содержит расписание/афишу на несколько дней — извлеки отдельное мероприятие на каждую дату ТОЛЬКО если для неё указан конкретный исполнитель/группа или другие детали (время, цена).
Если по дням нет конкретных деталей — верни [].

Верни JSON-массив событий. Если мероприятий нет — верни [].
Верни только JSON, без пояснений."""

    raw = _call_llm(user_text)
    result = _parse_claude_json(raw)
    if not isinstance(result, list):
        return []
    result = _only_event_dicts(result)
    _cache_write(cache_key, result)
    return result


def extract_events_multi(post: dict, channel_meta: dict, image_paths: list[str]) -> list[dict]:
    """Извлекает события из поста с несколькими картинками (только по тексту).
    Возвращает [events...] где каждое событие имеет поле image_indices."""
    text = post["text"]
    post_date = _post_date_str(post)
    print(f"\n  [multi] {post.get('url', '?')} {len(image_paths)} images", end="")
    cache_key = hashlib.sha256(("multi:" + post_date + ":" + text + ":" + ",".join(image_paths)).encode("utf-8")).hexdigest()[:16]
    print(f" key={cache_key}", end="")
    cached = _cache_read(cache_key)
    print(f" cache={cached is not None}", end="")
    if cached is not None:
        return _only_event_dicts(cached)

    user_text = f"""Заведение: {channel_meta['title']}, город: {channel_meta['city']}.
Дата публикации поста: {post_date}.

Текст поста:
\"\"\"
{text}
\"\"\"

К посту приложено {len(image_paths)} изображений (афиши/фото).

ОПРЕДЕЛИ СЦЕНАРИЙ по тексту:
1) Если анонсируется НЕСКОЛЬКО разных событий — создай отдельное событие на каждое с image_indices: [N].
2) Если одно событие с несколькими фото — одно событие с image_indices: [0, 1, ...].

Дополнительное поле:
- image_indices: список номеров картинок (начиная с 0), относящихся к событию

Верни JSON-массив событий с полем image_indices. Если мероприятий нет — верни [].
Верни только JSON, без пояснений."""

    raw = _call_llm(user_text)
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    print(f" [raw: {raw[:100]}]", end="")

    try:
        events = json.loads(raw)
    except json.JSONDecodeError:
        print(" [parse error]")
        return []
    if not isinstance(events, list):
        return []
    events = _only_event_dicts(events)
    print(f" -> {len(events)} events", end="")
    _cache_write(cache_key, events)
    return events


def extract_events_batch(posts: list[dict], channel_meta: dict) -> dict[str, list[dict]]:
    """Извлекает события из батча постов одним вызовом DeepSeek.
    Возвращает dict: post_url -> [events...].
    """
    if not posts:
        return {}

    cache_texts = [_post_date_str(p) + ":" + p["text"] for p in posts]
    cached = _cache_read("\n---\n".join(cache_texts))
    if cached is not None:
        print(f" [кэш]", end="")
        return _clean_batch_result(cached)

    posts_section = ""
    for i, post in enumerate(posts):
        url = post.get("url") or f"post_{i}"
        posts_section += f"\n--- POST {i+1} (url: {url}, дата публикации: {_post_date_str(post)}) ---\n{post['text']}\n"

    user_text = f"""Заведение: {channel_meta['title']}, город: {channel_meta['city']}.

{posts_section}

Для КАЖДОГО поста извлеки музыкальные мероприятия. Верни JSON-объект где ключи — url поста (точно как указано выше), а значения — массивы событий.

Если пост содержит расписание/афишу на несколько дней — извлеки отдельное мероприятие на каждую дату ТОЛЬКО если для неё указан конкретный исполнитель/группа или другие детали (время, цена).
Если по дням нет конкретных деталей — верни пустой массив [].

Если мероприятий нет ни в одном посте — верни {{}}.
Верни только JSON, без пояснений."""

    raw = _call_llm(user_text)
    result = _parse_claude_json(raw)
    if not isinstance(result, dict):
        return {}
    result = _clean_batch_result(result)
    _cache_write("\n---\n".join(cache_texts), result)
    return result


def fetch_max_posts(chat_id: int, token: str, days_back: int) -> list[dict]:
    from fetch_max import fetch_max_posts as _fetch
    return _fetch(chat_id, token, days_back)


def fetch_vk_posts(domain: str, token: str, days_back: int) -> list[dict]:
    from fetch_vk import fetch_vk_posts as _fetch
    return _fetch(domain, token, days_back)


def fetch_instagram_posts_wrapper(username: str, days_back: int) -> list[dict]:
    from fetch_instagram import fetch_instagram_posts as _fetch
    return _fetch(username, days_back)


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


# Сопоставление жанров afisha.ru со словарём сайта (нижний регистр)
_AFISHA_GENRE_MAP = {
    "эстрада": "поп",
    "шансон": "поп",
    "электроника": "поп",
    "авторская песня": "авторская",
    "хип-хоп/рэп": "хип-хоп",
}
_SITE_GENRES = {
    "поп", "классика", "рок", "джаз", "метал", "другое", "интерактив",
    "этно", "поп-рок", "фолк", "русский рок", "авторская", "инди",
    "хип-хоп", "панк-рок", "каверы", "юмор", "хоровая", "фолк-метал",
    "шоу", "лаунж", "медитативная", "рок-поп", "народная",
}


def _normalize_afisha_genre(g):
    if not g:
        return None
    g = g.strip().lower()
    g = _AFISHA_GENRE_MAP.get(g, g)
    return g if g in _SITE_GENRES else None


def process_afisha_ru(all_events: list):
    from fetch_afisha_ru import fetch_all_crimea
    print("\nАфиша (afisha.ru) — крымские города...")
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
            "source_channel": "afisha_ru",
            "source_city": post["_city"],
            "post_date": datetime.now(timezone.utc).isoformat(),
            "image": download_image(post.get("image")),
            "source_url": pre["source_url"],
            "genre": _normalize_afisha_genre(pre.get("genre")),
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


# Безусловные плейсхолдеры, которые может вернуть _fallback_artist — не имя
# исполнителя, а тип мероприятия (в отличие от веток с извлечением реального
# названия из кавычек типа «Концерт «X»» — те МОГУТ совпасть с настоящим
# артистом, поэтому в этот список не входят).
_GENERIC_ARTIST_LITERALS = {
    "Музыкальное лото", "DJ-сет", "Звукотерапия", "Квартирник", "Спектакль",
    "Фестиваль", "Живой концерт", "Музыкальный вечер", "Летний концерт",
    "Живой звук", "Открытие сезона", "Литературно-музыкальная гостиная",
    "Открытие летнего сезона", "Вечеринка", "Дегустация",
    "Массовое мероприятие", "Этно-проект",
}


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


def is_generic_artist(event: dict) -> bool:
    """True, если event['artist'] — не имя исполнителя, а тип мероприятия
    («DJ-сет», «Музыкальное лото», «Фестиваль» и т.п.), либо событие явно
    помечено флагом artist_is_generic.

    Сверяется с фиксированным списком безусловных плейсхолдеров
    (_GENERIC_ARTIST_LITERALS), а не пересчитывает _fallback_artist заново —
    иначе ветки с извлечением реального названия из кавычек («Концерт «X»»)
    ложно считались бы generic, если название совпало с уже настоящим
    значением artist (так ловилось «Скажите Джаз» — реальная джаз-группа).
    Применим и к событиям без проставленного флага (старые записи в
    events.json из прошлых прогонов).
    """
    if event.get("artist_is_generic"):
        return True
    return (event.get("artist") or "").strip() in _GENERIC_ARTIST_LITERALS


# ── Справочник городов (cities.json) ──────────────────────────────────────────
# Единственный источник правды по городам. Из него строятся:
#   _CITY_CANON  — точное имя/алиас → каноническое имя (для сверки готовых значений)
#   _CITY_RE     — регэкспы с падежами → каноническое имя (для поиска в тексте)
CITIES_FILE = "cities.json"

with open(CITIES_FILE, encoding="utf-8") as _f:
    _CITIES = json.load(_f)

# Окончания для распознавания падежей русского города в свободном тексте
# (существительные + прилагательные-названия вроде «Научный»).
_CITY_ENDINGS = r"(?:ого|ому|ым|ых|ые|ый|ий|ой|ом|ем|ей|а|я|у|ю|е|ы|и|ь|й|)"


def _city_stem(word: str) -> str:
    """Основа слова для поиска с падежами: отбрасывает окончание прилагательного или гласную/ь/й."""
    w = word.lower()
    for suf in ("ый", "ий", "ой"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)]
    if w and w[-1] in "аяьйыиеою":
        w = w[:-1]
    return w


def _norm(text: str) -> str:
    return (text or "").strip().lower().replace("ё", "е")


_CITY_CANON: dict[str, str] = {}   # нормализованное имя/алиас → каноническое имя
_CITY_RE: list = []                # [(compiled_regex, каноническое_имя)] для _detect_city

for _entry in _CITIES:
    _canon = _entry["name"]
    for _form in [_canon] + _entry.get("aliases", []):
        _CITY_CANON[_norm(_form)] = _canon
        if _entry.get("slug") == "all":
            continue  # «Крым» — это fallback, из текста его не «распознаём»
        if " " in _form:
            _CITY_RE.append((re.compile(re.escape(_form.lower())), _canon))
        else:
            _CITY_RE.append(
                (re.compile(r"\b" + re.escape(_city_stem(_form)) + _CITY_ENDINGS + r"\b"), _canon)
            )


def _canon_city(raw):
    """Точное значение → каноническое имя из справочника или None."""
    return _CITY_CANON.get(_norm(raw)) if raw else None


def _detect_city(text: str):
    """Ищет в свободном тексте любой город/алиас справочника (с падежами)."""
    low = (text or "").lower().replace("ё", "е")
    for rx, canon in _CITY_RE:
        if rx.search(low):
            return canon
    return None


def resolve_city(event: dict, channel: dict) -> str:
    """Определяет город события — всегда каноническое имя из справочника или «Крым»."""
    ch = _canon_city(channel.get("city"))
    if ch and ch != "Крым":          # канал привязан к конкретному городу — доверяем ему
        return ch
    detected = (
        _canon_city(event.get("city"))           # город от Claude, только если он из справочника
        or _detect_city(event.get("venue") or "")
        or _detect_city(event.get("description") or "")
    )
    return detected or "Крым"        # fallback


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


def _split_artist_field(artist: str) -> list[str]:
    """Разбивает поле artist по запятым верхнего уровня — не внутри скобок/«».

    Наивный artist.split(",") ломает случаи вроде «Дуэт «МысКрыма»
    (Дмитрий Ванханов, Вета)», где запятая — часть перечисления внутри
    скобок, а не разделитель артистов.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in artist:
        if ch in "(«":
            depth += 1
            current.append(ch)
        elif ch in ")»":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


_ARTIST_JOIN_RE = re.compile(
    r'\s+(и|&|\+|feat\.?|ft\.?|при участии|с участием)\s+', re.IGNORECASE,
)
_ARTIST_JOIN_WORDS = {"и", "&", "+", "feat", "feat.", "ft", "ft.",
                      "при участии", "с участием"}


def _artist_parts(name: str) -> list[str]:
    """Разбивает строку артиста на отдельные имена по разделителям."""
    # Режем по « и », « & », « + », «feat.», «ft.», «при участии», «с участием».
    # Запятую НЕ трогаем — она может быть частью названия или перечисления инструментов.
    result = _ARTIST_JOIN_RE.split(name)
    return [p.strip() for p in result
            if p.strip() and p.strip().lower() not in _ARTIST_JOIN_WORDS]


# Транслит для сравнения имён между кириллицей и латиницей (SHAMAN vs ШАМАН).
# Таблица та же, что в build_venues.py:slugify, для единообразия.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit_key(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in _normalize(text))


def _artist_set(event: dict) -> set:
    """Множество нормализованных имён артистов из события."""
    artist = event.get("artist") or ""
    names = set()
    for raw in _split_artist_field(artist):
        for name in _artist_parts(raw.strip()):
            n = _normalize(name)
            # убираем префиксы «группа», «band» для лучшего сравнения
            for prefix in ("группа ", "band ", "группа «", "«"):
                if n.startswith(prefix):
                    n = n[len(prefix):].strip()
            if n:
                names.add(n)
                names.add(_translit_key(n))  # ловит кириллица/латиница дубли
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
        for a in _split_artist_field(e.get("artist") or ""):
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


def _fetch_images_from_url(url: str) -> list[str]:
    """Fetches all image URLs from a Telegram post."""
    if not url or "t.me/" not in url:
        return []
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"},
                         follow_redirects=True, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        for wrap in soup.select(".tgme_widget_message_photo_wrap"):
            style = wrap.get("style", "")
            if "url(" in style:
                img_url = style.split("url('")[-1].split("')")[0]
                if img_url and img_url not in images:
                    images.append(img_url)
        return images
    except Exception:
        return []


def _redistribute_images(events: list[dict]) -> int:
    """Перескачивает картинки из постов и распределяет по событиям.
    Нужно для старых событий из кэша/архива у которых одна картинка на всех.
    Возвращает количество обновлённых событий."""
    by_url = {}
    for e in events:
        url = e.get("source_url", "")
        if url and "t.me/" in url:
            by_url.setdefault(url, []).append(e)

    updated = 0
    for url, group in by_url.items():
        # Skip if already has multiple distinct images
        existing = set()
        for e in group:
            for img in (e.get("images") or []):
                existing.add(img)
            if e.get("image"):
                existing.add(e["image"])
        if len(existing) > 1:
            continue

        raw_urls = _fetch_images_from_url(url)
        if len(raw_urls) <= 1:
            continue

        local = []
        for u in raw_urls:
            p = download_image(u)
            if p:
                local.append(p)
        if len(local) <= 1:
            continue

        for idx, e in enumerate(group):
            e["image"] = local[idx % len(local)]
            # Без image_index не знаем какая картинка "своя" — ставим только primary
            e["images"] = None
            updated += 1

    return updated


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


def process_channels(channels, all_events, get_posts_fn, days_back: int = DAYS_BACK):
    for channel in channels:
        label = channel.get("username") or channel.get("domain") or str(channel.get("chat_id"))
        print(f"\nЧитаю {label} ({channel['title']})...")
        try:
            posts = get_posts_fn(channel)
            print(f"  Постов за {days_back} дней: {len(posts)}")
        except Exception as e:
            print(f"  Ошибка: {e}")
            continue

        if not posts:
            print(f"  Найдено событий: 0          ")
            continue

        # Разделяем: multi-image (отдельно) и single-image (батчим)
        multi_posts = [p for p in posts if p.get("images") and len(p["images"]) > 1]
        single_posts = [p for p in posts if not p.get("images") or len(p.get("images") or []) <= 1]

        channel_events = 0

        # Multi-image — отдельный вызов на каждый пост
        for post in multi_posts:
            post_url = post.get("url") or ""
            print(f"  Multi-image: {post_url} ({len(post['images'])} картинок)...", end="")

            local = []
            for u in post["images"]:
                p = download_image(u)
                if p:
                    local.append(p)

            if not local:
                print(" нет картинок")
                continue

            events = extract_events_multi(post, channel, local)
            print(f" +{len(events)}")

            for event in events:
                event["source_channel"] = label
                event["source_city"] = resolve_city(event, channel)
                event.pop("city", None)
                if not event.get("venue"):
                    event["venue"] = channel["title"]
                event["post_date"] = post["date"]
                fix_event_year(event, post["date"])

                img_indices = event.pop("image_indices", None) or event.pop("image_index", None)
                if img_indices is None:
                    img_indices = [0]
                elif not isinstance(img_indices, list):
                    img_indices = [img_indices]
                if local and img_indices:
                    selected = []
                    for idx in img_indices:
                        if isinstance(idx, int) and 0 <= idx < len(local):
                            selected.append(local[idx])
                    if selected:
                        event["image"] = selected[0]
                        event["images"] = selected if len(selected) > 1 else None
                    else:
                        event["image"] = local[0]
                        event["images"] = None
                elif local:
                    event["image"] = local[0]
                    event["images"] = None
                event["source_url"] = post_url
                all_events.append(event)
                channel_events += 1

        # Single-image — батчим
        batches = [single_posts[i:i + BATCH_SIZE] for i in range(0, len(single_posts), BATCH_SIZE)]
        if batches:
            images_map = _download_all_images(single_posts)

            for bi, batch in enumerate(batches):
                print(f"  Батч {bi + 1}/{len(batches)} ({len(batch)} постов)...", end="")

                batch_result = extract_events_batch(batch, channel)

                for post in batch:
                    post_url = post.get("url") or ""
                    events = batch_result.get(post_url, [])
                    local_images = images_map.get(post_url, [])

                    for idx, event in enumerate(events):
                        event["source_channel"] = label
                        event["source_city"] = resolve_city(event, channel)
                        event.pop("city", None)
                        if not event.get("venue"):
                            event["venue"] = channel["title"]
                        event["post_date"] = post["date"]
                        fix_event_year(event, post["date"])

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


def main(days_back: int = DAYS_BACK):
    tg_channels, max_channels, vk_channels, ig_channels = load_channels()

    all_events = []

    process_channels(tg_channels, all_events, lambda ch: fetch_posts(ch["username"], days_back), days_back)

    max_token = os.environ.get("MAX_BOT_TOKEN", "")
    active_max = [c for c in max_channels if c.get("chat_id")]
    if active_max and max_token:
        process_channels(
            active_max, all_events, lambda ch: fetch_max_posts(ch["chat_id"], max_token, days_back), days_back
        )
    elif active_max:
        print("\nMax-каналы настроены, но MAX_BOT_TOKEN не задан — пропускаю.")

    vk_token = os.environ.get("VK_SERVICE_TOKEN", "")
    if vk_channels and vk_token:
        process_channels(
            vk_channels, all_events, lambda ch: fetch_vk_posts(ch["domain"], vk_token, days_back), days_back
        )
    elif vk_channels:
        print("\nVK-каналы настроены, но VK_SERVICE_TOKEN не задан — пропускаю.")

    ig_user = os.environ.get("IG_USERNAME", "")
    ig_pass = os.environ.get("IG_PASSWORD", "")
    ig_proxy = os.environ.get("IG_PROXY", "")
    if ig_channels and ig_user and ig_pass:
        print("\nInstagram — пропускаю (долго и нестабильно)")
        # process_channels(
        #     ig_channels, all_events, lambda ch: fetch_instagram_posts_wrapper(ch["username"], days_back)
        # )
    elif ig_channels:
        print("\nInstagram-каналы настроены, но IG_USERNAME / IG_PASSWORD не заданы — пропускаю.")

    process_yandex_afisha(all_events)

    process_afisha_ru(all_events)

    # Перераспределяем картинки: скачиваем все из постов и назначаем разным событиям
    img_updated = _redistribute_images(all_events)
    if img_updated:
        print(f"Картинки обновлены: {img_updated} событий")

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

    # Назначаем стабильный id (сохраняем существующий, генерируем для новых)
    for e in merged:
        if not e.get("id"):
            key = f"{e.get('source_url','')}-{e.get('date','')}-{e.get('artist','')}"
            e["id"] = hashlib.md5(key.encode()).hexdigest()[:8]

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
        # LLM иногда возвращает строку "null" вместо None
        artist = e.get("artist")
        if isinstance(artist, str) and artist.strip().lower() in ("null", "none", "undefined"):
            artist = None
        if artist is None:
            e["artist"] = None
            continue
        parts = _artist_parts(artist)
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
        e["artist"] = _to_scalar(e["artist"])

    # Проставляем жанр и артиста там, где их ещё нет
    genre_added = 0
    artist_extracted = 0
    artist_fallback = 0
    for e in merged:
        # Фолбэк артиста из описания
        if not e.get("artist"):
            extracted = _extract_artist_from_description(e.get("description") or "")
            if extracted:
                # Извлечено из кавычек/паттерна — это попытка настоящего имени,
                # а не плейсхолдер, флаг generic не ставим.
                e["artist"] = extracted
                artist_extracted += 1
            else:
                # Фолбэк по типу события
                fb = _fallback_artist(e)
                if fb:
                    e["artist"] = fb
                    e["artist_is_generic"] = fb in _GENERIC_ARTIST_LITERALS
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

    # Финальная отбраковка мусора: события-заглушки (LLM вернул объект вместо [])
    # и не-музыкальные форматы. Применяется ко всей базе, чтобы чистить и старые
    # записи, попавшие в неё до появления фильтра.
    before_filter = len(merged)
    merged = [e for e in merged if not _is_refusal_event(e)]
    removed = before_filter - len(merged)
    if removed:
        print(f"Убрано мусорных событий (заглушки/не-музыкальные): {removed}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Готово. Сохранено в {OUTPUT_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Глубина парсинга в днях (по умолчанию: DAYS_BACK)")
    args = parser.parse_args()
    days = args.days if args.days else DAYS_BACK
    if args.days:
        print(f"Глубина парсинга: {days} дней")
    main(days_back=days)
