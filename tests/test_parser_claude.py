"""Тесты парсинга JSON от Claude и кэширования."""

import json
import os
import tempfile
import pytest

from parser import _parse_claude_json, _cache_key, _cache_read, _cache_write


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
