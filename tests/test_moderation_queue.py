import json

import moderation_queue


def test_unreviewed_and_rejected_events_are_not_publishable():
    """Один и тот же фильтр использует генератор всех статических страниц."""
    from generate_pages import apply_settings

    events = [
        {"id": "visible", "source_url": "https://example.test/visible"},
        {"id": "review", "source_url": "https://example.test/review", "needs_review": True},
        {"id": "rejected", "source_url": "https://example.test/rejected", "moderation_status": "rejected"},
        {"id": "approved", "source_url": "https://example.test/approved", "moderation_status": "approved"},
    ]

    assert [event["id"] for event in apply_settings(events, {})] == ["visible", "approved"]


def test_dynamic_templates_apply_the_moderation_filter(project_root):
    """Главная и динамические шаблоны не должны расходиться со статикой."""
    expected = "e.needs_review || e.moderation_status === 'rejected'"
    for template in ("index.html", "genre.html", "event.html"):
        assert expected in (project_root / template).read_text(encoding="utf-8")


def test_approved_event_with_same_issues_leaves_queue(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    event = {
        "id": "approved1", "source_url": "https://example.test/post",
        "artist": "Артист", "date": "2026-09-01", "venue": "Клуб",
        "time": "", "price": "", "image": "",
    }
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [{
        "event_id": "approved1", "source_url": event["source_url"],
        "status": "approved", "reasons": ["нет времени", "нет цены", "нет постера"],
        "decided_at": "2026-08-28T01:00:00Z",
    }])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["needs_review"] is False
    assert saved["moderation_status"] == "approved"
    assert json.loads(queue_path.read_text(encoding="utf-8")) == []


def test_rejected_event_stays_out_of_queue(tmp_path, monkeypatch):
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    event = {"id": "rejected1", "source_url": "https://example.test/post", "artist": "Артист"}
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [{
        "event_id": "rejected1", "source_url": event["source_url"], "status": "rejected",
    }])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["needs_review"] is False
    assert saved["moderation_status"] == "rejected"
