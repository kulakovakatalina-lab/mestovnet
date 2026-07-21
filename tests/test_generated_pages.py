"""Проверки сгенерированных статических страниц: ссылки, постеры, SEO-теги.

Работает по уже сгенерированным файлам в репозитории (event/, venues/,
cities/, index.html) — не запускает generate_pages.py, просто проверяет
результат его последнего запуска.
"""
import json

import pytest
from bs4 import BeautifulSoup

from generate_pages import (
    CITY_SLUGS,
    DOMAIN,
    build_venue_alias_lookup,
    esc,
    resolve_venue_slugs,
)
from tests.conftest import KNOWN_MISSING_EVENT_PAGES, KNOWN_MISSING_VENUE_PAGES

# Сколько upcoming-событий проверять детально — весь список избыточен для
# каждого прогона, репрезентативной выборки достаточно, чтобы ловить
# системные регрессии генератора (не точечные дефекты одной страницы).
SAMPLE_SIZE = 30


def _soup(path):
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def _internal_targets(soup):
    for tag, attr in (("a", "href"), ("img", "src"), ("link", "href"), ("script", "src")):
        for el in soup.find_all(tag):
            val = el.get(attr)
            if not val:
                continue
            if val.startswith(("http://", "https://", "mailto:", "tel:", "javascript:", "#")):
                continue
            yield val


def _resolve_local(project_root, page_path, url):
    """Резолвит относительную ссылку так же, как это сделал бы браузер —
    от папки страницы, где она встретилась, а не от корня проекта.
    Раньше резолвили от project_root независимо от вложенности страницы,
    из-за чего относительный href="index.html" на вложенных страницах
    (genre/<slug>/, cities/<slug>.html) всегда "находил" корневой
    index.html в тесте, хотя в браузере вёл на несуществующий файл."""
    path = url.split("#")[0].split("?")[0]
    if path.startswith(DOMAIN):
        path = path[len(DOMAIN):]
    if path.startswith("/"):
        return project_root / path.lstrip("/")
    return page_path.parent / path


class TestEventPages:
    def _sample(self, upcoming_events):
        return upcoming_events[:SAMPLE_SIZE]

    def test_pages_exist_for_upcoming_events(self, upcoming_events, project_root):
        missing = [
            e["id"] for e in upcoming_events
            if e["id"] not in KNOWN_MISSING_EVENT_PAGES
            and not (project_root / "event" / e["id"]).is_file()
        ]
        assert not missing, (
            f"Нет сгенерированной страницы event/<id> для: {missing}. "
            f"Похоже, сайт нужно пересобрать: python3 generate_pages.py"
        )

    def test_title_contains_artist(self, upcoming_events, project_root):
        problems = []
        for e in self._sample(upcoming_events):
            page = project_root / "event" / e["id"]
            if not page.is_file():
                continue
            soup = _soup(page)
            title = soup.title.get_text() if soup.title else ""
            expected = esc(e.get("artist") or "")
            if expected and expected.split(",")[0].strip() not in BeautifulSoup(title, "html.parser").get_text():
                # title экранирован через esc() в HTML, но title тэг в DOM уже раскодирован —
                # сверяем по исходному (неэкранированному) артисту.
                if (e.get("artist") or "").split(",")[0].strip() not in title:
                    problems.append((e["id"], title))
        assert not problems, f"<title> не содержит артиста события: {problems}"

    def test_canonical_matches_own_url(self, upcoming_events, project_root):
        problems = []
        for e in self._sample(upcoming_events):
            page = project_root / "event" / e["id"]
            if not page.is_file():
                continue
            soup = _soup(page)
            link = soup.find("link", rel="canonical")
            expected = f"{DOMAIN}/event/{e['id']}"
            if not link or link.get("href") != expected:
                problems.append((e["id"], link.get("href") if link else None, expected))
        assert not problems, f"canonical не совпадает с реальным URL страницы: {problems}"

    def test_poster_matches_event_data(self, upcoming_events, project_root):
        """og:image страницы события обязан быть постером именно этого события."""
        problems = []
        for e in self._sample(upcoming_events):
            if not e.get("image"):
                continue
            page = project_root / "event" / e["id"]
            if not page.is_file():
                continue
            soup = _soup(page)
            og_image = soup.find("meta", property="og:image")
            expected = e["image"] if e["image"].startswith("http") else f"{DOMAIN}{e['image']}"
            if not og_image or og_image.get("content") != expected:
                problems.append((e["id"], og_image.get("content") if og_image else None, expected))
        assert not problems, f"og:image не совпадает с постером события в events.json: {problems}"

    def test_jsonld_is_valid(self, upcoming_events, project_root):
        problems = []
        for e in self._sample(upcoming_events):
            page = project_root / "event" / e["id"]
            if not page.is_file():
                continue
            soup = _soup(page)
            found_event_schema = False
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                except json.JSONDecodeError as exc:
                    problems.append((e["id"], f"невалидный JSON-LD: {exc}"))
                    continue
                graph = data.get("@graph", [data])
                if any(item.get("@type") == "MusicEvent" for item in graph if isinstance(item, dict)):
                    found_event_schema = True
            if not found_event_schema:
                problems.append((e["id"], "нет MusicEvent в JSON-LD"))
        assert not problems, f"Проблемы с JSON-LD на страницах событий: {problems}"


class TestVenueAndCityPages:
    def test_pages_exist_for_venues_with_events(self, venues, events, project_root):
        # Реплицируем логику generate_pages.main(): venue_slug резолвится
        # по точному совпадению строки venue/alias, а не произвольным
        # пересечением множеств имён.
        events_copy = [dict(e) for e in events]
        resolve_venue_slugs(events_copy, build_venue_alias_lookup(venues))
        active_slugs = {e["venue_slug"] for e in events_copy if e.get("venue_slug")}

        missing = [
            v["slug"] for v in venues
            if v["slug"] in active_slugs
            and v["slug"] not in KNOWN_MISSING_VENUE_PAGES
            and not (project_root / "venues" / v["slug"]).is_file()
        ]
        assert not missing, (
            f"Нет сгенерированной страницы venues/<slug> для площадок с событиями: {missing}. "
            f"Похоже, сайт нужно пересобрать: python3 generate_pages.py"
        )

    def test_pages_exist_for_cities_with_events(self, cities, events, project_root):
        active_cities = {e.get("source_city") for e in events if e.get("source_city")}
        missing = []
        for c in cities:
            # "Крым"/all — зонтичный псевдо-город, generate_pages.py его
            # намеренно не генерирует (main(): `CITY_SLUGS[c] != "all"`).
            if c["name"] in active_cities and CITY_SLUGS.get(c["name"]) != "all":
                path = project_root / "cities" / f"{c['slug']}.html"
                if not path.is_file():
                    missing.append(c["slug"])
        assert not missing, f"Нет сгенерированной страницы cities/<slug>.html для городов с событиями: {missing}"


class TestInternalLinks:
    """Обходит index.html + сэмпл сгенерированных страниц, проверяет что все
    относительные ссылки/картинки резолвятся в существующие файлы на диске."""

    def test_index_links_resolve(self, project_root):
        page = project_root / "index.html"
        soup = _soup(page)
        broken = []
        for url in _internal_targets(soup):
            target = _resolve_local(project_root, page, url)
            if not target.exists():
                broken.append(url)
        assert not broken, f"Битые внутренние ссылки/картинки на index.html: {broken}"

    def test_sample_pages_links_resolve(self, project_root, sample_event, sample_venue, sample_city):
        genre_pages = sorted((project_root / "genre").glob("*/index.html"))
        assert genre_pages, "Нет ни одной сгенерированной страницы genre/<slug>/index.html"
        pages = [
            project_root / "event" / sample_event["id"],
            project_root / "venues" / sample_venue["slug"],
            project_root / "cities" / f"{sample_city['slug']}.html",
            *genre_pages,
        ]
        broken = {}
        for page in pages:
            soup = _soup(page)
            page_broken = []
            for url in _internal_targets(soup):
                target = _resolve_local(project_root, page, url)
                if not target.exists():
                    page_broken.append(url)
            if page_broken:
                broken[str(page)] = page_broken
        assert not broken, f"Битые внутренние ссылки/картинки: {broken}"

    def test_logo_links_to_home(self, project_root, sample_event, sample_venue, sample_city):
        """Регресс: на вложенных страницах (genre/<slug>/, cities/<slug>.html)
        относительный href="index.html" у логотипа резолвится в файл САМОЙ
        страницы (он существует!), а не на главную — просто "существует ли
        файл" эту регрессию не ловит, нужно сверять именно с index.html."""
        genre_pages = sorted((project_root / "genre").glob("*/index.html"))
        assert genre_pages, "Нет ни одной сгенерированной страницы genre/<slug>/index.html"
        pages = [
            project_root / "index.html",
            project_root / "event" / sample_event["id"],
            project_root / "venues" / sample_venue["slug"],
            project_root / "cities" / f"{sample_city['slug']}.html",
            *genre_pages,
        ]
        home = (project_root / "index.html").resolve()
        broken = {}
        for page in pages:
            soup = _soup(page)
            page_broken = []
            for cls in ("nav-logo", "footer-logo"):
                el = soup.find("a", class_=cls)
                if el is None:
                    continue
                href = el.get("href")
                target = _resolve_local(project_root, page, href) if href else None
                if target is not None and target.is_dir():
                    target = target / "index.html"
                if target is None or target.resolve() != home:
                    page_broken.append((cls, href))
            if page_broken:
                broken[str(page)] = page_broken
        assert not broken, f"Логотип не ведёт на главную: {broken}"


class TestUniqueMeta:
    """Регресс: Яндекс.Метрика находила страницы с одинаковыми <title>/description
    (события с одинаковым артистом и площадкой, но разными датами)."""

    def _collect(self, project_root, subdir):
        pages = [
            p for p in (project_root / subdir).iterdir()
            if p.is_file()
        ]
        titles, descriptions = {}, {}
        for page in pages:
            soup = _soup(page)
            title = soup.title.get_text() if soup.title else ""
            meta = soup.find("meta", attrs={"name": "description"})
            desc = meta.get("content") if meta else ""
            titles.setdefault(title, []).append(page.name)
            descriptions.setdefault(desc, []).append(page.name)
        return titles, descriptions

    def test_event_titles_are_unique(self, project_root):
        titles, _ = self._collect(project_root, "event")
        dupes = {t: pages for t, pages in titles.items() if len(pages) > 1}
        assert not dupes, f"Повторяющиеся <title> на страницах событий: {dupes}"

    def test_event_descriptions_are_unique(self, project_root):
        _, descriptions = self._collect(project_root, "event")
        dupes = {d: pages for d, pages in descriptions.items() if len(pages) > 1}
        assert not dupes, f"Повторяющиеся meta description на страницах событий: {dupes}"


class TestEscapeRegression:
    """Регресс на фикс XSS в клиентских шаблонах (c8a6a6d)."""

    @pytest.mark.parametrize("payload", [
        '<script>alert(1)</script>',
        '"><img src=x onerror=alert(1)>',
        "'; alert(1); '",
        '<svg onload=alert(1)>',
    ])
    def test_esc_neutralizes_html(self, payload):
        escaped = esc(payload)
        assert "<" not in escaped
        assert ">" not in escaped

    def test_esc_handles_empty(self):
        assert esc("") == ""
        assert esc(None) == ""
