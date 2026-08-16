"""Проверки целостности данных: events.json / venues.json / cities.json / картинки.

Часть автотестов, которые гоняются перед каждым релизом (CI-джоб `test` в
deploy-yandex.yml). Цель — не пропустить на прод битые ссылки на площадки/
города, дубли id, кривые даты и битые файлы постеров.
"""
from datetime import date

from PIL import Image

from tests.conftest import KNOWN_BROKEN_IMAGE_EVENT_IDS, KNOWN_UNREGISTERED_VENUES

# date/venue/genre намеренно необязательны в модели данных — генератор
# отрисовывает события без даты отдельным блоком (render_event_list),
# а карточка подставляет source_channel вместо пустого venue.
REQUIRED_EVENT_FIELDS = ["id", "artist", "source_city", "source_url", "description"]


class TestEventsJson:
    def test_no_explicitly_non_music_events(self, events, project_root):
        import json
        settings = json.loads((project_root / "settings.json").read_text(encoding="utf-8"))
        hidden = set(settings.get("hidden", []))
        prefixes = ("экскурсия", "лекция", "мастер-класс", "кинопоказ", "выставка")
        leaked = [
            (e.get("id"), e.get("artist")) for e in events
            if e.get("source_url") not in hidden
            and (e.get("artist") or "").strip().lower().startswith(prefixes)
        ]
        assert not leaked, f"В музыкальную афишу попали немузкальные события: {leaked}"

    def test_not_empty(self, events):
        assert isinstance(events, list) and len(events) > 0

    def test_required_fields_present(self, events):
        problems = []
        for e in events:
            for field in REQUIRED_EVENT_FIELDS:
                if not e.get(field):
                    problems.append((e.get("id", "<no id>"), field))
        assert not problems, f"У событий отсутствуют обязательные поля: {problems}"

    def test_ids_are_unique(self, events):
        ids = [e["id"] for e in events if e.get("id")]
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, f"Дублирующиеся id событий: {dupes}"

    def test_no_content_duplicates(self, events):
        """Содержательные дубликаты: одинаковые дата+площадка+время или
        пересекающиеся артисты на одну дату (критерии deduplicate_events из
        parser.py), но разные id. Регресс на случай 8b763d82/a564ed8d —
        одно расписание из разных постов канала попало в базу дважды."""
        from parser import _artist_set, _venue_match

        dated = [e for e in events if e.get("date") and e.get("id")]
        dupes = []
        for i in range(len(dated)):
            for j in range(i + 1, len(dated)):
                a, b = dated[i], dated[j]
                if a["date"] != b["date"]:
                    continue
                ai, aj = _artist_set(a), _artist_set(b)
                vi, vj = a.get("venue") or "", b.get("venue") or ""
                ti, tj = a.get("time") or "", b.get("time") or ""
                same_artist = bool(ai and aj and ai & aj)
                same_venue_time = bool(vi and vj and _venue_match(vi, vj) and ti and tj and ti == tj)
                if same_artist or same_venue_time:
                    dupes.append((a["id"], b["id"], a["date"], a.get("artist"), b.get("artist"),
                                  vi or vj, ti or tj))
        assert not dupes, (
            f"Содержательные дубликаты событий (один концерт — две карточки): {dupes}"
        )

    def test_dates_are_valid_and_recent(self, events):
        current_year = date.today().year
        bad = []
        for e in events:
            ds = e.get("date")
            if not ds:
                continue
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                bad.append((e["id"], ds, "не парсится как YYYY-MM-DD"))
                continue
            if not (current_year - 1 <= d.year <= current_year + 1):
                bad.append((e["id"], ds, f"год вне диапазона {current_year - 1}..{current_year + 1}"))
        assert not bad, f"Подозрительные даты событий: {bad}"

    def test_venue_is_registered(self, events, venues):
        known_names = set()
        for v in venues:
            known_names.add(v["name"])
            known_names.update(v.get("aliases", []))

        unregistered = {
            e["venue"] for e in events if e.get("venue") and e["venue"] not in known_names
        }
        new_unregistered = unregistered - KNOWN_UNREGISTERED_VENUES
        assert not new_unregistered, (
            f"Новые площадки без записи в venues.json: {new_unregistered}. "
            f"Добавьте их в venues.json (или в KNOWN_UNREGISTERED_VENUES, если это не физическая площадка)."
        )

    def test_source_city_is_known(self, events, cities):
        known_names = set()
        for c in cities:
            known_names.add(c["name"])
            known_names.update(c.get("aliases", []))

        unknown = {
            e["source_city"] for e in events
            if e.get("source_city") and e["source_city"] not in known_names
        }
        assert not unknown, f"source_city не найден в cities.json: {unknown}"

    def test_event_images_exist_and_valid(self, events, project_root):
        missing = []
        corrupt = []
        tiny = []
        for e in events:
            image = e.get("image")
            if not image:
                continue
            path = project_root / image.lstrip("/")
            if not path.is_file():
                if e["id"] not in KNOWN_BROKEN_IMAGE_EVENT_IDS:
                    missing.append((e["id"], image))
                continue
            if path.stat().st_size == 0:
                corrupt.append((e["id"], image, "0 байт"))
                continue
            try:
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    w, h = im.size
            except Exception as exc:
                corrupt.append((e["id"], image, str(exc)))
                continue
            if w < 50 or h < 50:
                tiny.append((e["id"], image, w, h))

        assert not missing, f"Новые события с отсутствующим файлом постера: {missing}"
        assert not corrupt, f"Битые файлы постеров: {corrupt}"
        assert not tiny, f"Подозрительно маленькие постеры (похоже на заглушку): {tiny}"


class TestVenuesJson:
    def test_not_empty(self, venues):
        assert isinstance(venues, list) and len(venues) > 0

    def test_slugs_are_unique(self, venues):
        slugs = [v["slug"] for v in venues]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        assert not dupes, f"Дублирующиеся slug площадок: {dupes}"

    def test_required_fields_present(self, venues):
        problems = [v.get("slug", "<no slug>") for v in venues if not v.get("name") or not v.get("city")]
        assert not problems, f"У площадок отсутствуют name/city: {problems}"


class TestCitiesJson:
    def test_not_empty(self, cities):
        assert isinstance(cities, list) and len(cities) > 0

    def test_slugs_are_unique(self, cities):
        slugs = [c["slug"] for c in cities]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        assert not dupes, f"Дублирующиеся slug городов: {dupes}"


class TestArtistsJson:
    def test_not_empty(self, artists):
        assert isinstance(artists, list) and len(artists) > 0

    def test_slugs_are_unique(self, artists):
        slugs = [a["slug"] for a in artists]
        dupes = {s for s in slugs if slugs.count(s) > 1}
        assert not dupes, f"Дублирующиеся slug артистов: {dupes}"

    def test_required_fields_present(self, artists):
        problems = [a.get("slug", "<no slug>") for a in artists if not a.get("name")]
        assert not problems, f"У артистов отсутствует name: {problems}"

    def test_min_event_count(self, artists):
        # Порог публикации страницы — 2+ события (см. BACKLOG.md, раздел 1).
        below = [(a["slug"], a["event_count"]) for a in artists if a.get("event_count", 0) < 2]
        assert not below, f"Артисты ниже порога публикации (event_count < 2) не должны быть в artists.json: {below}"

    def test_no_generic_placeholder_names(self, artists):
        # Регресс на баг с ложной generic-классификацией (см. коммит
        # 6f8eed6): фолбэк-плейсхолдеры («DJ-сет», «Фестиваль» и т.п.)
        # не должны попадать в реестр как «артисты».
        from parser import _GENERIC_ARTIST_LITERALS

        leaked = [a["slug"] for a in artists if a["name"] in _GENERIC_ARTIST_LITERALS]
        assert not leaked, f"Generic-плейсхолдеры просочились в artists.json как артисты: {leaked}"
