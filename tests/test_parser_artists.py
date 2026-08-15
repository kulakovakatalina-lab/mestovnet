"""Тесты извлечения артистов: _extract_artist_from_description, _fallback_artist."""

import pytest

from parser import _extract_artist_from_description, _fallback_artist


class TestExtractArtistFromDescription:
    def test_vystuplenie_pattern(self):
        desc = "Выступление Сплин в клубе"
        assert _extract_artist_from_description(desc) is not None

    def test_koncert_pattern(self):
        desc = "Концерт группы Сплин"
        assert _extract_artist_from_description(desc) is not None

    def test_dj_pattern(self):
        desc = "DJ Smash — сет в клубе"
        result = _extract_artist_from_description(desc)
        assert result is not None
        assert "Smash" in result

    def test_dj_set_pattern(self):
        desc = "DJ-сет с DJ Groove до утра"
        assert _extract_artist_from_description(desc) is not None

    def test_group_quotes(self):
        desc = 'Группа «Сплин» выступает'
        result = _extract_artist_from_description(desc)
        assert result is not None
        assert "Сплин" in result

    def test_ispolnyaet_pattern(self):
        desc = '«ДДТ» исполняет хиты'
        result = _extract_artist_from_description(desc)
        assert result is not None

    def test_empty_description(self):
        assert _extract_artist_from_description("") is None
        assert _extract_artist_from_description(None) is None

    def test_no_artist_info(self):
        desc = "Живая музыка каждый вечер"
        assert _extract_artist_from_description(desc) is None


class TestFallbackArtist:
    def test_music_lottery(self):
        event = {"event_type": "концерт", "description": "Музыкальное лото в пятницу"}
        assert _fallback_artist(event) is None

    def test_music_quiz(self):
        event = {"event_type": "концерт", "description": "Музыкальный квиз"}
        assert _fallback_artist(event) is None

    def test_dj_party(self):
        event = {"event_type": "вечеринка", "description": "DJ играет до утра"}
        assert _fallback_artist(event) is None

    def test_dj_party_lowercase(self):
        event = {"event_type": "вечеринка", "description": "диджей играет"}
        assert _fallback_artist(event) is None

    def test_sound_therapy(self):
        event = {"event_type": "концерт", "description": "Звукотерапия тибетскими чашами"}
        assert _fallback_artist(event) is None

    def test_gong_therapy(self):
        event = {"event_type": "концерт", "description": "Гонг медитация"}
        assert _fallback_artist(event) is None

    def test_kvartirnik(self):
        event = {"event_type": "концерт", "description": "Квартирник у камина"}
        assert _fallback_artist(event) is None

    def test_spectacle_with_name(self):
        event = {"event_type": "другое", "description": 'Спектакль «Ревизор»'}
        result = _fallback_artist(event)
        assert "Ревизор" in result

    def test_spectacle_without_name(self):
        event = {"event_type": "другое", "description": "Театральная постановка"}
        assert _fallback_artist(event) is None

    def test_festival_with_name(self):
        event = {"event_type": "фестиваль", "description": 'Открытие фестиваля «Крымская волна»'}
        result = _fallback_artist(event)
        assert "Крымская волна" in result

    def test_festival_without_name(self):
        event = {"event_type": "фестиваль", "description": "Летний фестиваль"}
        assert _fallback_artist(event) is None

    def test_concert_with_quotes(self):
        event = {"event_type": "концерт", "description": 'Концерт «Зимняя сказка»'}
        result = _fallback_artist(event)
        assert "Зимняя сказка" in result

    def test_live_concert(self):
        event = {"event_type": "концерт", "description": "Живой концерт каждый вечер"}
        assert _fallback_artist(event) is None

    def test_music_evening(self):
        event = {"event_type": "концерт", "description": "Музыкальный вечер"}
        assert _fallback_artist(event) is None

    def test_live_sound(self):
        event = {"event_type": "концерт", "description": "Живой звук на террасе"}
        assert _fallback_artist(event) is None

    def test_season_opening(self):
        event = {"event_type": "концерт", "description": "Открытие сезона"}
        assert _fallback_artist(event) is None

    def test_party_with_theme(self):
        event = {"event_type": "вечеринка", "description": "Вечеринка в стиле Ретро"}
        assert _fallback_artist(event) is None

    def test_party_without_theme(self):
        event = {"event_type": "вечеринка", "description": "Танцы до утра"}
        assert _fallback_artist(event) is None

    def test_deguestation(self):
        event = {"event_type": "другое", "description": "Дегустация вин"}
        assert _fallback_artist(event) is None

    def test_mass_event(self):
        event = {"event_type": "другое", "description": "Массовое мероприятие"}
        assert _fallback_artist(event) is None

    def test_ethno_project(self):
        event = {"event_type": "другое", "description": "Этнокультурный проект"}
        assert _fallback_artist(event) is None

    def test_no_fallback(self):
        event = {"event_type": "концерт", "description": "Просто концерт"}
        assert _fallback_artist(event) is None