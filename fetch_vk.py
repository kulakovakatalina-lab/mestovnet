"""
Парсинг постов из открытых групп ВКонтакте через VK API wall.get.

Получить токен: https://vk.com/apps?act=manage
  → Создать приложение (тип «Standalone» или «Сервисное»)
  → Скопировать сервисный ключ доступа
  → Записать в .env: VK_SERVICE_TOKEN=...

Токен нужен только для чтения публичных стен (scope не требует прав пользователя).
"""

from datetime import datetime, timedelta, timezone

import httpx

VK_API = "https://api.vk.com/method/wall.get"
VK_VERSION = "5.131"


def fetch_vk_posts(domain: str, token: str, days_back: int = 14) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff_ts = int(cutoff.timestamp())

    params = {
        "domain": domain,
        "count": 100,
        "filter": "owner",
        "access_token": token,
        "v": VK_VERSION,
    }

    response = httpx.get(VK_API, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise RuntimeError(f"VK API error {data['error']['error_code']}: {data['error']['error_msg']}")

    posts = []
    for item in data["response"]["items"]:
        if item.get("marked_as_ads"):
            continue
        if item["date"] < cutoff_ts:
            continue
        text = item.get("text", "").strip()
        if not text:
            continue

        post_dt = datetime.fromtimestamp(item["date"], tz=timezone.utc)

        image_url = None
        for attachment in item.get("attachments", []):
            if attachment["type"] == "photo":
                sizes = attachment["photo"].get("sizes", [])
                if sizes:
                    largest = max(sizes, key=lambda s: s.get("width", 0))
                    image_url = largest.get("url")
                break

        posts.append({
            "date": post_dt.isoformat(),
            "text": text,
            "image": image_url,
            "url": f"https://vk.com/wall{item['owner_id']}_{item['id']}",
        })

    return posts


if __name__ == "__main__":
    import json
    import os
    import sys

    token = os.environ.get("VK_SERVICE_TOKEN", "")
    if not token:
        print("Задайте VK_SERVICE_TOKEN в .env", file=sys.stderr)
        sys.exit(1)

    domain = sys.argv[1] if len(sys.argv) > 1 else "gastrodvor.yalta"
    print(f"Парсю vk.com/{domain}...")
    posts = fetch_vk_posts(domain, token)
    print(f"Найдено постов: {len(posts)}")
    print(json.dumps(posts[:3], ensure_ascii=False, indent=2))
