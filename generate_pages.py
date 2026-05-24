#!/usr/bin/env python3
"""SEO static site generator for Местов.Нет.

Reads events.json and generates:
  - index.html          (с JSON-LD + статическим пре-рендером)
  - cities/{slug}.html  (страница каждого города)
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

# ── Конфиг ──────────────────────────────────────────────────────────────────

BASE_DIR      = Path(__file__).parent
EVENTS_FILE   = BASE_DIR / "events.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
INDEX_FILE    = BASE_DIR / "index.html"
DOMAIN     = "https://mestov.net"

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

CITY_SLUGS: dict[str, str] = {
    "Симферополь":   "simferopol",
    "Ялта":          "yalta",
    "Севастополь":   "sevastopol",
    "Бахчисарай":    "bakhchisaray",
    "Судак":         "sudak",
    "Евпатория":     "evpatoria",
    "Керчь":         "kerch",
    "Коктебель":     "koktebel",
    "Феодосия":      "feodosiya",
    "Алушта":        "alushta",
    "Саки":          "saki",
    "Крым":          "all",
    "Научный (Бахчисарайский р-н)": "nauchny",
    "Бахчисарайский район": "bakhchisaray",
}

CITY_PREP = {                           # «в Симферополе», «в Ялте», …
    "Симферополь":   "в Симферополе",
    "Ялта":          "в Ялте",
    "Севастополь":   "в Севастополе",
    "Бахчисарай":    "в Бахчисарае",
    "Судак":         "в Судаке",
    "Евпатория":     "в Евпатории",
    "Керчь":         "в Керчи",
    "Коктебель":     "в Коктебеле",
    "Феодосия":      "в Феодосии",
    "Алушта":        "в Алуште",
    "Саки":          "в Саках",
    "Крым":          "в Крыму",
    "Научный (Бахчисарайский р-н)": "в Научном",
    "Бахчисарайский район": "в Бахчисарайском районе",
}

# ── Утилиты ──────────────────────────────────────────────────────────────────

def esc(text) -> str:
    return html_module.escape(str(text)) if text else ""

def today_str() -> str:
    return date.today().isoformat()

def fmt_date(ds: str) -> str:
    try:
        d = datetime.strptime(ds, "%Y-%m-%d")
        return f"{d.day} {MONTHS_GEN[d.month - 1]}, {DAYS_SHORT[d.weekday()]}"
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
        tags += '<span class="tag cancelled-tag">перенесено</span>'
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

    # Статический пре-рендер событий города (для поисковиков)
    static_content = render_event_list(city_events, today, custom_names)
    seo_block = f'<div id="seo-content" style="display:none">\n{static_content}\n</div>\n'

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

    # Статический пре-рендер событий (скрытый блок для SEO)
    static_html = render_event_list(future, today, custom_names)
    seo_block = f'<div id="seo-content" style="display:none">\n{static_html}\n</div>\n'
    if '<div id="seo-content"' in src:
        src = re.sub(
            r'<div id="seo-content"[^>]*>.*?</div>',
            seo_block.strip(),
            src,
            flags=re.DOTALL,
        )
    else:
        src = src.replace('</body>', f'{seo_block}</body>')

    return src

# ── sitemap.xml ───────────────────────────────────────────────────────────────

def make_sitemap(cities: list[str]) -> str:
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

    lines.append("</urlset>")
    return "\n".join(lines)

# ── robots.txt ────────────────────────────────────────────────────────────────

def make_robots() -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n"

# ── Главная функция ───────────────────────────────────────────────────────────

def main() -> None:
    print("📖  Читаем events.json …")
    events: list[dict] = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    print(f"    {len(events)} событий загружено")

    settings = {}
    if SETTINGS_FILE.exists():
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    custom_names: dict = settings.get("names", {})

    today  = today_str()
    css    = extract_css()

    # Города, для которых есть события (исключаем «Крым» — он на главной)
    cities_with_events: list[str] = sorted(
        c for c in {e["source_city"] for e in events if e.get("source_city")}
        if city_slug(c) != "all"
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

    # 3. sitemap.xml
    print("🗺   Генерируем sitemap.xml …")
    sitemap = make_sitemap(cities_with_events)
    (BASE_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    print("    ✓ sitemap.xml")

    # 4. robots.txt
    robots = make_robots()
    (BASE_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print("    ✓ robots.txt")

    print("\n✅  Готово! Все страницы сгенерированы.")
    print(f"    Города: {', '.join(cities_with_events)}")
    print(f"\n💡  Следующий шаг: отправьте sitemap.xml в Яндекс.Вебмастер и Google Search Console:")
    print(f"    {DOMAIN}/sitemap.xml")


if __name__ == "__main__":
    main()
