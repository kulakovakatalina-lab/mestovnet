"""Тесты фичи «отменено»: published_events, render_card, make_jsonld_events."""

import pytest

from generate_pages import published_events, make_jsonld_events, render_card


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


class TestPublishedEventsCancelled:
    def test_marks_source_cancellation_without_mutating_original(self):
        events = [_event(source_status="cancelled"), _event(id="other")]
        result = published_events(events)
        assert result[0]["cancelled"] is True
        assert "cancelled" not in events[0]
        assert "cancelled" not in result[1]

    @pytest.mark.parametrize("fields", [
        {"needs_review": True}, {"moderation_status": "rejected"},
    ])
    def test_unpublished_cancellation_is_excluded(self, fields):
        assert published_events([_event(source_status="cancelled", **fields)]) == []


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
