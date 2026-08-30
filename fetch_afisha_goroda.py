"""Сборщик концертов с afishagoroda.ru для городов Крыма."""

import re
import time
from datetime import date, datetime
from typing import Optional, Tuple

import httpx
from bs4 import BeautifulSoup

CITIES = (
    {"subdomain": "simferopol", "city": "Симферополь"},
    {"subdomain": "sevastopol", "city": "Севастополь"},
    {"subdomain": "yalta", "city": "Ялта"},
    {"subdomain": "alushta", "city": "Алушта"},
    {"subdomain": "koktebel", "city": "Коктебель"},
    {"subdomain": "sudak", "city": "Судак"},
    {"subdomain": "kerch", "city": "Керчь"},
    {"subdomain": "feo", "city": "Феодосия"},
    {"subdomain": "evp", "city": "Евпатория"},
)
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MestovNet/1.0)"}
NON_MUSIC_MARKERS = ("стендап", "stand up", "стэнд-ап")


def _parse_date_time(text: str, today: date) -> Tuple[Optional[str], Optional[str]]:
    match = re.search(r"(\d{1,2})\s+([а-яё]+).*?(\d{1,2}:\d{2})", text.lower())
    if not match or match.group(2) not in MONTHS:
        return None, None
    try:
        month, day = MONTHS[match.group(2)], int(match.group(1))
        year = today.year + int((month, day) < (today.month, today.day))
        return date(year, month, day).isoformat(), match.group(3)
    except ValueError:
        return None, None


def parse_listing(html: str, city: str, base_url: str, today: date) -> list[dict]:
    posts = []
    for card in BeautifulSoup(html, "html.parser").select(".events-elem"):
        content = card.select_one(".events-elem_content")
        title = content.select_one("a.title[href]") if content else None
        when = content.select_one(".date--date-start") if content else None
        place = content.select_one(".place") if content else None
        if not title or not when or not place:
            continue
        event_date, event_time = _parse_date_time(when.get_text(" ", strip=True), today)
        if not event_date:
            continue
        artist, venue = title.get_text(" ", strip=True), place.get_text(" ", strip=True)
        if any(marker in artist.lower() for marker in NON_MUSIC_MARKERS):
            continue
        url = title["href"] if title["href"].startswith("http") else base_url + title["href"]
        price = content.select_one(".price")
        image = card.select_one("img.img[src]")
        image_url = image["src"] if image else None
        if image_url and image_url.startswith("/"):
            image_url = base_url + image_url
        posts.append({"date": event_date, "image": image_url, "_city": city,
            "text": f"{artist} — концерт. {venue}, {city}. {event_date} {event_time}. Ссылка: {url}",
            "_prefilled": {"artist": artist, "venue": venue, "date": event_date, "time": event_time,
                "price": price.get_text(" ", strip=True) if price else None, "event_type": "концерт",
                "description": f"{artist} — концерт в {venue}, {city}.", "source_url": url}})
    return posts


def fetch_all_crimea(days_back: int = 90) -> list[dict]:
    today, posts, seen = datetime.now().date(), [], set()
    latest = date.fromordinal(today.toordinal() + max(days_back, 0))
    for city in CITIES:
        base_url = f"https://{city['subdomain']}.afishagoroda.ru"
        try:
            response = httpx.get(f"{base_url}/events/koncert", headers=HEADERS, follow_redirects=True, timeout=20)
            response.raise_for_status()
            candidates = parse_listing(response.text, city["city"], base_url, today)
        except Exception as error:
            print(f"  Ошибка листинга {city['city']}: {error}")
            continue
        for post in candidates:
            if today <= date.fromisoformat(post["date"]) <= latest and post["_prefilled"]["source_url"] not in seen:
                seen.add(post["_prefilled"]["source_url"])
                posts.append(post)
        time.sleep(1)
    return posts
