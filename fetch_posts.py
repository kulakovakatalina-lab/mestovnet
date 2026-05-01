import json
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

DAYS_BACK = 14
USERNAMES = ["rocknroll_92", "nb_yalta", "artkovcheg"]


def fetch_posts(username: str) -> list[dict]:
    url = f"https://t.me/s/{username}"
    headers = {"User-Agent": "Mozilla/5.0"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)

    response = httpx.get(url, headers=headers, follow_redirects=True, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    posts = []

    for msg in soup.select(".tgme_widget_message"):
        time_tag = msg.select_one("time[datetime]")
        text_tag = msg.select_one(".tgme_widget_message_text")
        if not time_tag or not text_tag:
            continue
        post_dt = datetime.fromisoformat(time_tag["datetime"])
        if post_dt < cutoff:
            continue

        image_url = None
        photo_wrap = msg.select_one(".tgme_widget_message_photo_wrap")
        if photo_wrap:
            style = photo_wrap.get("style", "")
            if "background-image:url(" in style:
                image_url = style.split("url('")[1].split("'")[0]

        posts.append({
            "channel": username,
            "date": post_dt.isoformat(),
            "text": text_tag.get_text(separator="\n").strip(),
            "image": image_url,
        })

    return posts


all_posts = []
for username in USERNAMES:
    print(f"Fetching @{username}...")
    try:
        posts = fetch_posts(username)
        print(f"  {len(posts)} posts")
        all_posts.extend(posts)
    except Exception as e:
        print(f"  Error: {e}")

with open("raw_posts.json", "w", encoding="utf-8") as f:
    json.dump(all_posts, f, ensure_ascii=False, indent=2)

print(f"\nTotal: {len(all_posts)} posts saved to raw_posts.json")
