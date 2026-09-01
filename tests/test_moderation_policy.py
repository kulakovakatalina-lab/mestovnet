import json

import moderation_queue
from generate_pages import cleanup_unpublished_event_pages


def test_optional_fields_are_approved_but_missing_time_is_queued(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([
        {"id": "optional", "date": "2999-01-01", "artist": "A", "time": "19:00", "venue": "Клуб"},
        {"id": "time", "date": "2999-01-01", "artist": "B", "venue": "Клуб", "price": "бесплатно", "image": "/poster.jpg"},
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [])

    moderation_queue.main()

    saved = {event["id"]: event for event in json.loads(events_path.read_text(encoding="utf-8"))}
    assert saved["optional"]["moderation_status"] == "approved"
    assert saved["optional"]["needs_review"] is False
    assert saved["time"]["needs_review"] is True
    assert [event["id"] for event in json.loads(queue_path.read_text(encoding="utf-8"))] == ["time"]


def test_past_incomplete_event_is_archived(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([
        {"id": "past", "date": "2000-01-01", "artist": "A"},
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["moderation_status"] == "archived"
    assert saved["needs_review"] is False
    assert json.loads(queue_path.read_text(encoding="utf-8")) == []


def test_automatically_reconciled_event_is_published_without_review(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([
        {"id": "updated", "date": "2999-01-01", "artist": "A", "venue": "Клуб",
         "auto_updated": True},
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["moderation_status"] == "approved"
    assert saved["needs_review"] is False


def test_seo_collision_publishes_one_event_and_queues_the_other(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    settings_path = tmp_path / "settings.json"
    events_path.write_text(json.dumps([
        {"id": "a", "date": "2999-01-01", "time": "19:00", "artist": "Кальвадос", "venue": "Рок-н-рольщики", "source_city": "Симферополь", "price": "500 ₽", "image": "/a.jpg"},
        {"id": "b", "date": "2999-01-01", "time": "20:00", "artist": "Кальвадос", "venue": "Рок-н-рольщики", "source_city": "Симферополь", "price": "500 ₽", "image": "/b.jpg"},
    ]), encoding="utf-8")
    settings_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "SETTINGS", settings_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [])

    moderation_queue.main()

    saved = {event["id"]: event for event in json.loads(events_path.read_text(encoding="utf-8"))}
    queued = json.loads(queue_path.read_text(encoding="utf-8"))
    assert sum(event["needs_review"] for event in saved.values()) == 1
    assert len(queued) == 1
    assert moderation_queue.SEO_COLLISION in queued[0]["reasons"]


def test_hidden_event_page_is_removed_from_public_output(tmp_path):
    events_dir = tmp_path / "event"
    events_dir.mkdir()
    stale = events_dir / "deadbeef"
    stale.write_text('<link rel="canonical" href="https://mestov.net/event/deadbeef">', encoding="utf-8")
    current = events_dir / "cafebabe"
    current.write_text('<link rel="canonical" href="https://mestov.net/event/cafebabe">', encoding="utf-8")

    assert cleanup_unpublished_event_pages(events_dir, {"cafebabe"}) == 1
    assert not stale.exists()
    assert current.exists()
