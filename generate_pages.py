#!/usr/bin/env python3
"""SEO static site generator for Местов.Нет.

Reads events.json and generates:
  - index.html          (с JSON-LD + статическим пре-рендером)
  - cities/{slug}.html  (страница каждого города)
  - genre/{slug}/       (страница каждого жанра, чистый URL /genre/{slug}/)
  - sitemap.xml
  - robots.txt

Запускать после parser.py:
  python generate_pages.py
"""

import html as html_module
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Optional
from pathlib import Path

import parser as parser_mod  # переиспользуем _split_artist_field/_artist_parts

# ── Конфиг ──────────────────────────────────────────────────────────────────

BASE_DIR      = Path(__file__).parent
EVENTS_FILE   = BASE_DIR / "events.json"
VENUES_FILE   = BASE_DIR / "venues.json"
ARTISTS_FILE  = BASE_DIR / "artists.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
INDEX_FILE    = BASE_DIR / "index.html"
EVENT_FILE    = BASE_DIR / "event.html"
GENRE_FILE    = BASE_DIR / "genre.html"
DOMAIN     = "https://mestov.net"

# ── Жанры ────────────────────────────────────────────────────────────────────
# Копия GENRE_MAP/GENRE_LABELS из genre.html — единственное место для правки на JS-стороне,
# здесь дублируется для статической генерации страниц /genre/{slug}/.

GENRE_MAP: dict[str, str] = {
    "джаз": "jazz", "рок": "rock", "русский рок": "rock", "панк-рок": "rock",
    "инди-рок": "rock", "метал": "rock", "инди": "rock", "авторская": "rock",
    "классика": "classic", "хоровая": "classic", "медитативная": "classic",
    "поп": "pop", "поп-рок": "pop", "лаунж": "pop", "хип-хоп": "pop",
    "каверы": "pop", "юмор": "pop", "шоу": "pop", "интерактив": "pop",
    "этно": "folk", "фолк-метал": "folk", "народная": "folk",
    "блюз": "blues",
}
GENRE_LABELS: dict[str, str] = {
    "jazz": "Джаз", "rock": "Рок", "folk": "Фолк",
    "blues": "Блюз", "classic": "Классика", "pop": "Поп",
}
GENRE_ORDER: list[str] = ["jazz", "rock", "folk", "blues", "classic", "pop"]

def map_genre(raw: Optional[str]) -> str:
    return GENRE_MAP.get((raw or "").lower(), "pop")

# ── Локализация ──────────────────────────────────────────────────────────────

MONTHS_GEN = [
    "января","февраля","марта","апреля","мая","июня",
    "июля","августа","сентября","октября","ноября","декабря",
]
MONTHS_NOM = [
    "Январь","Февраль","Март","Апрель","Май","Июнь",
    "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь",
]
DAYS_SHORT = ["вс","пн","вт","ср","чт","пт","сб"]

# ── Города ───────────────────────────────────────────────────────────────────
# Единственный источник правды — cities.json (совпадает со справочником парсера).

CITIES_FILE = BASE_DIR / "cities.json"
with open(CITIES_FILE, encoding="utf-8") as _f:
    _CITIES = json.load(_f)

CITY_SLUGS: dict[str, str] = {c["name"]: c["slug"] for c in _CITIES}
CITY_PREP:  dict[str, str] = {c["name"]: c["prep"] for c in _CITIES}

# ── Утилиты ──────────────────────────────────────────────────────────────────

# Управляющие C0-символы (кроме \t \n \r) — не должны попадать в HTML/JSON-LD.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def esc(text) -> str:
    return html_module.escape(_CTRL_RE.sub("", str(text))) if text else ""

# SEO-пререндер оборачивается маркерами — так замена блока не спотыкается
# о вложенные </div> внутри карточек (прежний regex этим и был сломан).
SEO_START = "<!--seo-content-->"
SEO_END   = "<!--/seo-content-->"
_SEO_RE   = re.compile(re.escape(SEO_START) + r".*?" + re.escape(SEO_END) + r"\n?", re.DOTALL)

def wrap_seo(content: str) -> str:
    return f'{SEO_START}\n<div id="seo-content" style="display:none">\n{content}\n</div>\n{SEO_END}\n'

def strip_seo(src: str) -> str:
    # Убираем как новый (маркеры), так и старый (без маркеров) SEO-блок.
    src = _SEO_RE.sub("", src)
    src = re.sub(r'<div id="seo-content".*</div>\s*(?=</body>)', "", src, flags=re.DOTALL)
    return src

def today_str() -> str:
    return date.today().isoformat()

def fmt_date(ds: str) -> str:
    try:
        d = datetime.strptime(ds, "%Y-%m-%d")
        return f"{d.day} {MONTHS_GEN[d.month - 1]}, {DAYS_SHORT[d.weekday()]}"
    except Exception:
        return ds

def fmt_date_short(ds: str) -> str:
    """Дата без дня недели — для заголовков, где нужно короче."""
    try:
        d = datetime.strptime(ds, "%Y-%m-%d")
        return f"{d.day} {MONTHS_GEN[d.month - 1]}"
    except Exception:
        return ds

def city_slug(city: str) -> str:
    return CITY_SLUGS.get(city, city.lower().replace(" ", "-"))

def price_fmt(price) -> tuple[str, str]:
    """Возвращает (текст, css-класс) для тега цены."""
    if not price or str(price) == "null":
        return "", ""
    if price == "бесплатно":
        return "бесплатно", "free"
    return str(price), "price"

def get_source_label(e: dict) -> str:
    ch = e.get("source_channel", "")
    if ch == "yandex_afisha":
        return "Яндекс.Афиша"
    if ch == "krymskiye_dela":
        return f"@{ch} (Instagram)"
    return f"@{ch}"

def get_source_href(e: dict) -> str:
    if e.get("source_url"):
        return e["source_url"]
    ch = e.get("source_channel", "")
    if ch == "krymskiye_dela":
        return f"https://www.instagram.com/{ch}/"
    return f"https://t.me/{ch}"

# ── CSS и JS (извлекаем из index.html, чтобы не дублировать) ────────────────

def extract_css() -> str:
    try:
        src = INDEX_FILE.read_text(encoding="utf-8")
        m = re.search(r"<style>(.*?)</style>", src, re.DOTALL)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""

def extract_js() -> str:
    """Берём JS из index.html — так он всегда в синхроне с главной страницей."""
    try:
        src = INDEX_FILE.read_text(encoding="utf-8")
        m = re.search(r"<script>\s*(.*?)\s*</script>", src, re.DOTALL)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""

# ── Применение настроек из settings.json ─────────────────────────────────────

def apply_settings(events: list[dict], settings: dict) -> list[dict]:
    """Возвращает новый список событий с применёнными переопределениями из settings.json.

    Применяет: names, times, prices, images, cities, venues, descriptions, genres, cancelled.
    Удаляет скрытые события (hidden).
    Оригинальные объекты не изменяются — создаются копии.
    """
    hidden       = set(settings.get("hidden",       []))
    cancelled_ov = set(settings.get("cancelled",    []))
    names        = settings.get("names",        {})
    times        = settings.get("times",        {})
    prices       = settings.get("prices",       {})
    images_ov    = settings.get("images",       {})
    cities_ov    = settings.get("cities",       {})
    venues_ov    = settings.get("venues",       {})
    descs_ov     = settings.get("descriptions", {})
    genres_ov    = settings.get("genres",       {})

    result = []
    for e in events:
        url = e.get("source_url") or ""

        # Скрытые события исключаем полностью
        if url in hidden:
            continue

        ev = dict(e)  # мелкая копия, нам хватает

        if url in names:
            ev["artist"] = names[url]
        if url in times:
            ev["time"] = times[url]
        if url in prices:
            ev["price"] = prices[url]
        if url in images_ov:
            # None (null в JSON) означает «удалить картинку»
            ev["image"] = None if images_ov[url] is None else images_ov[url]
        if url in cities_ov:
            ev["source_city"] = cities_ov[url]
        if url in venues_ov:
            ev["venue"] = venues_ov[url]
        if url in descs_ov:
            ev["description"] = descs_ov[url]
        if url in genres_ov:
            ev["genre"] = genres_ov[url]
        if url in cancelled_ov:
            ev["cancelled"] = True

        result.append(ev)

    return result


# ── Статический рендер карточки события ──────────────────────────────────────

def render_card(e: dict, custom_names: Optional[dict] = None) -> str:
    artist   = e.get("artist") or ""
    venue    = e.get("venue") or e.get("source_channel") or ""
    city     = e.get("source_city") or ""
    time_    = e.get("time") or ""
    desc     = e.get("description") or ""
    evtype   = e.get("event_type") or ""
    cancelled = e.get("cancelled", False)
    src_href = esc(get_source_href(e))
    src_label = esc(get_source_label(e))
    image    = e.get("image") or ""

    src_url  = e.get("source_url") or ""
    label    = (custom_names or {}).get(src_url) or artist or venue
    venue_html = esc(venue) + (f'<span class="city">· {esc(city)}</span>' if artist else "")

    # Теги
    tags = ""
    if cancelled:
        tags += '<span class="tag cancelled-tag">отменено</span>'
    if evtype:
        tags += f'<span class="tag type">{esc(evtype)}</span>'
    genre = e.get("genre") or ""
    if genre:
        tags += f'<span class="tag genre">{esc(genre)}</span>'
    price_text, price_cls = price_fmt(e.get("price"))
    if price_text:
        tags += f'<span class="tag {price_cls}">{esc(price_text)}</span>'

    time_cls = "card-time" if time_ else "card-time no-time"
    time_disp = esc(time_) if time_ else "—"
    desc_html = f'<div class="card-description">{esc(desc)}</div>' if desc else ""
    img_html  = (f'<img class="card-thumb" src="{esc(image)}" alt="{esc(label)}"'
                 f' loading="lazy" onerror="this.remove()">' if image else "")
    cls_extra = " cancelled" if cancelled else ""

    return (
        f'<div class="card{cls_extra}" onclick="window.open(\'{src_href}\',\'_blank\')">'
        f'<div class="card-inner">'
        f'<div class="{time_cls}">{time_disp}</div>'
        f'<div class="card-body">'
        f'<div class="card-artist">{esc(label)}</div>'
        f'<div class="card-venue">{venue_html}</div>'
        f'{desc_html}'
        f'<div class="card-footer">{tags}</div>'
        f'<div class="card-source"><a class="src-link" href="{src_href}" target="_blank"'
        f' rel="noopener">{src_label}</a></div>'
        f'</div>{img_html}</div></div>'
    )

def render_event_list(events: list, today: str, custom_names: Optional[dict] = None) -> str:
    future   = [e for e in events if e.get("date") and e["date"] >= today]
    no_date  = [e for e in events if not e.get("date")]

    if not future and not no_date:
        return '<div class="empty">Событий не найдено</div>'

    groups: dict[str, list] = defaultdict(list)
    for e in future:
        groups[e["date"]].append(e)
    for e in no_date:
        groups["no-date"].append(e)

    parts = []
    for key in sorted(groups, key=lambda k: ("1" if k == "no-date" else k)):
        grp = sorted(groups[key], key=lambda e: e.get("time") or "99:99")
        if key == "no-date":
            label = "Дата уточняется"
        elif key == today:
            label = f'<span class="today-badge">Сегодня</span>{fmt_date(key)}'
        else:
            label = fmt_date(key)
        cards = "\n".join(render_card(e, custom_names) for e in grp)
        parts.append(f'<div class="date-group"><h2>{label}</h2>\n{cards}\n</div>')

    return "\n".join(parts)

# ── JSON-LD ───────────────────────────────────────────────────────────────────

def make_jsonld_events(events: list, custom_names: Optional[dict] = None) -> str:
    items = []
    for e in events[:30]:
        if not e.get("date"):
            continue
        try:
            datetime.strptime(e["date"], "%Y-%m-%d")
        except ValueError:
            continue

        src_url = e.get("source_url") or ""
        custom_name = (custom_names or {}).get(src_url)
        time_ = e.get("time") or "00:00"
        item: dict = {
            "@type":     "MusicEvent",
            "name":      custom_name or e.get("artist") or e.get("venue") or "Концерт",
            "startDate": f'{e["date"]}T{time_}:00+03:00',
            "location":  {
                "@type": "MusicVenue",
                "name":  e.get("venue") or "Крым",
                "address": {
                    "@type":         "PostalAddress",
                    "addressLocality": e.get("source_city") or "Крым",
                    "addressCountry": "RU",
                },
            },
        }
        if e.get("description"):
            item["description"] = e["description"]
        if e.get("cancelled"):
            item["eventStatus"] = "https://schema.org/EventCancelled"
        display_artist = custom_name or e.get("artist")
        if display_artist:
            item["performer"] = {"@type": "MusicGroup", "name": display_artist}
        if e.get("image"):
            item["image"] = e["image"]

        price_text, _ = price_fmt(e.get("price"))
        if price_text:
            if price_text == "бесплатно":
                item["offers"] = {"@type": "Offer", "price": "0", "priceCurrency": "RUB",
                                  "availability": "https://schema.org/InStock"}
            else:
                item["offers"] = {"@type": "Offer", "name": price_text,
                                  "priceCurrency": "RUB",
                                  "availability": "https://schema.org/InStock"}

        items.append(item)

    if not items:
        return ""

    schema = {"@context": "https://schema.org", "@graph": items}
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n</script>"
    )


def make_jsonld_breadcrumbs(crumbs: list[tuple[str, str]]) -> str:
    """crumbs: [(label, path), ...]  path может быть пустым для текущей страницы"""
    items = []
    for i, (label, path) in enumerate(crumbs, 1):
        item = {"@type": "ListItem", "position": i, "name": label}
        if path:
            item["item"] = f"{DOMAIN}{path}"
        items.append(item)
    schema = {"@context": "https://schema.org", "@type": "BreadcrumbList",
              "itemListElement": items}
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False)
        + "\n</script>"
    )

# ── Шаблон страницы города ───────────────────────────────────────────────────

def make_city_page(
    city: str,
    events_all: list,
    all_cities: list[str],
    css: str,
    custom_names: Optional[dict] = None,
) -> str:
    """Генерирует страницу города на основе нового index.html."""
    today   = today_str()
    slug    = city_slug(city)
    prep    = CITY_PREP.get(city, f"в {city}")
    city_events = [e for e in events_all if e.get("source_city") == city]
    count   = len([e for e in city_events if (e.get("date") or "") >= today])

    title       = f"Живая музыка и концерты {prep} — Местов.Нет"
    description = (f"Афиша концертов и живой музыки {prep}: "
                   f"ближайшие {count} событий в клубах, барах и на площадках. "
                   f"Обновляется ежедневно.")

    jsonld_events = make_jsonld_events([e for e in city_events if (e.get("date") or "") >= today], custom_names)
    jsonld_bc     = make_jsonld_breadcrumbs([("Местов.Нет", "/"), (city, "")])

    # Берём за основу свежий index.html
    src = INDEX_FILE.read_text(encoding="utf-8")

    # Страница живёт на уровень глубже (cities/<slug>.html) — относительный
    # href="index.html" у логотипа вёл бы на несуществующий cities/index.html.
    src = src.replace('<a href="index.html" class="nav-logo">', '<a href="/" class="nav-logo">')
    src = src.replace('<a href="index.html" class="footer-logo">', '<a href="/" class="footer-logo">')

    # Мета-теги
    src = re.sub(r'<title>.*?</title>', f'<title>{esc(title)}</title>', src)
    src = re.sub(r'<meta name="description"[^>]+>', f'<meta name="description" content="{esc(description)}">', src)
    src = re.sub(r'<link rel="canonical"[^>]+>', f'<link rel="canonical" href="{DOMAIN}/cities/{slug}.html">', src)
    src = re.sub(r'<meta property="og:title"[^>]+>', f'<meta property="og:title" content="{esc(title)}">', src)
    src = re.sub(r'<meta property="og:description"[^>]+>', f'<meta property="og:description" content="{esc(description)}">', src)

    # JSON-LD: убираем старый, вставляем городской + breadcrumb
    src = re.sub(r'<script type="application/ld\+json">.*?</script>', '', src, flags=re.DOTALL)
    if jsonld_events or jsonld_bc:
        combined = ''
        if jsonld_events:
            combined += jsonld_events
        if jsonld_bc:
            combined += '\n  ' if combined else ''
            combined += jsonld_bc
        src = src.replace('</head>', f'  {combined}\n</head>')

    # Статический пре-рендер событий города (для поисковиков).
    # Шаблон (index.html) может уже содержать SEO-блок — убираем его, чтобы не дублировать.
    src = strip_seo(src)
    static_content = render_event_list(city_events, today, custom_names)
    seo_block = wrap_seo(static_content)

    # Скрипт: предвыбираем город после загрузки
    city_script = f'''<script>
(function() {{
  var CITY = "{slug}";
  var orig = window.renderAll;
  if (typeof orig === "function") {{
    window.renderAll = function() {{
      orig();
      document.querySelectorAll(".city-pill").forEach(function(b) {{
        b.classList.toggle("active", b.dataset.city === CITY);
      }});
    }};
  }}
}})();
</script>
'''

    src = src.replace('</body>', f'{seo_block}{city_script}</body>')

    return src

# ── Шаблон страницы жанра (genre/{slug}/index.html, чистый URL /genre/{slug}/) ─

def make_genre_page(
    genre: str,
    events_all: list,
    css: str,
    custom_names: Optional[dict] = None,
) -> str:
    """Генерирует статическую SEO-страницу жанра на основе genre.html."""
    today  = today_str()
    label  = GENRE_LABELS[genre]
    genre_events = [e for e in events_all if map_genre(e.get("genre")) == genre]
    count  = len([e for e in genre_events if (e.get("date") or "") >= today])
    count_word = "концерт" if count == 1 else "концерта" if count < 5 else "концертов"

    title       = f"{label} в Крыму — концерты и афиша | Местов.Нет"
    description = (f"Афиша концертов в жанре «{label.lower()}» в Крыму: "
                   f"ближайшие {count} {count_word} в клубах, барах и на площадках. "
                   f"Обновляется ежедневно.")

    jsonld_events = make_jsonld_events([e for e in genre_events if (e.get("date") or "") >= today], custom_names)
    jsonld_bc     = make_jsonld_breadcrumbs([("Местов.Нет", "/"), (label, "")])

    src = GENRE_FILE.read_text(encoding="utf-8")

    # Страница живёт на уровень глубже (genre/<slug>/) — относительный
    # href="index.html" у логотипа вёл бы на несуществующий genre/<slug>/index.html.
    src = src.replace('<a href="index.html" class="nav-logo">', '<a href="/" class="nav-logo">')
    src = src.replace('<a href="index.html" class="footer-logo">', '<a href="/" class="footer-logo">')

    # Мета-теги
    src = re.sub(r'<title>.*?</title>', f'<title>{esc(title)}</title>', src)
    src = re.sub(r'<meta name="description"[^>]+>', f'<meta name="description" content="{esc(description)}">', src)
    src = re.sub(r'<link rel="canonical"[^>]+>', f'<link rel="canonical" href="{DOMAIN}/genre/{genre}/">', src)
    src = re.sub(r'<meta property="og:title"[^>]+>', f'<meta property="og:title" content="{esc(title)}">', src)
    src = re.sub(r'<meta property="og:description"[^>]+>', f'<meta property="og:description" content="{esc(description)}">', src)

    # JSON-LD: убираем старый, вставляем жанровый + breadcrumb
    src = re.sub(r'<script type="application/ld\+json">.*?</script>', '', src, flags=re.DOTALL)
    if jsonld_events or jsonld_bc:
        combined = ''
        if jsonld_events:
            combined += jsonld_events
        if jsonld_bc:
            combined += '\n  ' if combined else ''
            combined += jsonld_bc
        src = src.replace('</head>', f'  {combined}\n</head>')

    # Статический пре-рендер событий жанра (для поисковиков).
    src = strip_seo(src)
    static_content = render_event_list(genre_events, today, custom_names)
    seo_block = wrap_seo(static_content)

    # Скрипт: жанр по умолчанию для этой статической страницы (без ?g=).
    # Должен выполниться ДО основного <script>, который синхронно вызывает load().
    genre_script = f'<script>window.__DEFAULT_GENRE__ = "{genre}";</script>\n'
    src = src.replace('<script>\nconst GENRE_MAP', f'{genre_script}<script>\nconst GENRE_MAP')

    src = src.replace('</body>', f'{seo_block}</body>')

    return src

# ── Шаблон страницы события (event/{id} без расширения) ──────────────────────

def make_event_page(event: dict, all_events: list[dict], today: str,
                     custom_names: Optional[dict] = None) -> str:
    """Генерирует страницу события на основе event.html (чистый URL /event/{id})."""
    eid   = event["id"]
    src_url  = event.get("source_url") or ""
    artist   = (custom_names or {}).get(src_url) or event.get("artist") or "Мероприятие"
    venue    = event.get("venue") or ""
    city     = event.get("source_city") or ""
    city_prep = CITY_PREP.get(city, f"в {city}" if city else "")

    title = f"{artist} — {venue}" if venue else artist
    if city and city not in venue:
        title += f", {city}"
    if event.get("date"):
        title += f", {fmt_date_short(event['date'])}"
    title += " · Местов.Нет"

    desc_parts = [artist]
    if venue:
        desc_parts.append(venue)
    if city_prep:
        desc_parts.append(city_prep)
    if event.get("date"):
        desc_parts.append(fmt_date(event["date"]))
    description = ", ".join(desc_parts) + ". Билеты и подробности на Местов.Нет."

    canonical = f"{DOMAIN}/event/{eid}"
    jsonld    = make_jsonld_events([event], custom_names)
    jsonld_bc = make_jsonld_breadcrumbs([
        ("Местов.Нет", "/"),
        (city, f"/cities/{city_slug(city)}.html") if city else ("Крым", "/"),
        (artist, ""),
    ])

    src = EVENT_FILE.read_text(encoding="utf-8")

    src = re.sub(r'<title>.*?</title>', f'<title>{esc(title)}</title>', src)
    if '<meta name="description"' in src:
        src = re.sub(r'<meta name="description"[^>]+>',
                      f'<meta name="description" content="{esc(description)}">', src)
    else:
        src = src.replace('<meta name="viewport"',
                           f'<meta name="description" content="{esc(description)}">\n<meta name="viewport"')
    src = re.sub(r'<link rel="canonical"[^>]+>', '', src)
    src = re.sub(r'<meta property="og:[^>]+>', '', src)
    og_tags = (
        f'<link rel="canonical" href="{canonical}">\n'
        f'<meta property="og:title" content="{esc(title)}">\n'
        f'<meta property="og:description" content="{esc(description)}">\n'
        f'<meta property="og:type" content="article">\n'
    )
    if event.get("image"):
        img = event["image"]
        img_abs = img if img.startswith("http") else f"{DOMAIN}{img}"
        og_tags += f'<meta property="og:image" content="{esc(img_abs)}">\n'

    src = re.sub(r'<script type="application/ld\+json">.*?</script>', '', src, flags=re.DOTALL)
    combined = jsonld + ('\n' + jsonld_bc if jsonld_bc else '')
    src = src.replace('</head>', f'{og_tags}{combined}\n</head>')

    return src


# ── Обновление index.html ─────────────────────────────────────────────────────

def update_index(events: list, css_exists: bool, custom_names: Optional[dict] = None) -> str:
    """Читает текущий index.html и добавляет JSON-LD + статический пре-рендер."""
    src = INDEX_FILE.read_text(encoding="utf-8")
    today = today_str()
    future = [e for e in events if (e.get("date") or "") >= today]

    # JSON-LD для событий
    jsonld_events = make_jsonld_events(future, custom_names)

    # Улучшенный title и description
    count = len(future)
    new_title = "Местов.Нет — живая музыка в Крыму"
    new_desc  = (f"Афиша концертов и живой музыки в Крыму: {count} ближайших событий "
                 f"в Симферополе, Ялте, Севастополе и других городах. "
                 f"Клубы, бары, площадки — всё в одном месте.")

    # Обновляем <title>
    src = re.sub(
        r"<title>.*?</title>",
        f"<title>{esc(new_title)}</title>",
        src,
    )

    # Добавляем/заменяем <meta name="description"
    if '<meta name="description"' in src:
        src = re.sub(
            r'<meta name="description"[^>]+>',
            f'<meta name="description" content="{esc(new_desc)}">',
            src,
        )
    else:
        src = src.replace(
            '<meta name="viewport"',
            f'<meta name="description" content="{esc(new_desc)}">\n  <meta name="viewport"',
        )

    # Canonical
    canonical_tag = f'<link rel="canonical" href="{DOMAIN}/">'
    if '<link rel="canonical"' not in src:
        src = src.replace("</head>", f"  {canonical_tag}\n</head>")

    # Open Graph
    og_tags = (
        f'<meta property="og:title" content="{esc(new_title)}">\n'
        f'  <meta property="og:description" content="{esc(new_desc)}">\n'
        f'  <meta property="og:type" content="website">\n'
    )
    if '<meta property="og:title"' not in src:
        src = src.replace("</head>", f"  {og_tags}</head>")

    # JSON-LD: вставляем перед </head>
    if '<script type="application/ld+json">' not in src and jsonld_events:
        src = src.replace("</head>", f"  {jsonld_events}\n</head>")

    # Статический пре-рендер событий (скрытый блок для SEO).
    # Снимаем прежний блок по маркерам (устойчиво к вложенным </div>) и вставляем свежий.
    static_html = render_event_list(future, today, custom_names)
    src = strip_seo(src).replace('</body>', f'{wrap_seo(static_html)}</body>')

    return src

# ── Заведения ────────────────────────────────────────────────────────────────

def load_venues() -> list[dict]:
    if VENUES_FILE.exists():
        return json.loads(VENUES_FILE.read_text(encoding="utf-8"))
    return []


def build_venue_alias_lookup(venues: list[dict]) -> dict[str, str]:
    """Возвращает словарь raw_venue_string → venue_slug."""
    lookup: dict[str, str] = {}
    for v in venues:
        for alias in v.get("aliases", []):
            lookup[alias] = v["slug"]
        # имя тоже добавляем на случай ручных правок settings.json
        lookup[v["name"]] = v["slug"]
    return lookup


def resolve_venue_slugs(events: list[dict], lookup: dict[str, str]) -> None:
    """Добавляет поле venue_slug к каждому событию (in-place)."""
    for e in events:
        raw = (e.get("venue") or "").strip()
        e["venue_slug"] = lookup.get(raw)


# ── Артисты ──────────────────────────────────────────────────────────────────

def load_artists() -> list[dict]:
    if ARTISTS_FILE.exists():
        return json.loads(ARTISTS_FILE.read_text(encoding="utf-8"))
    return []


def build_artist_alias_lookup(artists: list[dict]) -> dict[str, str]:
    """Возвращает словарь raw_artist_name → artist_slug."""
    lookup: dict[str, str] = {}
    for a in artists:
        for alias in a.get("aliases", []):
            lookup[alias.strip()] = a["slug"]
        lookup[a["name"].strip()] = a["slug"]
    return lookup


def resolve_artist_slugs(events: list[dict], lookup: dict[str, str]) -> None:
    """Добавляет поле artist_slugs (список — в одном событии бывает несколько
    артистов) к каждому событию (in-place). Использует то же разбиение поля
    artist, что и build_artists.py при сборке реестра (запятые верхнего
    уровня + и/&/+/feat./ft./при участии/с участием), чтобы имена резолвились
    так же, как они группировались."""
    for e in events:
        raw = (e.get("artist") or "").strip()
        slugs: list[str] = []
        if raw:
            for part in parser_mod._split_artist_field(raw):
                for name in parser_mod._artist_parts(part.strip()):
                    slug = lookup.get(name.strip())
                    if slug and slug not in slugs:
                        slugs.append(slug)
        e["artist_slugs"] = slugs


def render_past_event_list(events: list[dict], today: str,
                           custom_names: Optional[dict] = None) -> str:
    past = [e for e in events if e.get("date") and e["date"] < today]
    if not past:
        return ""
    groups: dict[str, list] = defaultdict(list)
    for e in past:
        groups[e["date"]].append(e)
    parts = []
    for key in sorted(groups, reverse=True):  # сначала самые свежие прошедшие
        grp = sorted(groups[key], key=lambda e: e.get("time") or "99:99")
        cards = "\n".join(render_card(e, custom_names) for e in grp)
        parts.append(
            f'<div class="date-group">'
            f'<h2 class="past-date">{fmt_date(key)}</h2>\n{cards}\n</div>'
        )
    return "\n".join(parts)


def make_venue_jsonld(venue: dict, upcoming: list[dict],
                      today: str, custom_names: Optional[dict] = None) -> str:
    items: list[dict] = []

    place: dict = {
        "@type": "MusicVenue",
        "name":  venue["name"],
        "address": {
            "@type":           "PostalAddress",
            "addressLocality": venue.get("city") or "Крым",
            "addressCountry":  "RU",
        },
    }
    if venue.get("address"):
        place["address"]["streetAddress"] = venue["address"]
    items.append(place)

    for e in upcoming[:20]:
        if not e.get("date"):
            continue
        src_url = e.get("source_url") or ""
        custom_name = (custom_names or {}).get(src_url)
        time_ = e.get("time") or "00:00"
        item: dict = {
            "@type":     "MusicEvent",
            "name":      custom_name or e.get("artist") or e.get("venue") or "Концерт",
            "startDate": f'{e["date"]}T{time_}:00+03:00',
            "location":  {"@type": "MusicVenue", "name": venue["name"]},
        }
        if e.get("description"):
            item["description"] = e["description"]
        artist = custom_name or e.get("artist")
        if artist:
            item["performer"] = {"@type": "MusicGroup", "name": artist}
        if e.get("image"):
            item["image"] = e["image"]
        items.append(item)

    schema = {"@context": "https://schema.org", "@graph": items}
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n</script>"
    )


# Блок nav + modal копируем из index.html один раз при генерации страниц.
_NAV_CACHE: str = ""

def _extract_nav_block() -> str:
    global _NAV_CACHE
    if _NAV_CACHE:
        return _NAV_CACHE
    src = INDEX_FILE.read_text(encoding="utf-8")
    # Берём от <nav до закрытия модального блока (после </div> modal)
    m = re.search(r'(<nav class="nav">.*?</div>\s*</div>)', src, re.DOTALL)
    if m:
        _NAV_CACHE = m.group(1).replace('href="index.html"', 'href="/"')
    else:
        _NAV_CACHE = '<nav class="nav"><a href="/" class="nav-logo">местов<em>.нет</em></a></nav>'
    return _NAV_CACHE


def make_venue_page(venue: dict, all_events: list[dict], today: str,
                    css: str, custom_names: Optional[dict] = None) -> str:
    import json as _json
    slug    = venue["slug"]
    name    = venue["name"]
    city    = venue.get("city") or ""
    address = venue.get("address") or ""
    aliases = list(venue.get("aliases", [])) + [name]

    v_events = [e for e in all_events if e.get("venue_slug") == slug]
    upcoming = sorted(
        [e for e in v_events if (e.get("date") or "") >= today],
        key=lambda e: (e.get("date") or "9999", e.get("time") or "99:99"),
    )

    city_prep   = CITY_PREP.get(city, f"в {city}" if city else "")
    title       = f"{name} — афиша {city_prep} · Местов.Нет" if city_prep else f"{name} · Местов.Нет"
    description = (f"Концерты и живая музыка в {name}"
                   + (f", {city_prep}" if city_prep else "")
                   + f". {len(upcoming)} ближайших событий. Расписание и билеты.")
    canonical   = f"{DOMAIN}/venues/{slug}"
    jsonld      = make_venue_jsonld(venue, upcoming, today, custom_names)
    jsonld_bc   = make_jsonld_breadcrumbs([
        ("Местов.Нет", "/"),
        (city, f"/cities/{city_slug(city)}.html") if city else ("Крым", "/"),
        (name, ""),
    ])

    # Адрес + карта — под заголовком слева
    if address:
        maps_q   = f"{address}, {city}, Крым" if city else f"{address}, Крым"
        maps_url = f"https://yandex.ru/maps/?text={maps_q.replace(' ', '+')}"
        address_block = (
            f'<div class="venue-address-block">'
            f'<span class="venue-hero-address">{esc(address)}, {esc(city)}</span>'
            f'<a href="{esc(maps_url)}" target="_blank" rel="noopener" class="venue-map-link">'
            f'Открыть на Яндекс\xa0Картах</a>'
            f'</div>'
        )
    else:
        address_block = ""

    # Мини-карта с пином заведения — только если есть координаты
    # (geocode_venues.py заполняет lat/lon не для всех площадок).
    lat, lon = venue.get("lat"), venue.get("lon")
    has_coords = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    address_line = ", ".join(p for p in [address, city] if p) or "Крым"
    route_url = f"https://yandex.ru/maps/?rtext=~{lat},{lon}" if has_coords else ""

    venue_map_section = (
        f'<div class="venue-map-wrap">'
        f'<div id="venue-map"><div class="venue-map-loading">Загрузка карты…</div></div>'
        f'</div>'
    ) if has_coords else ""

    venue_map_script = (
        f'''<script src="https://api-maps.yandex.ru/2.1/?apikey=3085f395-0b2b-474d-aaeb-da26978e3e5c&lang=ru_RU" type="text/javascript"></script>
<script>
ymaps.ready(function() {{
  function escapeHtml(s) {{
    return String(s).replace(/[&<>"']/g, function(c) {{
      return ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c];
    }});
  }}
  var name = {_json.dumps(name, ensure_ascii=False)};
  var addr = {_json.dumps(address_line, ensure_ascii=False)};
  var routeUrl = {_json.dumps(route_url, ensure_ascii=False)};
  var el = document.getElementById('venue-map');
  if (!el) return;
  el.innerHTML = '';
  var balloonContent = '<div class="balloon-card">'
    + '<div class="balloon-name">' + escapeHtml(name) + '</div>'
    + '<div class="balloon-addr">' + escapeHtml(addr) + '</div>'
    + '<a class="balloon-route" href="' + routeUrl + '" target="_blank" rel="noopener">Маршрут</a>'
    + '</div>';
  var map = new ymaps.Map(el, {{
    center: [{lat}, {lon}],
    zoom: 16,
    controls: ['zoomControl'],
  }});
  var placemark = new ymaps.Placemark([{lat}, {lon}], {{
    hintContent: name,
    balloonContent: balloonContent,
  }}, {{ preset: 'islands#blueDotIcon' }});
  map.geoObjects.add(placemark);
}});
</script>''' if has_coords else ""
    )

    # Кол-во актуальных событий — справа
    event_count  = len(upcoming)
    count_word   = "событие" if event_count == 1 else "события" if event_count < 5 else "событий"
    hero_right   = (
        f'<div class="genre-hero-meta">'
        f'<div class="genre-hero-count">{event_count}</div>'
        f'<div class="genre-hero-count-label">{count_word}</div>'
        f'</div>'
    ) if event_count else ""

    aliases_json = _json.dumps(aliases, ensure_ascii=False)
    eyebrow_city = (f'· <a href="/cities/{city_slug(city)}.html">{esc(city)}</a>' if city else "· Крым")
    nav_block    = _extract_nav_block()

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<!-- Yandex.Metrika counter -->
<script type="text/javascript">
    (function(m,e,t,r,i,k,a){{
        m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};
        m[i].l=1*new Date();
        for (var j = 0; j < document.scripts.length; j++) {{if (document.scripts[j].src === r) {{ return; }}}}
        k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
    }})(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=110385036', 'ym');

    ym(110385036, 'init', {{ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: location.href, accurateTrackBounce:true, trackLinks:true}});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/110385036" style="position:absolute; left:-9999px;" alt="" /></div></noscript>
<!-- /Yandex.Metrika counter -->
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:type" content="website">
  {jsonld}
  {jsonld_bc}
  <style>
{css}
  /* ── Герой заведения (genre-hero CSS из genre.html) ── */
  .genre-hero {{
    max-width: var(--max-w);
    margin: 0 auto;
    padding: clamp(36px, 6vw, 64px) var(--gutter) clamp(28px, 4vw, 44px);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 24px;
    flex-wrap: wrap;
  }}
  .genre-hero-info {{
    min-width: 0;
    max-width: 100%;
  }}
  .genre-hero-eyebrow {{
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .genre-hero-eyebrow a {{ color: var(--muted); text-decoration: none; }}
  .genre-hero-eyebrow a:hover {{ color: var(--accent); }}
  .genre-hero-title {{
    font-family: var(--font-display);
    font-size: clamp(36px, 5.5vw, 68px);
    font-weight: 700;
    letter-spacing: -0.04em;
    line-height: 1.0;
    color: var(--fg);
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .venue-description {{
    font-size: 15px;
    color: var(--muted);
    line-height: 1.6;
    margin-top: 14px;
    max-width: 640px;
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .genre-hero-meta {{
    text-align: right;
    flex-shrink: 0;
  }}
  .genre-hero-count {{
    font-family: var(--font-mono);
    font-size: 48px;
    font-weight: 700;
    color: var(--fg);
    letter-spacing: -0.05em;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }}
  .genre-hero-count-label {{
    font-size: 13px;
    color: var(--muted);
    margin-top: 4px;
  }}
  .venue-address-block {{
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-top: 14px;
    max-width: 100%;
  }}
  .venue-hero-address {{
    font-size: 14px;
    color: var(--muted);
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .venue-map-link {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    font-weight: 500;
    color: var(--accent);
    text-decoration: none;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 6px 14px;
    transition: background 0.12s, border-color 0.12s;
    white-space: nowrap;
  }}
  .venue-map-link:hover {{ background: var(--border); }}
  .venue-map-wrap {{
    max-width: var(--max-w);
    margin: 0 auto;
    padding: clamp(20px, 3vw, 32px) var(--gutter) 0;
  }}
  #venue-map {{
    width: 100%;
    height: min(42vh, 360px);
    min-height: 240px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: var(--surface);
  }}
  .venue-map-loading {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--muted);
    font-size: 14px;
  }}
  .balloon-card {{ min-width: 200px; }}
  .balloon-name {{ font-weight: 700; margin-bottom: 4px; }}
  .balloon-addr {{ font-size: 13px; color: var(--muted); margin-bottom: 10px; }}
  .balloon-route {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    background: var(--accent);
    border-radius: var(--radius-sm);
    transition: filter 0.12s;
  }}
  .balloon-route:hover {{ filter: brightness(1.08); }}
  /* ── event-row CSS (из genre.html) ── */
  .bg-jazz    {{ background: linear-gradient(135deg, oklch(22% 0.04 255), oklch(32% 0.08 255)); }}
  .bg-folk    {{ background: linear-gradient(135deg, oklch(24% 0.04 155), oklch(34% 0.08 145)); }}
  .bg-rock    {{ background: linear-gradient(135deg, oklch(22% 0.04 15),  oklch(32% 0.06 20)); }}
  .bg-blues   {{ background: linear-gradient(135deg, oklch(22% 0.06 270), oklch(30% 0.10 265)); }}
  .bg-classic {{ background: linear-gradient(135deg, oklch(28% 0.06 65),  oklch(36% 0.09 58)); }}
  .bg-pop     {{ background: linear-gradient(135deg, oklch(30% 0.10 325), oklch(40% 0.14 310)); }}
  .events-list {{ max-width: var(--max-w); margin: 0 auto; }}
  .event-row {{
    display: grid;
    grid-template-columns: 80px 80px 1fr auto;
    gap: 24px;
    align-items: start;
    padding: clamp(18px, 3vw, 28px) var(--gutter);
    border-bottom: 1px solid var(--border);
    transition: background 0.12s;
    cursor: pointer;
    text-decoration: none;
    color: inherit;
  }}
  .event-row:hover {{ background: var(--surface); }}
  .event-row.past {{ opacity: 0.5; filter: grayscale(0.4); transition: opacity 0.15s, filter 0.15s, background 0.12s; }}
  .event-row.past:hover {{ opacity: 1; filter: none; }}
  .event-row.cancelled {{ opacity: 0.55; filter: grayscale(0.5); transition: opacity 0.15s, filter 0.15s, background 0.12s; }}
  .event-row.cancelled:hover {{ opacity: 0.85; filter: grayscale(0.2); }}
  .row-date {{ flex-shrink: 0; text-align: center; }}
  .row-date-day {{ font-family: var(--font-mono); font-size: 32px; font-weight: 700; color: var(--fg); letter-spacing: -0.05em; line-height: 1; font-variant-numeric: tabular-nums; }}
  .row-date-month {{ font-family: var(--font-mono); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 3px; }}
  .row-date-dow {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .row-thumb {{ width: 72px; height: 72px; border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
  .row-thumb svg {{ opacity: 0.22; }}
  .row-thumb img {{ width: 100%; height: 100%; object-fit: cover; object-position: center top; border-radius: 8px; }}
  .row-artist {{ font-family: var(--font-display); font-size: clamp(18px, 2.5vw, 24px); font-weight: 700; letter-spacing: -0.025em; line-height: 1.15; color: var(--fg); margin-bottom: 6px; }}
  .row-desc {{ font-size: 14px; color: var(--muted); line-height: 1.55; max-width: 560px; margin-bottom: 10px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .row-venue {{ display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }}
  .row-venue-dot {{ width: 3px; height: 3px; border-radius: 50%; background: var(--border); flex-shrink: 0; }}
  .row-right {{ text-align: right; flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }}
  .row-time {{ font-family: var(--font-mono); font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .row-price {{ font-size: 14px; font-weight: 600; color: var(--fg); }}
  .row-btn {{ display: inline-flex; align-items: center; padding: 8px 16px; background: oklch(58% 0.18 255 / 0.10); color: var(--accent); border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; transition: opacity 0.12s; white-space: nowrap; text-decoration: none; }}
  .row-btn:hover {{ opacity: 0.80; }}
  .pill {{ display: inline-block; padding: 3px 10px; border-radius: 100px; font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }}
  .pill-jazz    {{ background: oklch(58% 0.18 255 / 0.10); color: var(--accent); }}
  .pill-rock    {{ background: oklch(55% 0.15 15  / 0.10); color: oklch(50% 0.15 15); }}
  .pill-folk    {{ background: oklch(50% 0.12 150 / 0.10); color: oklch(46% 0.12 150); }}
  .pill-blues   {{ background: oklch(52% 0.14 270 / 0.10); color: oklch(50% 0.16 270); }}
  .pill-classic {{ background: oklch(52% 0.10 60  / 0.10); color: oklch(46% 0.10 60); }}
  .pill-pop     {{ background: oklch(58% 0.16 320 / 0.10); color: oklch(54% 0.16 320); }}
  .archive-link a {{ display: flex; align-items: center; justify-content: center; gap: 6px; padding: 22px var(--gutter); font-size: 14px; font-weight: 500; color: var(--muted); border-top: 1px solid var(--border); transition: color 0.12s, background 0.12s; }}
  .archive-link a:hover {{ color: var(--fg); background: var(--surface); }}
  .past-heading {{ max-width: var(--max-w); margin: 0 auto; padding: 4px var(--gutter) 14px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }}
  .loading {{ padding: 40px var(--gutter); color: var(--muted); font-size: 14px; max-width: var(--max-w); margin: 0 auto; }}
  @media (max-width: 820px) {{
    .event-row {{ grid-template-columns: 64px 64px 1fr; grid-template-rows: auto auto; }}
    .row-thumb {{ width: 56px; height: 56px; }}
    .row-right {{ grid-column: 2 / -1; flex-direction: row; align-items: center; justify-content: flex-start; gap: 12px; margin-top: 8px; }}
  }}
  @media (max-width: 600px) {{
    .event-row {{ grid-template-columns: 48px 1fr; grid-template-rows: auto auto; gap: 12px; padding: 16px var(--gutter); }}
    .row-thumb {{ display: none; }}
    .row-date-day {{ font-size: 26px; }}
    .row-right {{ grid-column: 2; flex-wrap: wrap; gap: 8px; }}
    .row-artist {{ font-size: 16px; }}
    .genre-hero {{ justify-content: center; text-align: center; }}
    .genre-hero-eyebrow {{ text-align: center; }}
    .venue-address-block {{ align-items: center; }}
    .genre-hero-meta {{ width: 100%; text-align: center; }}
    .genre-hero-count {{ font-size: 36px; }}
  }}
  </style>
</head>
<body>

{nav_block}

<div class="genre-hero">
  <div class="genre-hero-info">
    <div class="genre-hero-eyebrow">
      <a href="/">Местов.Нет</a>
      {eyebrow_city}
    </div>
    <h1 class="genre-hero-title">{esc(name)}</h1>
    {f'<p class="venue-description">{esc(venue.get("description", ""))}</p>' if venue.get("description") else ""}
    {address_block}
  </div>
  {hero_right}
</div>

{venue_map_section}

<div class="events-list" id="events-list">
  <div class="loading">Загрузка…</div>
</div>

<div class="archive-link" id="archive-link"></div>

<div class="past-heading" id="past-heading" hidden>Прошедшие</div>
<div class="events-list" id="past-list"></div>

<footer>
  <a href="/" class="footer-logo">местов<em>.нет</em></a>
  <span class="footer-note">Афиша живой музыки Крыма · 2026</span>
</footer>

{venue_map_script}

<script>
const VENUE_ALIASES = {aliases_json};

const GENRE_MAP = {{
  'джаз':'jazz','рок':'rock','русский рок':'rock','панк-рок':'rock',
  'инди-рок':'rock','метал':'rock','инди':'rock','авторская':'rock',
  'классика':'classic','хоровая':'classic','медитативная':'classic',
  'поп':'pop','поп-рок':'pop','лаунж':'pop','хип-хоп':'pop',
  'каверы':'pop','юмор':'pop','шоу':'pop','интерактив':'pop',
  'этно':'folk','фолк-метал':'folk','народная':'folk','блюз':'blues'
}};
const GENRE_LABELS = {{ jazz:'Джаз', rock:'Рок', folk:'Фолк', blues:'Блюз', classic:'Классика', pop:'Поп' }};
const MONTHS_GEN = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'];
const DOW = ['вс','пн','вт','ср','чт','пт','сб'];

function mapGenre(raw) {{ return GENRE_MAP[raw?.toLowerCase()] || 'pop'; }}
function parseDate(d) {{ const p = d.split('-'); return new Date(+p[0], +p[1]-1, +p[2]); }}
function parseDateTime(e) {{
  const d = parseDate(e.date);
  const m = e.time && e.time.match(/(\d{{1,2}}):(\d{{2}})/);
  if (m) d.setHours(+m[1], +m[2], 0, 0); else d.setHours(23, 59, 59, 0);
  return d;
}}
function formatDate(d) {{
  return {{ day: String(d.getDate()).padStart(2,'0'), month: MONTHS_GEN[d.getMonth()], dow: DOW[d.getDay()] }};
}}
function priceText(p) {{
  if (!p) return 'Вход свободный';
  const low = p.toLowerCase();
  return (low.includes('бесплат') || low === 'вход свободный') ? 'Вход свободный' : p;
}}

function applySettings(data, settings) {{
  const hiddenSet    = new Set(settings.hidden || []);
  const cancelledSet = new Set(settings.cancelled || []);
  const ov = {{ names: settings.names||{{}}, times: settings.times||{{}}, prices: settings.prices||{{}},
    images: settings.images||{{}}, cities: settings.cities||{{}}, venues: settings.venues||{{}},
    descriptions: settings.descriptions||{{}}, genres: settings.genres||{{}} }};
  return data.map((e, i) => {{
    const url = e.source_url || '';
    if (hiddenSet.has(url)) return null;
    const ev = {{ ...e }};
    if (url in ov.names)        ev.artist      = ov.names[url];
    if (url in ov.times)        ev.time        = ov.times[url];
    if (url in ov.prices)       ev.price       = ov.prices[url];
    if (url in ov.images)       ev.image       = ov.images[url] === null ? null : ov.images[url];
    if (url in ov.cities)       ev.source_city = ov.cities[url];
    if (url in ov.venues)       ev.venue       = ov.venues[url];
    if (url in ov.descriptions) ev.description = ov.descriptions[url];
    if (url in ov.genres)       ev.genre       = ov.genres[url];
    if (cancelledSet.has(url))  ev.cancelled   = true;
    return ev;
  }}).filter(Boolean);
}}

const genreIcon = (g) => `<svg width="40" height="40" viewBox="0 0 80 80" fill="none"><path d="M28 56V28l36-8v8L36 36v20a8 8 0 1 1-8 0z" fill="white" opacity=".25"/><circle cx="28" cy="56" r="8" fill="white" opacity=".25"/><circle cx="64" cy="28" r="8" fill="white" opacity=".25"/></svg>`;

function eventRowHtml(ev, extraClass) {{
  const genre = mapGenre(ev.genre);
  const fmt   = ev.dateFmt || formatDate(parseDate(ev.date));
  const price = ev.priceDisplay || priceText(ev.price);
  const thumbHtml = ev.image
    ? `<img src="${{ev.image}}" alt="${{ev.artist || ''}}" loading="lazy">`
    : `<div class="bg-${{genre}}" style="width:100%;height:100%;border-radius:inherit;display:flex;align-items:center;justify-content:center;">${{genreIcon(genre)}}</div>`;
  const rowClass = ['event-row', ev.cancelled ? 'cancelled' : '', extraClass || ''].filter(Boolean).join(' ');
  return `<a href="/event/${{ev.id}}" class="${{rowClass}}" data-genre="${{genre}}">
    <div class="row-date">
      <div class="row-date-day">${{fmt.day}}</div>
      <div class="row-date-month">${{fmt.month}}</div>
      <div class="row-date-dow">${{fmt.dow}}</div>
    </div>
    <div class="row-thumb">${{thumbHtml}}</div>
    <div>
      <div class="row-artist">${{ev.cancelled ? '<span class="cancelled-badge">Отменено</span> ' : ''}}${{ev.artist || '—'}}</div>
      <div class="row-desc">${{ev.description || ''}}</div>
      <div class="row-venue">
        <span>${{ev.venue || '—'}}</span>
        <span class="row-venue-dot"></span>
        <span>${{ev.source_city || '—'}}</span>
      </div>
    </div>
    <div class="row-right">
      ${{ev.time ? `<span class="row-time">${{ev.time}}</span>` : ''}}
      <span class="row-price">${{price}}</span>
      <span class="row-btn">Подробнее</span>
    </div>
  </a>`;
}}

function renderList(events, containerId, extraClass) {{
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = events.length
    ? events.map(ev => eventRowHtml(ev, extraClass)).join('')
    : '<div class="loading">Нет событий</div>';
}}

let pastEvents = [];
let pastExpanded = false;

function renderArchive() {{
  const el = document.getElementById('archive-link');
  if (!pastEvents.length) {{ el.innerHTML = ''; return; }}
  const word = pastEvents.length === 1 ? 'событие' : pastEvents.length < 5 ? 'события' : 'событий';
  el.innerHTML = `<a href="#">
    ${{pastExpanded ? '↑ Скрыть прошедшие' : `↓ Показать прошедшие — ${{pastEvents.length}} ${{word}}`}}
  </a>`;
  el.querySelector('a').onclick = (e) => {{
    e.preventDefault();
    pastExpanded = !pastExpanded;
    document.getElementById('past-heading').hidden = !pastExpanded;
    if (pastExpanded) renderList(pastEvents, 'past-list', 'past');
    else document.getElementById('past-list').innerHTML = '';
    renderArchive();
  }};
}}

async function load() {{
  try {{
    const [res, settingsRes] = await Promise.all([
      fetch('/events.json'),
      fetch('/settings.json').catch(() => null)
    ]);
    const data = await res.json();
    const settings = (settingsRes && settingsRes.ok) ? await settingsRes.json().catch(() => ({{}})) : {{}};
    const patched  = applySettings(data, settings);
    const now      = new Date();
    const aliasSet = new Set(VENUE_ALIASES);

    const all = patched
      .filter(e => e.date && e.venue && aliasSet.has(e.venue))
      .map(e => ({{ ...e, dateFmt: formatDate(parseDate(e.date)), priceDisplay: priceText(e.price) }}))
      .sort((a, b) => (a.date + (a.time||'')).localeCompare(b.date + (b.time||'')));

    const upcoming = all.filter(e => parseDateTime(e) >= now);
    pastEvents     = all.filter(e => parseDateTime(e) <  now).reverse();

    renderList(upcoming, 'events-list');
    renderArchive();

    // Жанры в шапке — все жанры сайта, не только этого заведения
    const genreCounts = {{}};
    patched.forEach(e => {{ const g = mapGenre(e.genre); genreCounts[g] = (genreCounts[g] || 0) + 1; }});
    const activeGenres = ['jazz','rock','folk','blues','classic','pop'].filter(g => genreCounts[g]);
    const navEl = document.getElementById('nav-genres');
    if (navEl) navEl.innerHTML = activeGenres.map(g =>
      `<a href="/genre/${{g}}/" class="nav-genre">${{GENRE_LABELS[g]}}</a>`
    ).join('');
  }} catch(err) {{
    document.getElementById('events-list').innerHTML = '<div class="loading">Не удалось загрузить события</div>';
  }}
}}
load();
</script>
</body>
</html>'''


def make_artist_jsonld(artist: dict, upcoming: list[dict], today: str,
                       custom_names: Optional[dict] = None) -> str:
    items: list[dict] = []

    performer: dict = {"@type": "MusicGroup", "name": artist["name"]}
    items.append(performer)

    for e in upcoming[:20]:
        if not e.get("date"):
            continue
        src_url = e.get("source_url") or ""
        custom_name = (custom_names or {}).get(src_url)
        time_ = e.get("time") or "00:00"
        item: dict = {
            "@type":     "MusicEvent",
            "name":      custom_name or artist["name"],
            "startDate": f'{e["date"]}T{time_}:00+03:00',
            "performer": {"@type": "MusicGroup", "name": artist["name"]},
            "location":  {
                "@type": "MusicVenue",
                "name":  e.get("venue") or "Крым",
                "address": {
                    "@type":            "PostalAddress",
                    "addressLocality":  e.get("source_city") or "Крым",
                    "addressCountry":   "RU",
                },
            },
        }
        if e.get("description"):
            item["description"] = e["description"]
        if e.get("image"):
            item["image"] = e["image"]
        items.append(item)

    schema = {"@context": "https://schema.org", "@graph": items}
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n</script>"
    )


def make_artist_page(artist: dict, all_events: list[dict], today: str,
                     css: str, custom_names: Optional[dict] = None) -> str:
    import json as _json
    slug    = artist["slug"]
    name    = artist["name"]
    aliases = list(artist.get("aliases", [])) + [name]

    a_events = [e for e in all_events if slug in (e.get("artist_slugs") or [])]
    upcoming = sorted(
        [e for e in a_events if (e.get("date") or "") >= today],
        key=lambda e: (e.get("date") or "9999", e.get("time") or "99:99"),
    )

    cities = artist.get("cities") or []
    city_note = f", {', '.join(cities[:3])}" if cities else ""
    title       = f"{name} — концерты в Крыму{city_note} · Местов.Нет"
    description = (f"Расписание концертов {name} в Крыму"
                   + (f" ({', '.join(cities[:3])})" if cities else "")
                   + f". {len(upcoming)} ближайших событий.")
    canonical   = f"{DOMAIN}/artist/{slug}"
    jsonld      = make_artist_jsonld(artist, upcoming, today, custom_names)
    jsonld_bc   = make_jsonld_breadcrumbs([
        ("Местов.Нет", "/"),
        (name, ""),
    ])

    # Города, где играет — под заголовком слева
    if cities:
        cities_block = (
            f'<div class="venue-address-block">'
            f'<span class="venue-hero-address">Играет: {esc(", ".join(cities))}</span>'
            f'</div>'
        )
    else:
        cities_block = ""

    event_count  = len(upcoming)
    count_word   = "событие" if event_count == 1 else "события" if event_count < 5 else "событий"
    hero_right   = (
        f'<div class="genre-hero-meta">'
        f'<div class="genre-hero-count">{event_count}</div>'
        f'<div class="genre-hero-count-label">{count_word}</div>'
        f'</div>'
    ) if event_count else ""

    aliases_json = _json.dumps(aliases, ensure_ascii=False)
    nav_block    = _extract_nav_block()

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<!-- Yandex.Metrika counter -->
<script type="text/javascript">
    (function(m,e,t,r,i,k,a){{
        m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};
        m[i].l=1*new Date();
        for (var j = 0; j < document.scripts.length; j++) {{if (document.scripts[j].src === r) {{ return; }}}}
        k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
    }})(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=110385036', 'ym');

    ym(110385036, 'init', {{ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: location.href, accurateTrackBounce:true, trackLinks:true}});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/110385036" style="position:absolute; left:-9999px;" alt="" /></div></noscript>
<!-- /Yandex.Metrika counter -->
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:type" content="website">
  {jsonld}
  {jsonld_bc}
  <style>
{css}
  /* ── Герой артиста (переиспользуем genre-hero/venue CSS) ── */
  .genre-hero {{
    max-width: var(--max-w);
    margin: 0 auto;
    padding: clamp(36px, 6vw, 64px) var(--gutter) clamp(28px, 4vw, 44px);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 24px;
    flex-wrap: wrap;
  }}
  .genre-hero-info {{
    min-width: 0;
    max-width: 100%;
  }}
  .genre-hero-eyebrow {{
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .genre-hero-eyebrow a {{ color: var(--muted); text-decoration: none; }}
  .genre-hero-eyebrow a:hover {{ color: var(--accent); }}
  .genre-hero-title {{
    font-family: var(--font-display);
    font-size: clamp(36px, 5.5vw, 68px);
    font-weight: 700;
    letter-spacing: -0.04em;
    line-height: 1.0;
    color: var(--fg);
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .venue-description {{
    font-size: 15px;
    color: var(--muted);
    line-height: 1.6;
    margin-top: 14px;
    max-width: 640px;
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  .genre-hero-meta {{
    text-align: right;
    flex-shrink: 0;
  }}
  .genre-hero-count {{
    font-family: var(--font-mono);
    font-size: 48px;
    font-weight: 700;
    color: var(--fg);
    letter-spacing: -0.05em;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }}
  .genre-hero-count-label {{
    font-size: 13px;
    color: var(--muted);
    margin-top: 4px;
  }}
  .venue-address-block {{
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-top: 14px;
    max-width: 100%;
  }}
  .venue-hero-address {{
    font-size: 14px;
    color: var(--muted);
    overflow-wrap: break-word;
    word-break: break-word;
  }}
  /* ── event-row CSS (из genre.html) ── */
  .bg-jazz    {{ background: linear-gradient(135deg, oklch(22% 0.04 255), oklch(32% 0.08 255)); }}
  .bg-folk    {{ background: linear-gradient(135deg, oklch(24% 0.04 155), oklch(34% 0.08 145)); }}
  .bg-rock    {{ background: linear-gradient(135deg, oklch(22% 0.04 15),  oklch(32% 0.06 20)); }}
  .bg-blues   {{ background: linear-gradient(135deg, oklch(22% 0.06 270), oklch(30% 0.10 265)); }}
  .bg-classic {{ background: linear-gradient(135deg, oklch(28% 0.06 65),  oklch(36% 0.09 58)); }}
  .bg-pop     {{ background: linear-gradient(135deg, oklch(30% 0.10 325), oklch(40% 0.14 310)); }}
  .events-list {{ max-width: var(--max-w); margin: 0 auto; }}
  .event-row {{
    display: grid;
    grid-template-columns: 80px 80px 1fr auto;
    gap: 24px;
    align-items: start;
    padding: clamp(18px, 3vw, 28px) var(--gutter);
    border-bottom: 1px solid var(--border);
    transition: background 0.12s;
    cursor: pointer;
    text-decoration: none;
    color: inherit;
  }}
  .event-row:hover {{ background: var(--surface); }}
  .event-row.past {{ opacity: 0.5; filter: grayscale(0.4); transition: opacity 0.15s, filter 0.15s, background 0.12s; }}
  .event-row.past:hover {{ opacity: 1; filter: none; }}
  .row-date {{ flex-shrink: 0; text-align: center; }}
  .row-date-day {{ font-family: var(--font-mono); font-size: 32px; font-weight: 700; color: var(--fg); letter-spacing: -0.05em; line-height: 1; font-variant-numeric: tabular-nums; }}
  .row-date-month {{ font-family: var(--font-mono); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 3px; }}
  .row-date-dow {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .row-thumb {{ width: 72px; height: 72px; border-radius: 8px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
  .row-thumb svg {{ opacity: 0.22; }}
  .row-thumb img {{ width: 100%; height: 100%; object-fit: cover; object-position: center top; border-radius: 8px; }}
  .row-artist {{ font-family: var(--font-display); font-size: clamp(18px, 2.5vw, 24px); font-weight: 700; letter-spacing: -0.025em; line-height: 1.15; color: var(--fg); margin-bottom: 6px; }}
  .row-desc {{ font-size: 14px; color: var(--muted); line-height: 1.55; max-width: 560px; margin-bottom: 10px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .row-venue {{ display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }}
  .row-venue-dot {{ width: 3px; height: 3px; border-radius: 50%; background: var(--border); flex-shrink: 0; }}
  .row-right {{ text-align: right; flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }}
  .row-time {{ font-family: var(--font-mono); font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .row-price {{ font-size: 14px; font-weight: 600; color: var(--fg); }}
  .row-btn {{ display: inline-flex; align-items: center; padding: 8px 16px; background: oklch(58% 0.18 255 / 0.10); color: var(--accent); border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; transition: opacity 0.12s; white-space: nowrap; text-decoration: none; }}
  .row-btn:hover {{ opacity: 0.80; }}
  .pill {{ display: inline-block; padding: 3px 10px; border-radius: 100px; font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }}
  .pill-jazz    {{ background: oklch(58% 0.18 255 / 0.10); color: var(--accent); }}
  .pill-rock    {{ background: oklch(55% 0.15 15  / 0.10); color: oklch(50% 0.15 15); }}
  .pill-folk    {{ background: oklch(50% 0.12 150 / 0.10); color: oklch(46% 0.12 150); }}
  .pill-blues   {{ background: oklch(52% 0.14 270 / 0.10); color: oklch(50% 0.16 270); }}
  .pill-classic {{ background: oklch(52% 0.10 60  / 0.10); color: oklch(46% 0.10 60); }}
  .pill-pop     {{ background: oklch(58% 0.16 320 / 0.10); color: oklch(54% 0.16 320); }}
  .archive-link a {{ display: flex; align-items: center; justify-content: center; gap: 6px; padding: 22px var(--gutter); font-size: 14px; font-weight: 500; color: var(--muted); border-top: 1px solid var(--border); transition: color 0.12s, background 0.12s; }}
  .archive-link a:hover {{ color: var(--fg); background: var(--surface); }}
  .past-heading {{ max-width: var(--max-w); margin: 0 auto; padding: 4px var(--gutter) 14px; font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }}
  .loading {{ padding: 40px var(--gutter); color: var(--muted); font-size: 14px; max-width: var(--max-w); margin: 0 auto; }}
  @media (max-width: 820px) {{
    .event-row {{ grid-template-columns: 64px 64px 1fr; grid-template-rows: auto auto; }}
    .row-thumb {{ width: 56px; height: 56px; }}
    .row-right {{ grid-column: 2 / -1; flex-direction: row; align-items: center; justify-content: flex-start; gap: 12px; margin-top: 8px; }}
  }}
  @media (max-width: 600px) {{
    .event-row {{ grid-template-columns: 48px 1fr; grid-template-rows: auto auto; gap: 12px; padding: 16px var(--gutter); }}
    .row-thumb {{ display: none; }}
    .row-date-day {{ font-size: 26px; }}
    .row-right {{ grid-column: 2; flex-wrap: wrap; gap: 8px; }}
    .row-artist {{ font-size: 16px; }}
    .genre-hero {{ justify-content: center; text-align: center; }}
    .genre-hero-eyebrow {{ text-align: center; }}
    .venue-address-block {{ align-items: center; }}
    .genre-hero-meta {{ width: 100%; text-align: center; }}
    .genre-hero-count {{ font-size: 36px; }}
  }}
  </style>
</head>
<body>

{nav_block}

<div class="genre-hero">
  <div class="genre-hero-info">
    <div class="genre-hero-eyebrow">
      <a href="/">Местов.Нет</a>
      · Артист
    </div>
    <h1 class="genre-hero-title">{esc(name)}</h1>
    {f'<p class="venue-description">{esc(artist.get("description", ""))}</p>' if artist.get("description") else ""}
    {cities_block}
  </div>
  {hero_right}
</div>

<div class="events-list" id="events-list">
  <div class="loading">Загрузка…</div>
</div>

<div class="archive-link" id="archive-link"></div>

<div class="past-heading" id="past-heading" hidden>Прошедшие</div>
<div class="events-list" id="past-list"></div>

<footer>
  <a href="/" class="footer-logo">местов<em>.нет</em></a>
  <span class="footer-note">Афиша живой музыки Крыма · 2026</span>
</footer>

<script>
const ARTIST_ALIASES = {aliases_json};
const ARTIST_ALIAS_SET = new Set(ARTIST_ALIASES);

const GENRE_MAP = {{
  'джаз':'jazz','рок':'rock','русский рок':'rock','панк-рок':'rock',
  'инди-рок':'rock','метал':'rock','инди':'rock','авторская':'rock',
  'классика':'classic','хоровая':'classic','медитативная':'classic',
  'поп':'pop','поп-рок':'pop','лаунж':'pop','хип-хоп':'pop',
  'каверы':'pop','юмор':'pop','шоу':'pop','интерактив':'pop',
  'этно':'folk','фолк-метал':'folk','народная':'folk','блюз':'blues'
}};
const GENRE_LABELS = {{ jazz:'Джаз', rock:'Рок', folk:'Фолк', blues:'Блюз', classic:'Классика', pop:'Поп' }};
const MONTHS_GEN = ['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'];
const DOW = ['вс','пн','вт','ср','чт','пт','сб'];

function mapGenre(raw) {{ return GENRE_MAP[raw?.toLowerCase()] || 'pop'; }}
function parseDate(d) {{ const p = d.split('-'); return new Date(+p[0], +p[1]-1, +p[2]); }}
function parseDateTime(e) {{
  const d = parseDate(e.date);
  const m = e.time && e.time.match(/(\d{{1,2}}):(\d{{2}})/);
  if (m) d.setHours(+m[1], +m[2], 0, 0); else d.setHours(23, 59, 59, 0);
  return d;
}}
function formatDate(d) {{
  return {{ day: String(d.getDate()).padStart(2,'0'), month: MONTHS_GEN[d.getMonth()], dow: DOW[d.getDay()] }};
}}
function priceText(p) {{
  if (!p) return 'Вход свободный';
  const low = p.toLowerCase();
  return (low.includes('бесплат') || low === 'вход свободный') ? 'Вход свободный' : p;
}}

// Разбивает поле artist так же, как build_artists.py: запятые верхнего
// уровня (не внутри скобок/«»), затем и/&/+/feat./ft./при участии/с участием.
function splitArtistField(artist) {{
  const parts = [];
  let depth = 0, current = '';
  for (const ch of artist) {{
    if (ch === '(' || ch === '«') {{ depth++; current += ch; }}
    else if (ch === ')' || ch === '»') {{ depth = Math.max(0, depth - 1); current += ch; }}
    else if (ch === ',' && depth === 0) {{ parts.push(current); current = ''; }}
    else {{ current += ch; }}
  }}
  parts.push(current);
  return parts;
}}
const ARTIST_JOIN_RE = /\s+(и|&|\+|feat\.?|ft\.?|при участии|с участием)\s+/i;
const ARTIST_JOIN_WORDS = new Set(['и','&','+','feat','feat.','ft','ft.','при участии','с участием']);
function artistParts(name) {{
  return name.split(ARTIST_JOIN_RE)
    .map(s => s.trim())
    .filter(s => s && !ARTIST_JOIN_WORDS.has(s.toLowerCase()));
}}
function eventMatchesArtist(ev) {{
  const raw = ev.artist || '';
  if (!raw) return false;
  for (const part of splitArtistField(raw)) {{
    for (const name of artistParts(part.trim())) {{
      if (ARTIST_ALIAS_SET.has(name.trim())) return true;
    }}
  }}
  return false;
}}
function otherArtistNames(ev) {{
  const raw = ev.artist || '';
  if (!raw) return [];
  const names = [];
  for (const part of splitArtistField(raw)) {{
    for (const name of artistParts(part.trim())) {{
      const n = name.trim();
      if (n && !ARTIST_ALIAS_SET.has(n) && !names.includes(n)) names.push(n);
    }}
  }}
  return names;
}}

function applySettings(data, settings) {{
  const hiddenSet = new Set(settings.hidden || []);
  const ov = {{ names: settings.names||{{}}, times: settings.times||{{}}, prices: settings.prices||{{}},
    images: settings.images||{{}}, cities: settings.cities||{{}}, venues: settings.venues||{{}},
    descriptions: settings.descriptions||{{}}, genres: settings.genres||{{}} }};
  return data.map((e, i) => {{
    const url = e.source_url || '';
    if (hiddenSet.has(url)) return null;
    const ev = {{ ...e }};
    if (url in ov.names)        ev.artist      = ov.names[url];
    if (url in ov.times)        ev.time        = ov.times[url];
    if (url in ov.prices)       ev.price       = ov.prices[url];
    if (url in ov.images)       ev.image       = ov.images[url] === null ? null : ov.images[url];
    if (url in ov.cities)       ev.source_city = ov.cities[url];
    if (url in ov.venues)       ev.venue       = ov.venues[url];
    if (url in ov.descriptions) ev.description = ov.descriptions[url];
    if (url in ov.genres)       ev.genre       = ov.genres[url];
    return ev;
  }}).filter(Boolean);
}}

const genreIcon = (g) => `<svg width="40" height="40" viewBox="0 0 80 80" fill="none"><path d="M28 56V28l36-8v8L36 36v20a8 8 0 1 1-8 0z" fill="white" opacity=".25"/><circle cx="28" cy="56" r="8" fill="white" opacity=".25"/><circle cx="64" cy="28" r="8" fill="white" opacity=".25"/></svg>`;

function eventRowHtml(ev, extraClass) {{
  const genre = mapGenre(ev.genre);
  const fmt   = ev.dateFmt || formatDate(parseDate(ev.date));
  const price = ev.priceDisplay || priceText(ev.price);
  const others = otherArtistNames(ev);
  const thumbHtml = ev.image
    ? `<img src="${{ev.image}}" alt="${{ev.venue || ''}}" loading="lazy">`
    : `<div class="bg-${{genre}}" style="width:100%;height:100%;border-radius:inherit;display:flex;align-items:center;justify-content:center;">${{genreIcon(genre)}}</div>`;
  return `<a href="/event/${{ev.id}}" class="event-row${{extraClass ? ' ' + extraClass : ''}}" data-genre="${{genre}}">
    <div class="row-date">
      <div class="row-date-day">${{fmt.day}}</div>
      <div class="row-date-month">${{fmt.month}}</div>
      <div class="row-date-dow">${{fmt.dow}}</div>
    </div>
    <div class="row-thumb">${{thumbHtml}}</div>
    <div>
      <div class="row-artist">${{ev.venue || '—'}}</div>
      <div class="row-desc">${{ev.description || ''}}</div>
      <div class="row-venue">
        ${{others.length ? `<span>${{others.join(', ')}}</span><span class="row-venue-dot"></span>` : ''}}
        <span>${{ev.source_city || '—'}}</span>
      </div>
    </div>
    <div class="row-right">
      ${{ev.time ? `<span class="row-time">${{ev.time}}</span>` : ''}}
      <span class="row-price">${{price}}</span>
      <span class="row-btn">Подробнее</span>
    </div>
  </a>`;
}}

function renderList(events, containerId, extraClass) {{
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = events.length
    ? events.map(ev => eventRowHtml(ev, extraClass)).join('')
    : '<div class="loading">Нет событий</div>';
}}

let pastEvents = [];
let pastExpanded = false;

function renderArchive() {{
  const el = document.getElementById('archive-link');
  if (!pastEvents.length) {{ el.innerHTML = ''; return; }}
  const word = pastEvents.length === 1 ? 'событие' : pastEvents.length < 5 ? 'события' : 'событий';
  el.innerHTML = `<a href="#">
    ${{pastExpanded ? '↑ Скрыть прошедшие' : `↓ Показать прошедшие — ${{pastEvents.length}} ${{word}}`}}
  </a>`;
  el.querySelector('a').onclick = (e) => {{
    e.preventDefault();
    pastExpanded = !pastExpanded;
    document.getElementById('past-heading').hidden = !pastExpanded;
    if (pastExpanded) renderList(pastEvents, 'past-list', 'past');
    else document.getElementById('past-list').innerHTML = '';
    renderArchive();
  }};
}}

async function load() {{
  try {{
    const [res, settingsRes] = await Promise.all([
      fetch('/events.json'),
      fetch('/settings.json').catch(() => null)
    ]);
    const data = await res.json();
    const settings = (settingsRes && settingsRes.ok) ? await settingsRes.json().catch(() => ({{}})) : {{}};
    const patched  = applySettings(data, settings);
    const now      = new Date();

    const all = patched
      .filter(e => e.date && eventMatchesArtist(e))
      .map(e => ({{ ...e, dateFmt: formatDate(parseDate(e.date)), priceDisplay: priceText(e.price) }}))
      .sort((a, b) => (a.date + (a.time||'')).localeCompare(b.date + (b.time||'')));

    const upcoming = all.filter(e => parseDateTime(e) >= now);
    pastEvents     = all.filter(e => parseDateTime(e) <  now).reverse();

    renderList(upcoming, 'events-list');
    renderArchive();

    const genreCounts = {{}};
    patched.forEach(e => {{ const g = mapGenre(e.genre); genreCounts[g] = (genreCounts[g] || 0) + 1; }});
    const activeGenres = ['jazz','rock','folk','blues','classic','pop'].filter(g => genreCounts[g]);
    const navEl = document.getElementById('nav-genres');
    if (navEl) navEl.innerHTML = activeGenres.map(g =>
      `<a href="/genre/${{g}}/" class="nav-genre">${{GENRE_LABELS[g]}}</a>`
    ).join('');
  }} catch(err) {{
    document.getElementById('events-list').innerHTML = '<div class="loading">Не удалось загрузить события</div>';
  }}
}}
load();
</script>
</body>
</html>'''


# ── sitemap.xml ───────────────────────────────────────────────────────────────

def make_sitemap(cities: list[str], venue_slugs: Optional[list] = None,
                  event_ids: Optional[list] = None, genre_slugs: Optional[list] = None,
                  artist_slugs: Optional[list] = None) -> str:
    today = today_str()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    def url(loc, freq, priority):
        return (f"  <url><loc>{loc}</loc>"
                f"<changefreq>{freq}</changefreq>"
                f"<priority>{priority}</priority>"
                f"<lastmod>{today}</lastmod></url>")

    lines.append(url(f"{DOMAIN}/", "daily", "1.0"))
    for c in sorted(cities):
        s = city_slug(c)
        lines.append(url(f"{DOMAIN}/cities/{s}.html", "daily", "0.8"))
    for s in (genre_slugs or []):
        lines.append(url(f"{DOMAIN}/genre/{s}/", "daily", "0.7"))
    for s in sorted(venue_slugs or []):
        lines.append(url(f"{DOMAIN}/venues/{s}", "weekly", "0.7"))
    for s in sorted(artist_slugs or []):
        lines.append(url(f"{DOMAIN}/artist/{s}", "weekly", "0.7"))
    for eid in sorted(event_ids or []):
        lines.append(url(f"{DOMAIN}/event/{eid}", "weekly", "0.6"))

    lines.append("</urlset>")
    return "\n".join(lines)

# ── robots.txt ────────────────────────────────────────────────────────────────

def make_robots() -> str:
    return (f"User-agent: *\nAllow: /\nDisallow: /404.html\n"
            f"Sitemap: {DOMAIN}/sitemap.xml\n")

# ── Главная функция ───────────────────────────────────────────────────────────

def main() -> None:
    print("📖  Читаем events.json …")
    events: list[dict] = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    print(f"    {len(events)} событий загружено")

    settings = {}
    if SETTINGS_FILE.exists():
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

    # Применяем все переопределения из settings.json одним проходом
    events = apply_settings(events, settings)
    hidden_count = len(settings.get("hidden", []))
    print(f"    После применения настроек: {len(events)} событий "
          f"({hidden_count} скрыто, переопределений: "
          f"names={len(settings.get('names',{}))}, "
          f"times={len(settings.get('times',{}))}, "
          f"prices={len(settings.get('prices',{}))}, "
          f"images={len(settings.get('images',{}))}, "
          f"cities={len(settings.get('cities',{}))}, "
          f"venues={len(settings.get('venues',{}))}, "
          f"descriptions={len(settings.get('descriptions',{}))}, "
          f"genres={len(settings.get('genres',{}))})")

    # custom_names больше не нужен отдельно — names уже применены в events
    custom_names: dict = {}

    # Загружаем реестр заведений и привязываем venue_slug к каждому событию
    venues = load_venues()
    venue_lookup = build_venue_alias_lookup(venues)
    resolve_venue_slugs(events, venue_lookup)

    # Загружаем реестр артистов и привязываем artist_slugs к каждому событию
    artists = load_artists()
    artist_lookup = build_artist_alias_lookup(artists)
    resolve_artist_slugs(events, artist_lookup)

    today  = today_str()
    css    = extract_css()

    # Города, для которых есть события. Берём только из справочника cities.json
    # (исключаем «Крым» — он на главной). Незнакомые значения игнорируем.
    raw_cities = {e["source_city"] for e in events if e.get("source_city")}
    unknown = sorted(c for c in raw_cities if c not in CITY_SLUGS)
    if unknown:
        print(f"⚠️  Города вне справочника cities.json (пропущены): {', '.join(unknown)}")
    cities_with_events: list[str] = sorted(
        c for c in raw_cities
        if c in CITY_SLUGS and CITY_SLUGS[c] != "all"
    )

    # 1. Обновляем index.html
    print("📝  Обновляем index.html …")
    new_index = update_index(events, bool(css), custom_names)
    INDEX_FILE.write_text(new_index, encoding="utf-8")
    print("    ✓ index.html обновлён")

    # 2. Генерируем страницы городов
    cities_dir = BASE_DIR / "cities"
    cities_dir.mkdir(exist_ok=True)
    seen_slugs: set[str] = set()
    print(f"🏙   Генерируем страницы городов ({len(cities_with_events)}) …")
    for city in cities_with_events:
        slug = city_slug(city)
        if slug in seen_slugs:
            print(f"    — cities/{slug}.html  (дубль: {city}, пропущен)")
            continue
        seen_slugs.add(slug)
        page = make_city_page(city, events, cities_with_events, css, custom_names)
        out  = cities_dir / f"{slug}.html"
        out.write_text(page, encoding="utf-8")
        city_events  = [e for e in events if e.get("source_city") == city]
        future_count = len([e for e in city_events if (e.get("date") or "") >= today])
        print(f"    ✓ cities/{slug}.html  ({future_count} событий)")

    # 2b. Генерируем страницы жанров (genre/{slug}/index.html — чистый URL /genre/{slug}/)
    genre_dir = BASE_DIR / "genre"
    genre_dir.mkdir(exist_ok=True)
    genres_with_events = [g for g in GENRE_ORDER if any(map_genre(e.get("genre")) == g for e in events)]
    print(f"🎼   Генерируем страницы жанров ({len(genres_with_events)}) …")
    for genre in genres_with_events:
        page = make_genre_page(genre, events, css, custom_names)
        slug_dir = genre_dir / genre
        slug_dir.mkdir(exist_ok=True)
        out = slug_dir / "index.html"
        out.write_text(page, encoding="utf-8")
        g_count = len([e for e in events
                       if map_genre(e.get("genre")) == genre and (e.get("date") or "") >= today])
        print(f"    ✓ genre/{genre}/  ({g_count} событий)")

    # 3. Генерируем страницы заведений (venues/{slug} без расширения)
    venues_dir = BASE_DIR / "venues"
    venues_dir.mkdir(exist_ok=True)
    venues_with_events = [
        v for v in venues
        if any(e.get("venue_slug") == v["slug"] for e in events)
    ]
    print(f"🏟   Генерируем страницы заведений ({len(venues_with_events)}) …")
    generated_venue_slugs: list[str] = []
    for venue in venues_with_events:
        page = make_venue_page(venue, events, today, css, custom_names)
        out  = venues_dir / venue["slug"]  # без расширения .html
        out.write_text(page, encoding="utf-8")
        v_upcoming = len([e for e in events
                          if e.get("venue_slug") == venue["slug"]
                          and (e.get("date") or "") >= today])
        v_past     = len([e for e in events
                          if e.get("venue_slug") == venue["slug"]
                          and (e.get("date") or "9999") < today])
        generated_venue_slugs.append(venue["slug"])
        print(f"    ✓ venues/{venue['slug']}  "
              f"({v_upcoming} предстоящих, {v_past} прошедших)")

    # 3b. Генерируем страницы артистов (artist/{slug} без расширения)
    artist_dir = BASE_DIR / "artist"
    artist_dir.mkdir(exist_ok=True)
    artists_with_events = [
        a for a in artists
        if any(a["slug"] in (e.get("artist_slugs") or []) for e in events)
    ]
    print(f"🎤   Генерируем страницы артистов ({len(artists_with_events)}) …")
    generated_artist_slugs: list[str] = []
    for artist in artists_with_events:
        page = make_artist_page(artist, events, today, css, custom_names)
        out  = artist_dir / artist["slug"]  # без расширения .html
        out.write_text(page, encoding="utf-8")
        a_upcoming = len([e for e in events
                          if artist["slug"] in (e.get("artist_slugs") or [])
                          and (e.get("date") or "") >= today])
        a_past     = len([e for e in events
                          if artist["slug"] in (e.get("artist_slugs") or [])
                          and (e.get("date") or "9999") < today])
        generated_artist_slugs.append(artist["slug"])
        print(f"    ✓ artist/{artist['slug']}  "
              f"({a_upcoming} предстоящих, {a_past} прошедших)")
    # Убираем файлы для артистов, которых больше нет в artists.json
    current_artist_slugs = set(generated_artist_slugs)
    artist_removed = 0
    for f in artist_dir.iterdir():
        if f.is_file() and f.name not in current_artist_slugs:
            f.unlink()
            artist_removed += 1
    if artist_removed:
        print(f"    (удалено устаревших страниц артистов: {artist_removed})")

    # 4. Генерируем страницы событий (event/{id} без расширения)
    events_dir = BASE_DIR / "event"
    events_dir.mkdir(exist_ok=True)
    print(f"🎫  Генерируем страницы событий ({len(events)}) …")
    generated_event_ids: list[str] = []
    for e in events:
        eid = e.get("id")
        if not eid:
            continue
        page = make_event_page(e, events, today, custom_names)
        out  = events_dir / eid  # без расширения
        out.write_text(page, encoding="utf-8")
        generated_event_ids.append(eid)
    # Убираем файлы для событий, которых больше нет в events.json
    current_ids = set(generated_event_ids)
    removed = 0
    for f in events_dir.iterdir():
        if f.is_file() and f.name not in current_ids:
            f.unlink()
            removed += 1
    print(f"    ✓ event/  ({len(generated_event_ids)} страниц"
          + (f", удалено устаревших: {removed}" if removed else "") + ")")

    upcoming_event_ids = [e["id"] for e in events
                           if e.get("id") and (e.get("date") or "") >= today]

    # 5. sitemap.xml
    print("🗺   Генерируем sitemap.xml …")
    sitemap = make_sitemap(cities_with_events, generated_venue_slugs, upcoming_event_ids,
                           genres_with_events, generated_artist_slugs)
    (BASE_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    print("    ✓ sitemap.xml")

    # 6. robots.txt
    robots = make_robots()
    (BASE_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print("    ✓ robots.txt")

    print("\n✅  Готово! Все страницы сгенерированы.")
    print(f"    Города: {', '.join(cities_with_events)}")
    print(f"    Жанры: {', '.join(genres_with_events)}")
    print(f"    Заведений: {len(generated_venue_slugs)}")
    print(f"    Артистов: {len(generated_artist_slugs)}")
    print(f"    Событий: {len(generated_event_ids)}")
    print(f"\n💡  Следующий шаг: отправьте sitemap.xml в Яндекс.Вебмастер и Google Search Console:")
    print(f"    {DOMAIN}/sitemap.xml")


if __name__ == "__main__":
    main()
