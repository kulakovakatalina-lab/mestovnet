"""
Парсер Яндекс.Афиши для крымских городов.
Парсим листинговую страницу: без JS, один запрос на город.
Картинки — из атрибута data-src (lazy-loading).
"""

import re
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

CITIES = [
    {"slug": "simferopol", "name": "Симферополь"},
    {"slug": "sevastopol", "name": "Севастополь"},
    {"slug": "yalta",      "name": "Ялта"},
    {"slug": "kerch",      "name": "Керчь"},
]

MONTH_MAP = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

_HEADERS = {
    # Мобильный UA — не вызывает капчу при умеренной частоте запросов
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def _parse_date_time(date_str: str):
    """'10 мая, 20:00' → ('2026-05-10', '20:00')"""
    m = re.match(r"(\d+)\s+(\S+),\s+(\d+:\d+)", date_str.strip())
    if not m:
        return None, None
    day, month_ru, t = int(m.group(1)), m.group(2), m.group(3)
    month = MONTH_MAP.get(month_ru)
    if not month:
        return None, None
    year = datetime.now().year
    now = datetime.now()
    if month < now.month or (month == now.month and day < now.day):
        year += 1
    return f"{year}-{month:02d}-{day:02d}", t


def fetch_yandex_afisha_posts(city_slug: str, city_name: str) -> list[dict]:
    url = f"https://afisha.yandex.ru/{city_slug}/concert"

    resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    posts = []

    for card in soup.select("div.DggLY9"):
        lis = [li.get_text(strip=True) for li in card.select("li")]
        if len(lis) < 2:
            continue

        date_str = lis[0]   # "10 мая, 20:00"
        venue    = lis[1]   # "Наследие"

        artist_block = card.select_one("div.P6cQEI")
        artist = (
            artist_block.get_text(strip=True).replace(date_str, "").replace(venue, "").strip()
            if artist_block else None
        )

        price_tag = card.select_one("span.nGpc5s")
        price = price_tag.get_text(strip=True) if price_tag else None

        link_tag = card.select_one("a[href]")
        link = "https://afisha.yandex.ru" + link_tag["href"] if link_tag else url

        # Яндекс использует lazy-loading: картинка в data-src
        image = None
        img_tag = card.select_one("img[data-src]") or card.select_one("img[src]")
        if img_tag:
            src = img_tag.get("data-src") or img_tag.get("src", "")
            if src and not src.startswith("data:"):
                image = src

        date, t = _parse_date_time(date_str)
        if not date:
            continue

        posts.append({
            "date": date,
            "text": (
                f"{artist} — концерт в {venue}. {date_str}. "
                f"Билеты: {price or 'цена не указана'}. Ссылка: {link}"
            ),
            "image": image,
            "_prefilled": {
                "artist": artist,
                "venue": venue,
                "date": date,
                "time": t,
                "price": price,
                "event_type": "концерт",
                "description": f"{artist} в {venue}, {city_name}.",
                "source_url": link,
            },
        })

    return posts


def fetch_all_crimea(days_back: int = 90) -> list[dict]:
    """Возвращает посты со всех крымских городов."""
    all_posts = []
    for city in CITIES:
        try:
            posts = fetch_yandex_afisha_posts(city["slug"], city["name"])
            for p in posts:
                p["_city"] = city["name"]
            all_posts.extend(posts)
            time.sleep(2)  # пауза между городами
        except Exception as e:
            print(f"  Ошибка {city['slug']}: {e}")
    return all_posts
