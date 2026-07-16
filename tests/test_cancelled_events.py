"""Тесты фичи «отменено»: apply_settings, render_card, make_jsonld_events."""

import pytest

from generate_pages import apply_settings, make_jsonld_events, render_card


def _event(**overrides):
    base = {
        "id": "abc123",
        "date": "2099-01-01",
        "time": "19:00",
        "artist": "Тестовый Артист",
        "venue": "Тестовая площадка",
        "source_city": "Симферополь",
        "source_url": "https://t.me/testchannel/1",
        "event_type": "концерт",
        "genre": "рок",
        "price": "от 500 ₽",
    }
    base.update(overrides)
    return base


class TestApplySettingsCancelled:
    def test_marks_event_cancelled_by_source_url(self):
        events = [_event()]
        settings = {"cancelled": [events[0]["source_url"]]}
        result = apply_settings(events, settings)
        assert result[0]["cancelled"] is True

    def test_leaves_other_events_untouched(self):
        events = [_event(source_url="https://t.me/testchannel/1"),
                  _event(source_url="https://t.me/testchannel/2", id="def456")]
        settings = {"cancelled": ["https://t.me/testchannel/1"]}
        result = apply_settings(events, settings)
        assert result[0].get("cancelled") is True
        assert result[1].get("cancelled") is None

    def test_absent_cancelled_key_does_not_break(self):
        events = [_event()]
        result = apply_settings(events, {})
        assert result[0].get("cancelled") is None

    def test_does_not_mutate_original_events(self):
        events = [_event()]
        settings = {"cancelled": [events[0]["source_url"]]}
        apply_settings(events, settings)
        assert "cancelled" not in events[0]

    def test_cancelled_and_hidden_together(self):
        # скрытое событие не должно попадать в результат вообще,
        # даже если оно также помечено отменённым
        events = [_event()]
        url = events[0]["source_url"]
        settings = {"hidden": [url], "cancelled": [url]}
        result = apply_settings(events, settings)
        assert result == []


class TestRenderCardCancelled:
    def test_shows_cancelled_label(self):
        html = render_card(_event(cancelled=True))
        assert "отменено" in html
        assert "cancelled-tag" in html

    def test_no_cancelled_label_by_default(self):
        html = render_card(_event())
        assert "отменено" not in html
        assert "cancelled-tag" not in html

    def test_card_has_cancelled_class(self):
        html = render_card(_event(cancelled=True))
        assert 'class="card cancelled"' in html

    def test_card_without_cancelled_class_by_default(self):
        html = render_card(_event())
        assert 'class="card"' in html


class TestJsonLdCancelled:
    def test_sets_event_status_cancelled(self):
        jsonld = make_jsonld_events([_event(cancelled=True)])
        assert "https://schema.org/EventCancelled" in jsonld

    def test_no_event_status_by_default(self):
        jsonld = make_jsonld_events([_event()])
        assert "eventStatus" not in jsonld
