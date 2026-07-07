"""
Шаг 1: скачивает посты из Telegram и Яндекс.Афиши.
Результат: posts.json (сырые посты) + yandex_events.json (готовые события).
Не использует Claude/AI — только HTTP-запросы.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

CHANNELS_FILE = "channels.json"
POSTS_FILE = "posts.json"
YANDEX_FILE = "yandex_events.json"
AFISHA_FILE = "afisha_events.json"
DAYS_BACK = 2
IMAGES_DIR = "images/events"

# Жанры afisha.ru → словарь сайта (нижний регистр)
_AFISHA_GENRE_MAP = {
    "эстрада": "поп", "шансон": "поп", "электроника": "поп",
    "авторская песня": "авторская", "хип-хоп/рэп": "хип-хоп",
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


def download_image(url: str):
    if not url:
        return None
    os.makedirs(IMAGES_DIR, exist_ok=True)
    url_hash = hashlib.md5(url.encode()).hexdigest()
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
        ct = resp.headers.get("content-type", "")
        guessed_ext = mimetypes.guess_extension(ct.split(";")[0].strip())
        if guessed_ext and guessed_ext.lstrip(".") in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = guessed_ext.lstrip(".")
            local_path = os.path.join(IMAGES_DIR, f"{url_hash}.{ext}")
        with open(local_path, "wb") as f:
            f.write(resp.content)
        return f"/{local_path}"
    except Exception:
        return url


def fetch_tg_posts(username: str, days_back: int) -> list[dict]:
    url = f"https://t.me/s/{username}"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"},
                     follow_redirects=True, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    posts = []
    for msg in soup.select(".tgme_widget_message"):
        time_tag = (msg.select_one(".tgme_widget_message_date time[datetime]")
                    or msg.select_one("time[datetime]"))
        text_tag = msg.select_one(".tgme_widget_message_text")
        if not time_tag or not text_tag:
            continue
        post_dt = datetime.fromisoformat(time_tag["datetime"])
        if post_dt < cutoff:
            continue

        image_urls = []
        for wrap in msg.select(".tgme_widget_message_photo_wrap"):
            style = wrap.get("style", "")
            if "url(" in style:
                img_url = style.split("url('")[-1].split("')")[0]
                if img_url and img_url not in image_urls:
                    image_urls.append(img_url)

        thumbnail_url = None
        video_tag = msg.select_one(".tgme_widget_message_video_thumb")
        if video_tag and video_tag.get("style"):
            style = video_tag["style"]
            if "url(" in style:
                thumbnail_url = style.split("url('")[-1].split("')")[0]

        data_post = msg.get("data-post")
        post_url = f"https://t.me/{data_post}" if data_post else None

        posts.append({
            "date": post_dt.isoformat(),
            "text": text_tag.get_text(separator="\n").strip(),
            "image_urls": image_urls,
            "thumbnail_url": thumbnail_url,
            "url": post_url,
        })
    return posts


def load_channels():
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data["channels"]


def main(days_back: int = DAYS_BACK):
    channels = load_channels()
    all_posts = []

    for ch in channels:
        username = ch.get("username")
        if not username:
            continue
        print(f"Читаю {username} ({ch['title']})...", end="")
        try:
            raw = fetch_tg_posts(username, days_back)
        except Exception as e:
            print(f" ошибка: {e}")
            continue

        for post in raw:
            local_images = []
            for u in post["image_urls"]:
                p = download_image(u)
                if p:
                    local_images.append(p)
            if not local_images and post["thumbnail_url"]:
                p = download_image(post["thumbnail_url"])
                if p:
                    local_images.append(p)

            all_posts.append({
                "channel_username": username,
                "channel_title": ch["title"],
                "channel_city": ch["city"],
                "url": post["url"],
                "date": post["date"],
                "text": post["text"],
                "local_images": local_images,
            })

        print(f" {len(raw)} постов")

    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    print(f"\nСохранено {len(all_posts)} постов → {POSTS_FILE}")

    # Яндекс.Афиша — не нуждается в Claude
    print("\nЯндекс.Афиша...")
    try:
        from fetch_yandex_afisha import fetch_all_crimea
        yandex_posts = fetch_all_crimea()
        yandex_events = []
        for post in yandex_posts:
            pre = post["_prefilled"]
            yandex_events.append({
                "date": pre["date"],
                "time": pre["time"],
                "artist": pre["artist"],
                "venue": pre["venue"],
                "event_type": pre["event_type"],
                "price": pre["price"],
                "description": pre["description"],
                "source_channel": "yandex_afisha",
                "source_city": post["_city"],
                "post_date": datetime.now(timezone.utc).isoformat(),
                "image": download_image(post.get("image")),
                "source_url": pre["source_url"],
            })
        with open(YANDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(yandex_events, f, ensure_ascii=False, indent=2)
        print(f"Яндекс.Афиша: {len(yandex_events)} событий → {YANDEX_FILE}")
    except Exception as e:
        print(f"Яндекс.Афиша ошибка: {e}")
        with open(YANDEX_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    # Афиша (afisha.ru) — не нуждается в Claude
    print("\nАфиша (afisha.ru)...")
    try:
        from fetch_afisha_ru import fetch_all_crimea as fetch_afisha_crimea
        afisha_posts = fetch_afisha_crimea()
        afisha_events = []
        for post in afisha_posts:
            pre = post["_prefilled"]
            afisha_events.append({
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
            })
        with open(AFISHA_FILE, "w", encoding="utf-8") as f:
            json.dump(afisha_events, f, ensure_ascii=False, indent=2)
        print(f"Афиша (afisha.ru): {len(afisha_events)} событий → {AFISHA_FILE}")
    except Exception as e:
        print(f"Афиша (afisha.ru) ошибка: {e}")
        with open(AFISHA_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DAYS_BACK)
    args = parser.parse_args()
    main(days_back=args.days)
