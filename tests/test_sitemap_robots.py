"""Проверки sitemap.xml, robots.txt и стабильности "статических" URL сайта."""
import xml.etree.ElementTree as ET

from generate_pages import CITY_SLUGS, DOMAIN

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# URL, которые не зависят от текущего набора событий и не должны менять
# адрес без явного намерения (защита от «побились ссылки»). Динамические
# event/venue/city URL сюда не входят — они естественно меняются каждый день.
STATIC_URLS = sorted(
    {"/", "/sitemap.xml", "/robots.txt", "/404.html"}
    | {f"/cities/{slug}.html" for slug in CITY_SLUGS.values() if slug != "all"}
)

def _resolve_local(project_root, loc):
    path = loc[len(DOMAIN):] if loc.startswith(DOMAIN) else loc
    return project_root / path.lstrip("/")


class TestSitemap:
    def test_is_valid_xml(self, project_root):
        tree = ET.parse(project_root / "sitemap.xml")
        assert tree.getroot().tag.endswith("urlset")

    def test_no_duplicate_urls(self, project_root):
        tree = ET.parse(project_root / "sitemap.xml")
        locs = [el.text for el in tree.getroot().findall("sm:url/sm:loc", SITEMAP_NS)]
        dupes = {loc for loc in locs if locs.count(loc) > 1}
        assert not dupes, f"Дублирующиеся <loc> в sitemap.xml: {dupes}"

    def test_all_urls_resolve_to_existing_files(self, project_root):
        tree = ET.parse(project_root / "sitemap.xml")
        locs = [el.text for el in tree.getroot().findall("sm:url/sm:loc", SITEMAP_NS)]
        broken = [loc for loc in locs if not _resolve_local(project_root, loc).exists()
                  and not _resolve_local(project_root, loc + "/index.html").exists()]
        assert not broken, f"В sitemap.xml есть URL без соответствующего файла: {broken}"

    def test_domain_is_consistent(self, project_root):
        tree = ET.parse(project_root / "sitemap.xml")
        locs = [el.text for el in tree.getroot().findall("sm:url/sm:loc", SITEMAP_NS)]
        wrong = [loc for loc in locs if not loc.startswith(DOMAIN)]
        assert not wrong, f"URL в sitemap.xml не на домене {DOMAIN}: {wrong}"

    def test_includes_all_non_hidden_events(self, project_root, events, settings):
        """Регресс: sitemap.xml раньше исключал прошедшие события (только
        upcoming), из-за чего ссылки на архивные афиши не были доступны
        поисковикам. Теперь в sitemap должны попадать ВСЕ события из
        events.json с id, кроме намеренно скрытых в settings.json."""
        hidden = set(settings.get("hidden", []))
        expected_ids = {
            e["id"] for e in events
            if e.get("id") and (e.get("source_url") or "") not in hidden
        }
        tree = ET.parse(project_root / "sitemap.xml")
        locs = [el.text for el in tree.getroot().findall("sm:url/sm:loc", SITEMAP_NS)]
        sitemap_ids = {loc.rsplit("/", 1)[-1] for loc in locs if "/event/" in loc}
        missing = expected_ids - sitemap_ids
        assert not missing, (
            f"В sitemap.xml нет страниц событий, которые есть в events.json: "
            f"{sorted(missing)}. Ожидалось {len(expected_ids)} страниц событий."
        )

    def test_includes_past_events(self, project_root, events, settings, today_str):
        """Прошедшие события (date < сегодня или без даты) обязаны оставаться
        в sitemap.xml — они не должны выпадать из него при прогоне."""
        hidden = set(settings.get("hidden", []))
        past_ids = {
            e["id"] for e in events
            if e.get("id")
            and (e.get("source_url") or "") not in hidden
            and (not e.get("date") or e["date"] < today_str)
        }
        assert past_ids, "В events.json нет прошедших событий — тест не может проверить"
        tree = ET.parse(project_root / "sitemap.xml")
        locs = [el.text for el in tree.getroot().findall("sm:url/sm:loc", SITEMAP_NS)]
        sitemap_ids = {loc.rsplit("/", 1)[-1] for loc in locs if "/event/" in loc}
        missing = past_ids - sitemap_ids
        assert not missing, (
            f"Прошедшие события отсутствуют в sitemap.xml: {sorted(missing)}"
        )


class TestRobots:
    def test_disallows_404_page(self, project_root):
        content = (project_root / "robots.txt").read_text(encoding="utf-8")
        assert "Disallow: /404.html" in content, (
            "robots.txt потерял 'Disallow: /404.html' — регресс на фикс cca787c"
        )

    def test_references_correct_sitemap(self, project_root):
        content = (project_root / "robots.txt").read_text(encoding="utf-8")
        assert f"Sitemap: {DOMAIN}/sitemap.xml" in content

    def test_allows_crawling_by_default(self, project_root):
        content = (project_root / "robots.txt").read_text(encoding="utf-8")
        assert "Allow: /" in content


class TestStaticUrlsStability:
    """Снапшот адресов, которые в принципе не должны переименовываться.

    Если тест падает — значит, домен/слаг города/структура сайта поменялись
    без явного намерения. При осознанном переименовании — обновить
    tests/snapshots/static_urls.txt.
    """

    def test_matches_snapshot(self, project_root):
        snapshot_file = project_root / "tests" / "snapshots" / "static_urls.txt"
        expected = snapshot_file.read_text(encoding="utf-8").splitlines()
        assert STATIC_URLS == expected, (
            "Список статических URL расходится со снапшотом "
            f"tests/snapshots/static_urls.txt.\n"
            f"Сейчас: {STATIC_URLS}\nБыло: {expected}"
        )

    def test_always_present_urls_exist_on_disk(self, project_root):
        # Только те URL, что не зависят от текущего набора событий — страница
        # города существует лишь пока в этом городе есть события (это уже
        # проверяет test_generated_pages.py::test_pages_exist_for_cities_with_events).
        always_present = {
            "/": "index.html",
            "/sitemap.xml": "sitemap.xml",
            "/robots.txt": "robots.txt",
            "/404.html": "404.html",
        }
        missing = [url for url, rel in always_present.items() if not (project_root / rel).is_file()]
        assert not missing, f"Базовые статические файлы не найдены на диске: {missing}"
