import json

import moderation_queue


def test_optional_fields_are_approved_but_missing_time_is_queued(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    events_path.write_text(json.dumps([
        {"id": "optional", "date": "2999-01-01", "artist": "A", "time": "19:00", "venue": "Клуб"},
        {"id": "time", "date": "2999-01-01", "artist": "B", "venue": "Клуб", "price": "бесплатно", "image": "/poster.jpg"},
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
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
    events_path.write_text(json.dumps([
        {"id": "past", "date": "2000-01-01", "artist": "A"},
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["moderation_status"] == "archived"
    assert saved["needs_review"] is False
    assert json.loads(queue_path.read_text(encoding="utf-8")) == []
