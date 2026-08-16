"""Тесты дедупликации и мёрджа событий."""

import pytest

from parser import (
    deduplicate_events,
    _merge_events,
    _merge_group,
    _bare_artist_key,
    _artist_parts,
    _artist_set,
    is_generic_artist,
    _split_artist_field,
)


class TestMergeEvents:
    def test_basic_merge(self):
        events = [
            {
                "date": "2026-01-15",
                "time": "20:00",
                "artist": "Би-2",
                "event_type": "концерт",
                "venue": "Jam Club",
                "price": "500",
                "description": "desc1",
                "source_city": "Симферополь",
                "source_channel": "ch1",
                "post_date": "2026-01-10",
                "source_url": "https://t.me/ch1/1",
            },
            {
                "date": "2026-01-15",
                "time": None,
                "artist": None,
                "event_type": "концерт",
                "venue": None,
                "price": None,
                "description": "desc2",
                "source_city": None,
                "source_channel": "ch2",
                "post_date": "2026-01-11",
                "source_url": "https://t.me/ch2/1",
            },
        ]
        merged = _merge_events(events)
        assert merged["date"] == "2026-01-15"
        assert merged["artist"] == "Би-2"
        assert merged["venue"] == "Jam Club"
        assert merged["price"] == "500"

    def test_most_recent_source_url(self):
        events = [
            {"post_date": "2026-01-10", "source_url": "url1"},
            {"post_date": "2026-01-12", "source_url": "url2", "description": "more info"},
        ]
        merged = _merge_events(events)
        assert merged["source_url"] == "url2"


class TestMergeGroup:
    def test_combine_artists(self):
        group = [
            {"artist": "Би-2", "post_date": "2026-01-10"},
            {"artist": "Сплин", "post_date": "2026-01-11"},
        ]
        merged = _merge_group(group)
        assert "Би-2" in merged["artist"]
        assert "Сплин" in merged["artist"]

    def test_deduplicate_artists(self):
        group = [
            {"artist": "Би-2", "post_date": "2026-01-10"},
            {"artist": "группа Би-2", "post_date": "2026-01-11"},
        ]
        merged = _merge_group(group)
        assert merged["artist"].count("Би") == 1

    def test_single_event(self):
        group = [{"artist": "X", "post_date": "2026-01-10"}]
        merged = _merge_group(group)
        assert merged["artist"] == "X"


class TestBareArtistKey:
    def test_removes_group_prefix(self):
        assert _bare_artist_key("группа Би-2") == "би2"

    def test_removes_band_prefix(self):
        assert _bare_artist_key("band Queen") == "queen"

    def test_normalizes(self):
        assert _bare_artist_key("«Би-2»") == "би2"


class TestDeduplicateEvents:
    def test_typo_and_parenthetical_artist_merge_at_same_venue(self):
        base = {
            "date": "2026-08-16",
            "venue": "Рок-н-рольщики (Симферополь)",
            "event_type": "концерт",
            "description": "Акустический концерт",
            "post_date": "2026-08-10",
        }
        events = [
            {**base, "source_url": "https://t.me/a/1", "artist": "Роман Курортный (Парень с пакетом)"},
            {**base, "source_url": "https://t.me/b/1", "artist": "Роман Куротрый"},
        ]
        assert len(deduplicate_events(events)) == 1

    def test_same_url_same_date_merge(self):
        events = [
            {
                "source_url": "https://t.me/ch/1",
                "date": "2026-01-15",
                "artist": "Би-2",
                "venue": "Jam Club",
                "event_type": "концерт",
                "description": "desc1",
                "post_date": "2026-01-10",
            },
            {
                "source_url": "https://t.me/ch/1",
                "date": "2026-01-15",
                "artist": None,
                "venue": None,
                "event_type": "концерт",
                "description": "desc2",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 1
        assert result[0]["artist"] == "Би-2"
        assert result[0]["venue"] == "Jam Club"

    def test_different_urls_same_date_same_artist_merge(self):
        events = [
            {
                "source_url": "https://t.me/ch1/1",
                "date": "2026-01-15",
                "artist": "Би-2",
                "venue": "Jam Club",
                "event_type": "концерт",
                "description": "desc1",
                "post_date": "2026-01-10",
            },
            {
                "source_url": "https://t.me/ch2/1",
                "date": "2026-01-15",
                "artist": "Би-2",
                "venue": "Jam Club",
                "event_type": "концерт",
                "description": "desc2",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 1

    def test_different_artists_same_date_different_events(self):
        events = [
            {
                "source_url": "https://t.me/ch1/1",
                "date": "2026-01-15",
                "artist": "Би-2",
                "venue": "Jam Club",
                "event_type": "концерт",
                "description": "desc1",
                "post_date": "2026-01-10",
            },
            {
                "source_url": "https://t.me/ch2/1",
                "date": "2026-01-15",
                "artist": "Сплин",
                "venue": "Markhal",
                "event_type": "концерт",
                "description": "desc2",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 2

    def test_no_url_no_date_kept_separate(self):
        events = [
            {
                "source_url": "",
                "date": "",
                "artist": "X",
                "venue": "V1",
                "event_type": "концерт",
                "description": "desc1",
                "post_date": "2026-01-10",
            },
            {
                "source_url": "",
                "date": "",
                "artist": "Y",
                "venue": "V2",
                "event_type": "концерт",
                "description": "desc2",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 2

    def test_venue_time_match(self):
        events = [
            {
                "source_url": "https://t.me/ch1/1",
                "date": "2026-01-15",
                "artist": "Артист А",
                "venue": "Jam Club",
                "time": "20:00",
                "event_type": "концерт",
                "description": "desc1",
                "post_date": "2026-01-10",
            },
            {
                "source_url": "https://t.me/ch2/1",
                "date": "2026-01-15",
                "artist": "Артист Б",
                "venue": "Jam Club Venue",
                "time": "20:00",
                "event_type": "концерт",
                "description": "desc2",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 1

    def test_empty_list(self):
        assert deduplicate_events([]) == []

    def test_single_event(self):
        events = [
            {
                "source_url": "https://t.me/ch/1",
                "date": "2026-01-15",
                "artist": "X",
                "venue": "V",
                "event_type": "концерт",
                "description": "desc",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 1
        assert result[0]["artist"] == "X"

    def test_festival_partial_artists_merge(self):
        events = [
            {
                "source_url": "https://t.me/ch1/1",
                "date": "2026-01-15",
                "artist": "Би-2, Сплин",
                "venue": "Фестиваль",
                "event_type": "фестиваль",
                "description": "desc1",
                "post_date": "2026-01-10",
            },
            {
                "source_url": "https://t.me/ch2/1",
                "date": "2026-01-15",
                "artist": "Сплин, Земфира",
                "venue": "Фестиваль",
                "event_type": "фестиваль",
                "description": "desc2",
                "post_date": "2026-01-10",
            },
        ]
        result = deduplicate_events(events)
        assert len(result) == 1
        merged_artist = result[0]["artist"]
        assert "Би-2" in merged_artist
        assert "Сплин" in merged_artist
        assert "Земфира" in merged_artist


class TestArtistPartsExtendedJoins:
    def test_feat_dot(self):
        assert _artist_parts("Pasha Rhino feat. DJ Sasha") == ["Pasha Rhino", "DJ Sasha"]

    def test_feat_no_dot(self):
        assert _artist_parts("Pasha Rhino feat DJ Sasha") == ["Pasha Rhino", "DJ Sasha"]

    def test_ft_dot(self):
        assert _artist_parts("Иван Иванов ft. Пётр Петров") == ["Иван Иванов", "Пётр Петров"]

    def test_pri_uchastii(self):
        assert _artist_parts("Группа А при участии Группы Б") == ["Группа А", "Группы Б"]

    def test_s_uchastiem(self):
        assert _artist_parts("Соло с участием хора") == ["Соло", "хора"]

    def test_existing_i_join_still_works(self):
        assert _artist_parts("Ирина и Александр Круг") == ["Ирина", "Александр Круг"]


class TestArtistSetTranslit:
    def test_latin_cyrillic_variants_intersect(self):
        latin = _artist_set({"artist": "SHAMAN"})
        cyrillic = _artist_set({"artist": "ШАМАН"})
        assert latin & cyrillic

    def test_distinct_artists_do_not_intersect(self):
        a = _artist_set({"artist": "Би-2"})
        b = _artist_set({"artist": "Сплин"})
        assert not (a & b)


class TestIsGenericArtist:
    def test_flagged_event_is_generic(self):
        assert is_generic_artist({"artist": "DJ-сет", "artist_is_generic": True})

    def test_recomputes_fallback_by_type(self):
        event = {
            "artist": "Музыкальное лото",
            "event_type": "концерт",
            "description": "Сегодня музыкальное лото для всех гостей",
        }
        assert is_generic_artist(event)

    def test_extracted_from_description_is_not_generic(self):
        # _extract_artist_from_description достаёт РЕАЛЬНОЕ имя из текста —
        # это не плейсхолдер, даже если artist совпадает с извлечённым значением.
        event = {
            "artist": "Сплин",
            "description": "Выступление Сплин в клубе",
        }
        assert not is_generic_artist(event)

    def test_real_name_in_quotes_is_not_generic(self):
        # Регрессия: «Концерт «X»»-паттерн в _fallback_artist достаёт название
        # из кавычек — реальное имя (напр. «Скажите Джаз», настоящая джаз-группа)
        # не должно считаться generic только потому, что оно совпало с тем,
        # что вернул бы фолбэк для этого текста.
        event = {
            "artist": "Скажите Джаз",
            "event_type": "концерт",
            "description": "Концерт «Скажите Джаз» на летней веранде",
        }
        assert not is_generic_artist(event)

    def test_real_artist_is_not_generic(self):
        event = {"artist": "SHAMAN", "description": "Большой концерт на набережной"}
        assert not is_generic_artist(event)

    def test_empty_artist_is_not_generic(self):
        assert not is_generic_artist({"artist": None})

    def test_bare_festival_literal_is_generic(self):
        event = {"artist": "Фестиваль", "event_type": "фестиваль", "description": "Большой летний фестиваль"}
        assert is_generic_artist(event)


class TestSplitArtistField:
    def test_comma_inside_parens_not_split(self):
        assert _split_artist_field(
            "Дуэт «МысКрыма», МысКрыма (Дмитрий Ванх, Вета)"
        ) == ["Дуэт «МысКрыма»", " МысКрыма (Дмитрий Ванх, Вета)"]

    def test_comma_inside_guillemets_not_split(self):
        assert _split_artist_field("«Би-2, live», Сплин") == ["«Би-2, live»", " Сплин"]

    def test_plain_comma_list_still_splits(self):
        assert _split_artist_field("Би-2, Сплин, Земфира") == ["Би-2", " Сплин", " Земфира"]

    def test_no_comma(self):
        assert _split_artist_field("Би-2") == ["Би-2"]

    def test_empty(self):
        assert _split_artist_field("") == [""]
