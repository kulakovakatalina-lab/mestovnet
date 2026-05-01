"""
Instagram fetcher via instagrapi (private mobile API).

Setup:
  pip install instagrapi
  Set IG_USERNAME and IG_PASSWORD in .env

Session is cached to ig_session.json to avoid re-login on each run.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_FILE = "ig_session.json"
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    try:
        from instagrapi import Client
        from instagrapi.exceptions import LoginRequired
    except ImportError:
        raise ImportError("instagrapi не установлен. Запустите: pip install instagrapi")

    username = os.environ.get("IG_USERNAME")
    password = os.environ.get("IG_PASSWORD")
    if not username or not password:
        raise ValueError("Не заданы IG_USERNAME / IG_PASSWORD в .env")

    cl = Client()
    cl.delay_range = [2, 5]  # случайная пауза между запросами (сек)

    session_path = Path(SESSION_FILE)
    if session_path.exists():
        try:
            cl.load_settings(session_path)
            cl.login(username, password)
        except (LoginRequired, Exception):
            # сессия устарела — логинимся заново
            session_path.unlink(missing_ok=True)
            cl.login(username, password)
    else:
        cl.login(username, password)

    cl.dump_settings(session_path)
    _client = cl
    return cl


def _extract_image_url(media):
    """
    Возвращает URL картинки для любого типа медиа:
    - фото → image_versions2 (основное изображение)
    - видео → thumbnail_url (первый кадр, генерируется Instagram)
    - альбом → картинка первого элемента
    """
    # Видео: thumbnail_url — это первый кадр
    if media.thumbnail_url:
        return str(media.thumbnail_url)
    # Фото: основное изображение в image_versions2
    iv2 = getattr(media, "image_versions2", None)
    if iv2 and getattr(iv2, "candidates", None):
        return str(iv2.candidates[0].url)
    # Альбом: берём первый ресурс
    resources = getattr(media, "resources", None) or []
    if resources:
        first = resources[0]
        if first.thumbnail_url:
            return str(first.thumbnail_url)
        iv2 = getattr(first, "image_versions2", None)
        if iv2 and getattr(iv2, "candidates", None):
            return str(iv2.candidates[0].url)
    return None


def fetch_instagram_posts(username: str, days_back: int) -> list[dict]:
    """
    Возвращает список постов из Instagram-профиля за последние days_back дней.
    Каждый пост: {"date": ISO-строка, "text": подпись, "image": url или None}
    """
    cl = _get_client()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        user_id = cl.user_id_from_username(username)
        # instagrapi не гарантирует порядок — сортируем сами по убыванию даты
        medias = sorted(
            cl.user_medias(user_id, amount=15),
            key=lambda m: m.taken_at,
            reverse=True,
        )
    except Exception as e:
        raise RuntimeError(f"Ошибка при получении постов @{username}: {e}")

    posts = []
    for media in medias:
        taken_at = media.taken_at
        if taken_at.tzinfo is None:
            taken_at = taken_at.replace(tzinfo=timezone.utc)
        if taken_at < cutoff:
            continue

        caption = (media.caption_text or "").strip()
        if not caption:
            continue  # пост без подписи — нечего анализировать

        image_url = _extract_image_url(media)

        posts.append({
            "date": taken_at.isoformat(),
            "text": caption,
            "image": image_url,
            "url": f"https://www.instagram.com/p/{media.code}/",
        })

        time.sleep(0.5)  # небольшая пауза между итерациями

    return posts
