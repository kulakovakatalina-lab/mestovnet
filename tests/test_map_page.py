"""Проверки страницы карты (map.html): наличие, навигация, деплой.

Работает по файлам в репозитории — не запускает браузер (для рендеринга
и JS-ошибок карты см. tests/test_layout_playwright.py::TestLayout, где
"map" добавлена в список проверяемых страниц).
"""
from bs4 import BeautifulSoup

NAV_LINK_HTML = '<a href="/map.html" class="nav-map-link">Карта</a>'

# Шаблоны с собственной копией <nav> (см. generate_pages.py: index.html
# переиспользуется через _extract_nav_block(), genre.html/event.html —
# отдельные шаблоны со своей вёрсткой шапки).
TEMPLATES_WITH_NAV_LINK = ["index.html", "genre.html", "event.html", "map.html"]


class TestMapPageExists:
    def test_file_exists(self, project_root):
        assert (project_root / "map.html").is_file()

    def test_has_expected_title_and_hero(self, project_root):
        soup = BeautifulSoup((project_root / "map.html").read_text(encoding="utf-8"), "html.parser")
        assert soup.title and "Карта" in soup.title.text
        assert soup.find(id="map") is not None, "На странице нет контейнера #map"

    def test_fetches_venues_events_and_settings(self, project_root):
        content = (project_root / "map.html").read_text(encoding="utf-8")
        for endpoint in ("/venues.json", "/events.json", "/settings.json"):
            assert endpoint in content, f"map.html не запрашивает {endpoint}"

    def test_loads_yandex_maps_api_with_key(self, project_root):
        content = (project_root / "map.html").read_text(encoding="utf-8")
        assert "api-maps.yandex.ru" in content
        assert "apikey=" in content


class TestMapNavLink:
    def test_present_in_all_root_templates(self, project_root):
        missing = [
            name for name in TEMPLATES_WITH_NAV_LINK
            if 'href="/map.html"' not in (project_root / name).read_text(encoding="utf-8")
        ]
        assert not missing, f"Ссылка на /map.html отсутствует в шаблонах: {missing}"


class TestMapInDeploy:
    def test_map_html_copied_in_workflow(self, project_root):
        workflow = (project_root / ".github" / "workflows" / "deploy-yandex.yml").read_text(encoding="utf-8")
        assert "map.html" in workflow, (
            "map.html не упомянут в deploy-yandex.yml — не попадёт на прод при деплое"
        )


class TestVenueCoordinates:
    """lat/lon добавляются geocode_venues.py (Nominatim) — не все площадки
    геокодируются успешно, но те, что есть, должны быть похожи на Крым."""

    # Крым примерно: широта 44.0–46.3, долгота 32.3–36.7 — с небольшим запасом
    LAT_RANGE = (43.5, 46.5)
    LON_RANGE = (32.0, 37.0)

    def test_coordinates_within_crimea_bounds(self, venues):
        bad = []
        for v in venues:
            lat, lon = v.get("lat"), v.get("lon")
            if lat is None and lon is None:
                continue
            if lat is None or lon is None:
                bad.append((v["slug"], "lat/lon заполнены только частично"))
                continue
            if not (self.LAT_RANGE[0] <= lat <= self.LAT_RANGE[1]
                    and self.LON_RANGE[0] <= lon <= self.LON_RANGE[1]):
                bad.append((v["slug"], lat, lon))
        assert not bad, f"Координаты вне разумных границ Крыма: {bad}"


class TestVenuePagePinMap:
    """Мини-карта с пином на странице заведения (venues/<slug>), под блоком
    «Прошедшие» — рендерится только когда у площадки есть lat/lon, с балуном
    (название, адрес, кнопка «Как проехать?» до текущей точки). Адрес в шапке
    кликабелен и скроллит к #venue-map."""

    def _venue_html(self, project_root, slug):
        path = project_root / "venues" / slug
        assert path.is_file(), f"Нет сгенерированной страницы venues/{slug}"
        return path.read_text(encoding="utf-8")

    def test_venues_with_coords_render_pin_map(self, project_root, venues):
        with_coords = [
            v for v in venues
            if isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lon"), (int, float))
            and (project_root / "venues" / v["slug"]).is_file()
        ]
        assert with_coords, "Нет ни одной сгенерированной страницы заведения с координатами"
        for v in with_coords:
            html = self._venue_html(project_root, v["slug"])
            assert 'id="venue-map"' in html, f"{v['slug']}: нет контейнера #venue-map"
            assert "api-maps.yandex.ru" in html, f"{v['slug']}: не подключён Yandex Maps API"
            assert f'{v["lat"]}, {v["lon"]}]' in html, f"{v['slug']}: пин не на координатах заведения"
            route_marker = f"rtext=~{v['lat']},{v['lon']}"
            assert route_marker in html, f"{v['slug']}: нет ссылки «Как проехать?» до площадки"
            assert "Как проехать?" in html
            # Кликабельный адрес-якорь на карту есть только там, где вообще
            # есть строка адреса (у части площадок с координатами известен
            # только город — venue-address-block для них не рендерится вовсе).
            if v.get("address"):
                assert 'href="#venue-map"' in html, (
                    f"{v['slug']}: адрес в шапке не ссылается на #venue-map"
                )

    def test_map_is_placed_after_past_events_block(self, project_root, venues):
        with_coords = [
            v for v in venues
            if isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lon"), (int, float))
            and (project_root / "venues" / v["slug"]).is_file()
        ]
        assert with_coords
        for v in with_coords:
            html = self._venue_html(project_root, v["slug"])
            assert html.index('id="past-list"') < html.index('id="venue-map"'), (
                f"{v['slug']}: карта должна идти после блока прошедших событий"
            )
            assert html.index('id="venue-map"') < html.index("<footer>"), (
                f"{v['slug']}: карта должна быть перед подвалом страницы"
            )

    def test_venues_without_coords_have_no_map(self, project_root, venues):
        without_coords = [
            v for v in venues
            if not (isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lon"), (int, float)))
            and (project_root / "venues" / v["slug"]).is_file()
        ]
        assert without_coords, "Нет ни одной сгенерированной страницы заведения без координат"
        for v in without_coords:
            html = self._venue_html(project_root, v["slug"])
            assert 'id="venue-map"' not in html, f"{v['slug']}: не должно быть карты без координат"
            assert "api-maps.yandex.ru" not in html, (
                f"{v['slug']}: не должен подключаться Yandex Maps API без координат"
            )
