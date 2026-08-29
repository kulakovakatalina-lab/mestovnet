"""
Парсер Яндекс.Афиши для крымских городов.
Парсим листинговую страницу: без JS, один запрос на город.
Картинки — из атрибута data-src (lazy-loading).
"""

import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

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

# Ротация User-Agent для обхода блокировок
_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def _get_headers() -> dict:
    """Возвращает заголовки с случайным User-Agent."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def _fetch_with_retry(url: str, max_retries: int = 3) -> httpx.Response:
    """Выполняет запрос с повторами при ошибках 403/429/5xx."""
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = httpx.get(url, headers=_get_headers(), follow_redirects=True, timeout=20)
            if resp.status_code == 403:
                # Пробуем с другим UA
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code in (403, 429, 500, 502, 503, 504):
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            raise
        except Exception as e:
            last_error = e
            time.sleep(2 ** attempt + random.uniform(0, 1))
            continue
    raise last_error or Exception(f"Failed after {max_retries} retries")


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


def _fetch_event_description(event_url: str) -> Optional[str]:
    """Парсит страницу события: извлекает блок «О концерте»."""
    try:
        resp = _fetch_with_retry(event_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        h3 = soup.find("h3", string=re.compile(r"О концерте|О мероприятии"))
        if h3:
            desc_div = h3.find_next_sibling("div")
            if desc_div:
                text = desc_div.get_text(strip=True)
                return text if len(text) > 30 else None
        return None
    except Exception:
        return None


def fetch_yandex_afisha_posts(city_slug: str, city_name: str) -> list[dict]:
    url = f"https://afisha.yandex.ru/{city_slug}/concert"

    resp = _fetch_with_retry(url)

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

        # Загружаем блок «О концерте» со страницы события
        description = _fetch_event_description(link)
        if not description:
            description = f"{artist} в {venue}, {city_name}."

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
                "description": description,
                "source_url": link,
            },
        })

    return posts


def _is_within_horizon(date_value: str, today: date, days_back: int) -> bool:
    """Проверяет, что событие приходится на заданный горизонт вперёд."""
    try:
        event_date = date.fromisoformat(date_value)
    except (TypeError, ValueError):
        return False
    horizon = today + timedelta(days=max(days_back, 0))
    return today <= event_date <= horizon


def fetch_all_crimea(days_back: int = 90) -> list[dict]:
    """Возвращает события на сегодня и в пределах горизонта вперёд."""
    all_posts = []
    today = date.today()
    for city in CITIES:
        try:
            posts = fetch_yandex_afisha_posts(city["slug"], city["name"])
            for p in posts:
                if not _is_within_horizon(p.get("date"), today, days_back):
                    continue
                p["_city"] = city["name"]
                all_posts.append(p)
            time.sleep(5)  # пауза между городами (увеличена для обхода rate limit)
        except Exception as e:
            print(f"  Ошибка {city['slug']}: {e}")
    return all_posts
