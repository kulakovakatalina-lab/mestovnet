"""Тесты парсинга JSON от Claude и кэширования."""

import json
import os
import tempfile
import pytest

from parser import (
    _parse_claude_json,
    _cache_key,
    _cache_read,
    _cache_write,
    _only_event_dicts,
    _clean_batch_result,
)


class TestParseClaudeJson:
    def test_valid_json(self):
        raw = json.dumps({"key": "value"})
        assert _parse_claude_json(raw) == {"key": "value"}

    def test_json_array(self):
        raw = json.dumps([1, 2, 3])
        assert _parse_claude_json(raw) == [1, 2, 3]

    def test_markdown_code_block(self):
        raw = '```json\n{"key": "value"}\n```'
        assert _parse_claude_json(raw) == {"key": "value"}

    def test_markdown_without_lang(self):
        raw = '```\n{"key": "value"}\n```'
        assert _parse_claude_json(raw) == {"key": "value"}

    def test_invalid_json(self):
        raw = "not json at all"
        assert _parse_claude_json(raw) is None

    def test_empty_string(self):
        assert _parse_claude_json("") is None

    def test_non_dict_non_list(self):
        raw = '"just a string"'
        assert _parse_claude_json(raw) == "just a string"


class TestOnlyEventDicts:
    def test_filters_strings_from_list(self):
        events = [
            {"date": "2026-08-01"},
            "нет событий",
            {"artist": "X"},
            "   ",
        ]
        assert _only_event_dicts(events) == [
            {"date": "2026-08-01"},
            {"artist": "X"},
        ]

    def test_keeps_empty(self):
        assert _only_event_dicts([]) == []

    def test_filters_non_dict_values(self):
        events = [42, None, "ошибка"]
        assert _only_event_dicts(events) == []

    def test_normalizes_list_fields(self):
        events = [{
            "date": "2026-08-01",
            "artist": ["Группа", "Другое"],
            "venue": ["Бар"],
            "price": 500,
        }]
        result = _only_event_dicts(events)
        assert result[0]["artist"] == "Группа, Другое"
        assert result[0]["venue"] == "Бар"
        assert result[0]["price"] == "500"
        assert result[0]["date"] == "2026-08-01"

    def test_keeps_none_fields(self):
        events = [{"date": "2026-08-01", "artist": None}]
        assert _only_event_dicts(events) == [{"date": "2026-08-01", "artist": None}]

    def test_filters_refusal_descriptions(self):
        events = [
            {"date": "2026-08-01", "description": "Нет информации о музыкальном мероприятии."},
            {"date": "2026-08-02", "description": "Пост не содержит анонса музыкального мероприятия."},
            {"date": "2026-08-03", "description": "Пост содержит информацию о блюде, нет музыкальных мероприятий."},
            {"date": "2026-08-04", "description": "Живая музыка, группа «Берега» каждый вечер."},
        ]
        assert _only_event_dicts(events) == [
            {"date": "2026-08-04", "description": "Живая музыка, группа «Берега» каждый вечер."}
        ]

    def test_keeps_event_without_description(self):
        events = [{"date": "2026-08-01", "artist": "Группа"}]
        assert _only_event_dicts(events) == [{"date": "2026-08-01", "artist": "Группа"}]

    def test_filters_non_music_markers(self):
        events = [
            {"date": "2026-08-01", "description": "Кино под открытым небом: «Сделано в Италии»."},
            {"date": "2026-08-02", "description": "Утренний забег, танцы и завтрак."},
            {"date": "2026-08-03", "description": "Групповая экскурсия с видом на море."},
            {"date": "2026-08-04", "description": "Анонс атмосферы отдыха в отеле, без конкретного музыкального мероприятия."},
            {"date": "2026-08-05", "description": "Джазовый вечер, группа «Берега»."},
        ]
        result = _only_event_dicts(events)
        assert result == [{"date": "2026-08-05", "description": "Джазовый вечер, группа «Берега»."}]

    def test_filters_empty_stub(self):
        events = [
            {"id": "a", "date": None, "artist": None, "venue": None, "description": ""},
            {"id": "b", "date": "2026-08-02", "artist": "Группа", "venue": None, "description": ""},
        ]
        result = _only_event_dicts(events)
        assert [e["id"] for e in result] == ["b"]


class TestCleanBatchResult:
    def test_drops_non_list_values(self):
        result = {
            "url1": [{"artist": "A"}],
            "url2": "нет событий",
            "url3": [{"artist": "B"}, "мусор"],
            "url4": None,
        }
        assert _clean_batch_result(result) == {
            "url1": [{"artist": "A"}],
            "url3": [{"artist": "B"}],
        }

    def test_empty(self):
        assert _clean_batch_result({}) == {}


class TestCacheKey:
    def test_consistent(self):
        key1 = _cache_key("hello")
        key2 = _cache_key("hello")
        assert key1 == key2

    def test_different_inputs(self):
        assert _cache_key("hello") != _cache_key("world")

    def test_fixed_length(self):
        key = _cache_key("test text")
        assert len(key) == 16

    def test_unicode(self):
        key = _cache_key("привет мир")
        assert len(key) == 16


class TestCacheReadWrite:
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import parser
            original_cache = parser.CACHE_DIR
            parser.CACHE_DIR = tmpdir

            try:
                text = "test cache content"
                data = {"events": [{"artist": "X"}]}

                assert _cache_read(text) is None

                _cache_write(text, data)
                result = _cache_read(text)
                assert result == data
            finally:
                parser.CACHE_DIR = original_cache

    def test_corrupted_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import parser
            original_cache = parser.CACHE_DIR
            parser.CACHE_DIR = tmpdir

            try:
                text = "corrupted"
                key = _cache_key(text)
                path = os.path.join(tmpdir, f"{key}.json")
                with open(path, "w") as f:
                    f.write("not valid json {{{")

                assert _cache_read(text) is None
            finally:
                parser.CACHE_DIR = original_cache
