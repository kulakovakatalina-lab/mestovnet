"""Тесты утилитарных функций parser.py: normalize, venue_match, artist_parts, detect_genre, detect_city."""

import pytest

from parser import (
    _normalize,
    _normalize_venue,
    _venue_match,
    _artist_parts,
    _artist_set,
    _field_count,
    _is_refusal_event,
    _print_dry_run_report,
    _sanitize_event_dates,
    _valid_date_or_none,
    detect_genre,
    _detect_city,
)


def test_standup_is_rejected_as_non_music():
    assert _is_refusal_event({"artist": "StandUp Валентин Сидоров"})
    assert _is_refusal_event({"artist": "Стендап-концерт"})


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
    ])
    def test_city_detection(self, text, expected):
        assert _detect_city(text) == expected

    def test_no_city(self):
        assert _detect_city("просто текст без города") is None

    def test_case_insensitive(self):
        assert _detect_city("ЯЛТА") == "Ялта"
        assert _detect_city("севастополь") == "Севастополь"
