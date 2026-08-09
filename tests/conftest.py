import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Известный на момент написания тестов долг (ratchet) ──────────────────────
# Эти константы — верхняя граница для регресса, а не цель для расширения.
# Каждая проблема отражена в отдельной активной ветке/задаче; тест должен
# упасть, если появится НОВЫЙ такой же дефект, но не должен блокировать
# релиз из-за уже известного и учтённого долга.

# Площадки, упомянутые в events.json, но не зарегистрированные в venues.json —
# все текущие записи это фестивали/организаторы/источники, а не физические
# площадки (см. EXCLUDE_KEYS в build_venues.py), поэтому список не растёт.
# Обновлено 2026-07-22 после ежемесячного прогона build_venues.py
# (ACTUALIZATION.md): список сократился с 14 до 5 — новые заведения
# зарегистрированы, дубли слиты через MERGE_GROUPS.
KNOWN_UNREGISTERED_VENUES = {
    "Comedy Republic",
    "Крым Event",
    "Крымские Дела",
    "Скажите Джаз",
    "Афиша PayBerry",
}

# id событий, у которых поле image указывает на не существующий файл.
# Ветка fix-broken-posters починила все известные на 2026-07-05 случаи —
# множество пусто, но оставлено как задел для будущего known-debt.
KNOWN_BROKEN_IMAGE_EVENT_IDS = set()

# slug площадок, у которых есть события (venue_slug резолвится), но
# generate_pages.py ещё не генерировал для них venues/<slug> — сайт не
# пересобирался после последнего обновления venues.json/events.json.
# Нужно перегенерировать сайт (`python3 generate_pages.py`) перед релизом.
KNOWN_MISSING_VENUE_PAGES = {
    "belbek",
    "koktebel-bereg-chernogo-morya",
    "chayka-na-plyazhe",
    "level-beach-club",
    "monro",
}

# id событий (upcoming, картинка на месте), для которых event/<id> ещё не
# сгенерирован — та же причина: сайт не пересобирался. Пересоздать той же
# командой (`python3 generate_pages.py`).
KNOWN_MISSING_EVENT_PAGES = {
    "fe6c477a",
    "6e9fa104",
    "42da48cf",
}

# slug артистов, у которых есть события (artist_slugs резолвится), но
# artist/<slug> ещё не сгенерирован — задел на будущее, как для venues/event.
KNOWN_MISSING_ARTIST_PAGES = set()


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


def _load_json(name):
    with open(PROJECT_ROOT / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def events():
    return _load_json("events.json")


@pytest.fixture(scope="session")
def venues():
    return _load_json("venues.json")


@pytest.fixture(scope="session")
def artists():
    return _load_json("artists.json")


@pytest.fixture(scope="session")
def cities():
    return _load_json("cities.json")


@pytest.fixture(scope="session")
def channels():
    return _load_json("channels.json")


@pytest.fixture(scope="session")
def settings():
    return _load_json("settings.json")


@pytest.fixture(scope="session")
def today_str():
    return date.today().isoformat()


@pytest.fixture(scope="session")
def upcoming_events(events, today_str, settings):
    hidden = set(settings.get("hidden", []))
    return [
        e for e in events
        if e.get("date") and e["date"] >= today_str
        and (e.get("source_url") or "") not in hidden
    ]


@pytest.fixture(scope="session")
def sample_event(upcoming_events, events):
    pool = upcoming_events or events
    for e in pool:
        if e.get("id") and (PROJECT_ROOT / "event" / e["id"]).is_file():
            return e
    pytest.skip("Нет ни одного события с сгенерированной страницей event/<id>")


@pytest.fixture(scope="session")
def event_without_date(events, settings):
    """Прошедшее/архивное событие без даты, у которого есть сгенерированная
    страница. Нужно для проверки, что JS не подменяет его на ближайшее."""
    hidden = set(settings.get("hidden", []))
    for e in events:
        if (e.get("id") and not e.get("date")
                and (e.get("source_url") or "") not in hidden
                and (PROJECT_ROOT / "event" / e["id"]).is_file()):
            return e
    pytest.skip("Нет события без даты с сгенерированной страницей event/<id>")


@pytest.fixture(scope="session")
def sample_venue(venues, events):
    venue_names_with_events = {
        e.get("venue") for e in events if e.get("venue")
    }
    for v in venues:
        names = {v.get("name"), *v.get("aliases", [])}
        if names & venue_names_with_events and (PROJECT_ROOT / "venues" / v["slug"]).is_file():
            return v
    pytest.skip("Нет ни одной площадки с событиями и сгенерированной страницей")


@pytest.fixture(scope="session")
def sample_artist(artists, events):
    from generate_pages import build_artist_alias_lookup, resolve_artist_slugs

    events_copy = [dict(e) for e in events]
    resolve_artist_slugs(events_copy, build_artist_alias_lookup(artists))
    active_slugs = {s for e in events_copy for s in (e.get("artist_slugs") or [])}
    for a in artists:
        if a["slug"] in active_slugs and (PROJECT_ROOT / "artist" / a["slug"]).is_file():
            return a
    pytest.skip("Нет ни одного артиста с событиями и сгенерированной страницей")


@pytest.fixture(scope="session")
def sample_city(cities, events):
    city_names_with_events = {e.get("source_city") for e in events if e.get("source_city")}
    for c in cities:
        if c["name"] in city_names_with_events and (PROJECT_ROOT / "cities" / f"{c['slug']}.html").is_file():
            return c
    pytest.skip("Нет ни одного города с событиями и сгенерированной страницей")
