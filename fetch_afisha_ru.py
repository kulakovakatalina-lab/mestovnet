"""
Парсер Афиши (afisha.ru) для крымских городов.

Логика:
1. Листинг города /{slug}/concerts/ — собираем ссылки на страницы концертов
   (на карточке листинга нет даты/площадки, только имя/жанр/постер).
2. Страница концерта /concert/<slug>/ — в блоке «Расписание сеансов» лежат
   площадки (с адресом и городом) и сеансы (дата/время/цена).
   Один концерт может идти в нескольких городах — оставляем только сеансы
   на крымских площадках, поэтому пересечения между листингами городов
   естественно схлопываются.
"""

import re
import time
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

# Крупные города с собственным разделом /concerts/
LISTING_CITIES = [
    {"slug": "simferopol", "name": "Симферополь"},
    {"slug": "sevastopol", "name": "Севастополь"},
    {"slug": "yalta",      "name": "Ялта"},
    {"slug": "kerch",      "name": "Керчь"},
    {"slug": "feodosiya",  "name": "Феодосия"},
    {"slug": "evpatoriya", "name": "Евпатория"},
]

# Все крымские слаги — для фильтрации площадок на странице концерта.
CRIMEA_SLUGS = {
    "simferopol": "Симферополь",
    "sevastopol": "Севастополь",
    "yalta":      "Ялта",
    "kerch":      "Керчь",
    "feodosiya":  "Феодосия",
    "evpatoriya": "Евпатория",
    "alushta":    "Алушта",
    "saki":       "Саки",
    "dzhankoy":   "Джанкой",
    "bahchisaray": "Бахчисарай",
    "sudak":      "Судак",
    "koktebel":   "Коктебель",
    "gurzuf":     "Гурзуф",
}

MONTH_MAP = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

BASE = "https://www.afisha.ru"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def _parse_session(aria: str):
    """'18 сентября в 20:00, от 2400 ₽' → (date, time, price)."""
    m = re.search(r"(\d+)\s+([а-яё]+)(?:\s+в\s+(\d+:\d+))?", aria)
    if not m:
        return None, None, None
    day, month_ru, t = int(m.group(1)), m.group(2), m.group(3)
    month = MONTH_MAP.get(month_ru)
    if not month:
        return None, None, None
    now = datetime.now()
    year = now.year
    if month < now.month or (month == now.month and day < now.day):
        year += 1
    date = f"{year}-{month:02d}-{day:02d}"

    price = None
    pm = re.search(r"(от\s+[\d\s]+₽|[\d\s]+₽|бесплатно)", aria, re.IGNORECASE)
    if pm:
        price = re.sub(r"\s+", " ", pm.group(1)).strip()
    return date, t, price


def _collect_listing(slug: str) -> list[dict]:
    """Возвращает [{url, name, genre, image}] со страницы /{slug}/concerts/."""
    url = f"{BASE}/{slug}/concerts/"
    resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    cards = []
    for item in soup.select('[data-test="ITEM"]'):
        link = item.select_one('a[data-test*="ITEM-URL"], a[href^="/concert/"]')
        if not link or not link.get("href", "").startswith("/concert/"):
            continue
        name_tag = item.select_one('[data-test="ITEM-NAME"]')
        name = name_tag.get_text(strip=True) if name_tag else item.get("aria-label")
        badge = item.select_one('[data-test="ITEM-BADGE"]')
        genre = badge.get_text(strip=True) if badge else None
        img = item.select_one("img[src]")
        image = None
        if img:
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                image = src
        cards.append({
            "url": BASE + link["href"].split("?")[0],
            "name": name,
            "genre": genre,
            "image": image,
        })
    return cards


def _parse_concert_page(card: dict) -> list[dict]:
    """Парсит /concert/<slug>/ — возвращает посты по крымским сеансам."""
    resp = httpx.get(card["url"], headers=_HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Блок «Расписание сеансов»
    sched = None
    for sec in soup.select('[data-test="SECTION"]'):
        title = sec.select_one('[data-test="SECTION-TITLE"]')
        if title and "Расписание" in title.get_text():
            sched = sec
            break
    if not sched:
        return []

    # Чистое имя артиста берём из og:title («Артист - купить билет ...»),
    # имя с карточки листинга бывает с мусором расписания.
    artist = card["name"]
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        title = og["content"]
        title = re.split(r"\s+[-–—]\s+купить", title)[0]
        title = re.split(r"\s+[–—]\s+Афиша", title)[0]
        title = title.strip()
        if title:
            artist = title

    desc_tag = soup.select_one('[data-test="OBJECT-DESCRIPTION-CONTENT"]')
    description = desc_tag.get_text(" ", strip=True) if desc_tag else None

    genres = []
    for mf in soup.select('[data-test="META-FIELD"]'):
        nm = mf.select_one('[data-test="META-FIELD-NAME"]')
        vl = mf.select_one('[data-test="META-FIELD-VALUE"]')
        if nm and vl and "Жанр" in nm.get_text():
            genres = [g.strip() for g in vl.get_text(",", strip=True).split(",") if g.strip()]
    genre = card.get("genre") or (genres[0] if genres else None)

    posts = []
    for grp in sched.select(".LujD_"):
        venue_link = grp.select_one('a[data-test*="ITEM-URL"]')
        href = venue_link.get("href", "") if venue_link else ""
        city_slug = href.strip("/").split("/")[0] if href else ""
        if city_slug not in CRIMEA_SLUGS:
            continue
        city_name = CRIMEA_SLUGS[city_slug]

        name_tag = grp.select_one('[data-test="ITEM-NAME"]')
        venue = name_tag.get_text(strip=True) if name_tag else None
        addr_tag = grp.select_one('[aria-label="Адрес"]')
        address = addr_tag.get_text(strip=True) if addr_tag else None

        for sess in grp.select('[data-test="SESSION"]'):
            aria = sess.get("aria-label", "")
            date, t, price = _parse_session(aria)
            if not date:
                continue
            desc = description or f"{artist} — концерт в {venue}, {city_name}."
            posts.append({
                "date": date,
                "text": (
                    f"{artist} — концерт. {venue}, {city_name}. "
                    f"{aria}. Ссылка: {card['url']}"
                ),
                "image": card.get("image"),
                "_city": city_name,
                "_prefilled": {
                    "artist": artist,
                    "venue": venue,
                    "date": date,
                    "time": t,
                    "price": price,
                    "event_type": "концерт",
                    "genre": genre,
                    "address": address,
                    "description": desc,
                    "source_url": card["url"],
                },
            })
    return posts


def fetch_all_crimea(days_back: int = 90) -> list[dict]:
    """Возвращает посты со всех крымских городов afisha.ru.

    days_back трактуется как горизонт вперёд в днях (как у Яндекс.Афиши):
    прошедшие сеансы отбрасываются, сеансы дальше горизонта — тоже.
    """
    today = datetime.now().date()
    horizon = today.fromordinal(today.toordinal() + max(days_back, 0)) if days_back else None

    # 1. Собираем уникальные ссылки на концерты со всех листингов.
    cards: dict[str, dict] = {}
    for city in LISTING_CITIES:
        try:
            for card in _collect_listing(city["slug"]):
                cards.setdefault(card["url"], card)
            time.sleep(1.5)
        except Exception as e:
            print(f"  Ошибка листинга {city['slug']}: {e}")

    # 2. Парсим каждую страницу концерта один раз.
    all_posts = []
    seen = set()
    for url, card in cards.items():
        try:
            for post in _parse_concert_page(card):
                d = datetime.strptime(post["date"], "%Y-%m-%d").date()
                if d < today:
                    continue
                if horizon and d > horizon:
                    continue
                key = (post["_prefilled"]["source_url"], post["date"],
                       post["_prefilled"]["venue"], post["_prefilled"]["time"])
                if key in seen:
                    continue
                seen.add(key)
                all_posts.append(post)
            time.sleep(1.0)
        except Exception as e:
            print(f"  Ошибка {url}: {e}")
    return all_posts


if __name__ == "__main__":
    import json
    posts = fetch_all_crimea()
    print(f"Всего сеансов: {len(posts)}")
    for p in posts[:10]:
        pf = p["_prefilled"]
        print(f"  {pf['date']} {pf['time'] or ''} — {pf['artist']} @ {pf['venue']} ({p['_city']}) {pf['price'] or ''}")
