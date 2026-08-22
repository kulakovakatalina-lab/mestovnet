"""Тесты утилитарных функций parser.py: normalize, venue_match, artist_parts, detect_genre, detect_city."""

import pytest
import parser as parser_module

from parser import (
    _normalize,
    _normalize_venue,
    _venue_match,
    _artist_parts,
    _artist_set,
    _field_count,
    _is_refusal_event,
    _print_dry_run_report,
    _print_source_report,
    resolve_city,
    _sanitize_event_dates,
    _sanitize_event_times,
    _valid_date_or_none,
    _valid_time_or_none,
    _event_validation_reason,
    _assign_event_images,
    _drop_unpublished_image_links,
    validate_events,
    detect_genre,
    _detect_city,
)


def _valid_event(**overrides):
    event = {
        "date": "2026-08-20",
        "artist": "Группа A",
        "source_city": "Ялта",
        "source_url": "https://example.com/event",
    }
    event.update(overrides)
    return event


def test_final_validation_accepts_complete_music_event():
    events, rejected = validate_events([_valid_event()])
    assert len(events) == 1
    assert not rejected


@pytest.mark.parametrize(("change", "reason"), [
    ({"date": None}, "missing_date"),
    ({"date": "20.08.2026"}, "invalid_date"),
    ({"artist": None}, "missing_artist"),
    ({"artist": "Фестиваль"}, "generic_artist"),
    ({"artist": "A" * 181}, "artist_too_long"),
    ({"artist": "Стендап-концерт"}, "non_music"),
    ({"source_city": "Неизвестный город"}, "unknown_city"),
    ({"source_url": None}, "missing_source"),
])
def test_final_validation_rejects_bad_event(change, reason):
    assert _event_validation_reason(_valid_event(**change)) == reason


def test_source_report_shows_posts_passed_and_rejection_reason(capsys):
    good = _valid_event(source_channel="test", source_url="https://example.com/good")
    bad = _valid_event(source_channel="test", source_url="https://example.com/bad", date=None)
    stats = {
        "test": {
            "title": "Тестовый канал",
            "posts": 3,
            "extracted": 2,
            "urls": {good["source_url"], bad["source_url"]},
        }
    }
    _print_source_report(stats, [good, bad], [good])
    output = capsys.readouterr().out
    assert "постов 3, извлечено 2, прошло 1, склеено дублей 0" in output
    assert "нет даты: 1" in output


def test_standup_is_rejected_as_non_music():
    assert _is_refusal_event({"artist": "StandUp Валентин Сидоров"})
    assert _is_refusal_event({"artist": "Стендап-концерт"})


def test_muzloto_is_rejected_as_non_music():
    assert _is_refusal_event({"artist": "МУЗЛОТО"})
    assert _is_refusal_event({"description": "В пятницу играем в музлото"})


def test_film_screening_is_rejected_as_non_music():
    assert _is_refusal_event({"description": "Показ фильма в рамках акции «Ночь кино»"})


def test_dry_run_report_shows_diff(capsys):
    existing = [{"id": "old", "date": "2026-08-20", "artist": "Группа A"}]
    candidate = [{"id": "new", "date": "2026-08-21", "artist": "Группа B"}]
    _print_dry_run_report(existing, candidate)
    output = capsys.readouterr().out
    assert "events.json не изменён" in output
    assert "Добавить: 1" in output
    assert "Убрать/склеить: 1" in output


@pytest.mark.parametrize("value", ["2026-08-XX", "2026-null-null", "2026-02-30", "17.08.2026", "2026-8-17", None])
def test_invalid_event_date_is_rejected(value):
    assert _valid_date_or_none(value) is None


def test_valid_event_date_is_canonical():
    assert _valid_date_or_none("2026-08-17") == "2026-08-17"
    assert _valid_date_or_none("2028-02-29") == "2028-02-29"


def test_sanitize_event_dates_keeps_event_and_clears_only_date():
    events = [{"date": "2026-08-XX", "artist": "Группа A"}]
    assert _sanitize_event_dates(events) == 1
    assert events == [{"date": None, "artist": "Группа A"}]


@pytest.mark.parametrize("raw,expected", [
    ("8:05", "08:05"),
    ("18:00", "18:00"),
    ("18:00-2:00", "18:00–02:00"),
    ("18:00–02:00", "18:00–02:00"),
    ("17:30 (сбор гостей), 18:30 (начало)", "18:30"),
])
def test_event_time_is_normalized(raw, expected):
    assert _valid_time_or_none(raw) == expected


@pytest.mark.parametrize("raw", ["24:00", "12:60", "вечером", "17:30 (сбор гостей)", None])
def test_invalid_event_time_is_rejected(raw):
    assert _valid_time_or_none(raw) is None


def test_sanitize_event_times_reports_normalized_and_cleaned():
    events = [{"time": "8:05"}, {"time": "25:00"}, {"time": "18:00"}]
    assert _sanitize_event_times(events) == (1, 1)
    assert events == [{"time": "08:05"}, {"time": None}, {"time": "18:00"}]


class TestNormalize:
    def test_empty(self):
        assert _normalize("") == ""
        assert _normalize(None) == ""

    def test_lowercases(self):
        assert _normalize("РОК") == "рок"

    def test_removes_quotes(self):
        assert _normalize("«Группа»") == "группа"
        assert _normalize('"Test"') == "test"

    def test_removes_punctuation(self):
        assert _normalize("hello, world!") == "hello world"

    def test_collapses_whitespace(self):
        assert _normalize("  hello   world  ") == "hello world"

    def test_full_pipeline(self):
        assert _normalize('  «БИ-2» — Лучший РОК!  ') == "би2 лучший рок"


class TestNormalizeVenue:
    def test_empty(self):
        assert _normalize_venue("") == ""
        assert _normalize_venue(None) == ""

    def test_removes_type_words(self):
        assert "отель" not in _normalize_venue("Отель Ялта")
        assert "resort" not in _normalize_venue("Mriya Resort")
        assert "spa" not in _normalize_venue("Levante Spa")
        assert "palace" not in _normalize_venue("Yalta Palace")

    def test_keeps_name(self):
        result = _normalize_venue("Jam Club")
        assert "jam" in result
        assert "club" not in result

    def test_removes_dk(self):
        assert "дк" not in _normalize_venue("ДК Профсоюзов")

    def test_removes_teatr(self):
        assert "театральный" not in _normalize_venue("Театральный зал")


class TestVenueMatch:
    def test_same_venue(self):
        assert _venue_match("Jam Club", "Jam Club") is True

    def test_similar_with_type(self):
        assert _venue_match("Отель Ялта", "Ялта Resort") is True

    def test_different_venues(self):
        assert _venue_match("Jam Club", "Gudini") is False

    def test_empty_venues(self):
        assert _venue_match("", "") is False
        assert _venue_match("Venue", "") is False

    def test_partial_overlap(self):
        assert _venue_match("Клуб Рок", "Рок Сити") is True


class TestArtistParts:
    def test_single_artist(self):
        assert _artist_parts("Radio Tapok") == ["Radio Tapok"]

    def test_split_by_and(self):
        parts = _artist_parts("Би-2 и Сплин")
        assert "Би-2" in parts
        assert "Сплин" in parts

    def test_split_by_ampersand(self):
        parts = _artist_parts("DJ Smash & Nastya")
        assert "DJ Smash" in parts
        assert "Nastya" in parts

    def test_split_by_plus(self):
        parts = _artist_parts("А + Б")
        assert "А" in parts
        assert "Б" in parts

    def test_comma_not_split(self):
        parts = _artist_parts("Иванов, Петров")
        assert len(parts) == 1

    def test_multiple_separators(self):
        parts = _artist_parts("А & Б + В")
        assert len(parts) == 3


class TestArtistSet:
    def test_single_artist(self):
        event = {"artist": "Radio Tapok"}
        result = _artist_set(event)
        assert "radio tapok" in result

    def test_multiple_artists(self):
        event = {"artist": "Би-2, Сплин"}
        result = _artist_set(event)
        assert "би2" in result
        assert "сплин" in result

    def test_strips_group_prefix(self):
        event = {"artist": "группа Би-2"}
        result = _artist_set(event)
        assert "би2" in result

    def test_empty_artist(self):
        event = {"artist": None}
        assert _artist_set(event) == set()


class TestFieldCount:
    def test_all_fields(self):
        event = {
            "date": "2026-01-01", "time": "20:00", "artist": "X",
            "event_type": "концерт", "venue": "V", "price": "500",
            "description": "desc", "source_city": "Ялта",
        }
        assert _field_count(event) == 8

    def test_some_fields(self):
        event = {"date": "2026-01-01", "artist": "X"}
        assert _field_count(event) == 2

    def test_empty_fields(self):
        event = {"date": "", "artist": None, "description": ""}
        assert _field_count(event) == 0


class TestDetectGenre:
    @pytest.mark.parametrize("text,expected", [
        ("джазовый вечер с саксофоном", "джаз"),
        ("blues night", "блюз"),
        ("рок-концерт группы", "рок"),
        ("фолк-метал фестиваль", "фолк-метал"),
        ("панк вечеринка", "панк-рок"),
        ("metallica tribute", "метал"),
        ("хип-хоп батл", "хип-хоп"),
        ("рэп концерт", "хип-хоп"),
        ("симфонический оркестр", "классика"),
        ("камерный хор", "классика"),
        ("этническая музыка уутай", "этно"),
        ("народная песня", "фолк"),
        ("авторская песня", "авторская"),
        ("музыкальное лото", "интерактив"),
        ("indie band", "инди"),
        ("lounge музыка", "лаунж"),
        ("легенды 90-х", "поп"),
        ("поп-рок хиты", "поп-рок"),
        ("русский рок", "русский рок"),
        ("рок-хиты", "русский рок"),
        ("кавер на Queen", "каверы"),
        ("tribute Queen", "рок"),
        ("стендап шоу", "юмор"),
        ("комедия клуб", "юмор"),
        ("скрипка и рояль", "классика"),
        ("виолончель соло", "классика"),
        ("балет лебединое озеро", "другое"),
        ("кельтская музыка", "фолк"),
        ("диско вечеринка", "поп"),
        ("drum and bass", "поп"),
        ("trance фестиваль", "поп"),
        ("house музыка", "поп"),
    ])
    def test_genre_detection(self, text, expected):
        event = {"description": text, "artist": "", "event_type": ""}
        assert detect_genre(event) == expected

    def test_channel_genre_override(self):
        event = {
            "source_channel": "skazhitejazz",
            "description": "обычный вечер",
            "artist": "",
            "event_type": "",
        }
        assert detect_genre(event) == "джаз"

    def test_event_type_fallback(self):
        event = {"description": "", "artist": "", "event_type": "трибьют"}
        assert detect_genre(event) == "рок"

        event = {"description": "", "artist": "", "event_type": "вечеринка"}
        assert detect_genre(event) == "поп"

        event = {"description": "", "artist": "", "event_type": "фестиваль"}
        assert detect_genre(event) == "рок"

        event = {"description": "", "artist": "", "event_type": "концерт"}
        assert detect_genre(event) == "поп"

    def test_no_genre(self):
        event = {"description": "просто встреча", "artist": "", "event_type": ""}
        assert detect_genre(event) is None


class TestDetectCity:
    @pytest.mark.parametrize("text,expected", [
        ("концерт в Ялте", "Ялта"),
        ("Массандра приглашает", "Ялта"),
        ("Симферополь рок", "Симферополь"),
        ("Севастополь блюз", "Севастополь"),
        ("Керчь фестиваль", "Керчь"),
        ("Феодосия джаз", "Феодосия"),
        ("Судак море", "Судак"),
        ("Евпатория концерт", "Евпатория"),
        ("Алушта музыка", "Алушта"),
        ("Коктебель джаз", "Коктебель"),
        ("Бахчисарай этно", "Бахчисарай"),
        ("Саки фестиваль", "Саки"),
        ("Гурзуф вечер", "Гурзуф"),
        ("Ливадия концерт", "Ялта"),
        ("Мрия resort", "Ялта"),
        ("Дюльбер мероприятие", "Ялта"),
        ("Мисхор музыка", "Ялта"),
        ("пространство лабиринта в Краснолесье", "Симферополь"),
    ])
    def test_city_detection(self, text, expected):
        assert _detect_city(text) == expected

    def test_no_city(self):
        assert _detect_city("просто текст без города") is None

    def test_case_insensitive(self):
        assert _detect_city("ЯЛТА") == "Ялта"
        assert _detect_city("севастополь") == "Севастополь"


def test_dry_run_does_not_persist_images(tmp_path):
    previous = parser_module.PERSIST_IMAGES
    parser_module.PERSIST_IMAGES = False
    try:
        url = "https://example.test/poster.jpg"
        assert parser_module.download_image(url) == url
        assert list(tmp_path.iterdir()) == []
    finally:
        parser_module.PERSIST_IMAGES = previous


def test_missing_poster_does_not_leave_external_url(monkeypatch):
    monkeypatch.setattr(parser_module.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert parser_module.download_image("https://example.test/poster.jpg") is None


def test_unpublished_poster_links_are_removed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    events = [{"image": "https://example.test/poster.jpg", "images": ["https://example.test/poster.jpg"]}]
    assert _drop_unpublished_image_links(events) == 2
    assert events == [{"image": None, "images": None}]


def test_explicit_event_location_overrides_channel_city():
    event = {
        "city": None,
        "venue": "Лабиринт",
        "description": "Концерт в Краснолесье",
    }
    channel = {"city": "Севастополь"}
    assert resolve_city(event, channel) == "Симферополь"


def test_multiple_events_from_image_album_do_not_guess_posters():
    events = [{}, {}]
    _assign_event_images(events, ["one.jpg", "two.jpg"], multi_image_post=True)
    assert events == [
        {"image": None, "images": None},
        {"image": None, "images": None},
    ]


def test_single_event_keeps_image_album():
    events = [{}]
    _assign_event_images(events, ["one.jpg", "two.jpg"], multi_image_post=True)
    assert events == [{"image": "one.jpg", "images": ["one.jpg", "two.jpg"]}]


def test_multiple_events_share_only_a_single_post_image():
    events = [{}, {}]
    _assign_event_images(events, ["schedule.jpg"], multi_image_post=False)
    assert events == [
        {"image": "schedule.jpg", "images": None},
        {"image": "schedule.jpg", "images": None},
    ]
