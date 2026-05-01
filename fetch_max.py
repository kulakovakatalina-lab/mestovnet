import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

MAX_API = "https://platform-api.max.ru"
DAYS_BACK = 14


def _headers(token: str) -> dict:
    return {"Authorization": token}


def fetch_max_posts(chat_id: int, token: str, days_back: int = DAYS_BACK) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    params = {
        "chat_id": chat_id,
        "count": 100,
        "from": int(cutoff.timestamp()),
    }

    resp = httpx.get(f"{MAX_API}/messages", headers=_headers(token), params=params, timeout=15)
    resp.raise_for_status()

    posts = []
    for msg in resp.json().get("messages", []):
        ts = msg.get("timestamp")
        body = msg.get("body", {})
        text = body.get("text", "").strip()
        if not ts or not text:
            continue

        post_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if post_dt < cutoff:
            continue

        image_url = None
        for att in body.get("attachments", []):
            payload = att.get("payload", {})
            photos = payload.get("photos", {})
            if photos:
                image_url = next(iter(photos.values()), {}).get("url")
                break

        posts.append({
            "channel": str(chat_id),
            "date": post_dt.isoformat(),
            "text": text,
            "image": image_url,
        })

    return posts


def discover_chat_ids(token: str):
    """Long-poll for updates — add the bot to a Max channel, chat_id will appear here."""
    print("Ожидаю обновления (добавьте бота в каналы)... Ctrl+C для остановки\n")
    marker = None
    while True:
        params = {"timeout": 30}
        if marker:
            params["marker"] = marker
        try:
            resp = httpx.get(
                f"{MAX_API}/updates", headers=_headers(token), params=params, timeout=35
            )
            resp.raise_for_status()
            data = resp.json()
            marker = data.get("marker")
            for upd in data.get("updates", []):
                upd_type = upd.get("update_type", "")
                if upd_type == "bot_added":
                    chat = upd.get("chat", {})
                    print(f"[bot_added] chat_id={chat.get('chat_id')}  title={chat.get('title')!r}")
                elif upd_type == "message_created":
                    msg = upd.get("message", {})
                    recipient = msg.get("recipient", {})
                    cid = recipient.get("chat_id")
                    text_preview = msg.get("body", {}).get("text", "")[:60]
                    print(f"[message]  chat_id={cid}  preview={text_preview!r}")
        except KeyboardInterrupt:
            print("\nОстановлено.")
            break
        except Exception as e:
            print(f"Ошибка: {e}")


if __name__ == "__main__":
    token = os.environ.get("MAX_BOT_TOKEN", "")
    if not token:
        print("Укажите MAX_BOT_TOKEN в переменных окружения или в .env")
        sys.exit(1)

    if "--discover" in sys.argv:
        discover_chat_ids(token)
        sys.exit(0)

    with open("channels.json", encoding="utf-8") as f:
        config = json.load(f)

    max_channels = config.get("max_channels", [])
    if not max_channels:
        print("Нет Max-каналов в channels.json")
        sys.exit(0)

    all_posts = []
    for ch in max_channels:
        chat_id = ch.get("chat_id", 0)
        if not chat_id:
            print(f"  Пропускаю {ch['title']} — chat_id не задан (запустите --discover)")
            continue
        print(f"Читаю {ch['title']} (chat_id={chat_id})...")
        try:
            posts = fetch_max_posts(chat_id, token)
            print(f"  {len(posts)} постов")
            for p in posts:
                p["source_channel"] = str(chat_id)
                p["source_title"] = ch["title"]
                p["source_city"] = ch["city"]
            all_posts.extend(posts)
        except Exception as e:
            print(f"  Ошибка: {e}")

    with open("raw_posts_max.json", "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)

    print(f"\nИтого: {len(all_posts)} постов → raw_posts_max.json")
