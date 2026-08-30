import json

import moderation_queue


def test_network_errors_are_treated_as_failed_sync(monkeypatch):
    monkeypatch.setenv("MODERATION_WORKER_URL", "https://worker.example.test")
    monkeypatch.setenv("MODERATION_SYNC_TOKEN", "secret")

    def fail(*args, **kwargs):
        raise OSError("TLS connection reset")

    monkeypatch.setattr(moderation_queue.urllib.request, "urlopen", fail)

    assert moderation_queue.load_decisions() is None


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
    decisions_path = tmp_path / "moderation_decisions.json"
    event = {
        "id": "approved1", "source_url": "https://example.test/post",
        "artist": "Артист", "date": "2026-09-01", "venue": "Клуб",
        "time": "", "price": "", "image": "",
    }
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
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
    decisions_path = tmp_path / "moderation_decisions.json"
    event = {"id": "rejected1", "source_url": "https://example.test/post", "artist": "Артист"}
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [{
        "event_id": "rejected1", "source_url": event["source_url"], "status": "rejected",
    }])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["needs_review"] is False
    assert saved["moderation_status"] == "rejected"


def test_worker_failure_preserves_cached_approval(tmp_path, monkeypatch):
    event = {
        "id": "approved1", "source_url": "https://example.test/post",
        "artist": "Артист", "date": "2026-09-01", "venue": "Клуб",
        "time": "", "price": "", "image": "",
    }
    issues = moderation_queue.reasons(event)
    decision = {
        "event_id": event["id"], "status": "approved", "reasons": issues,
        "fingerprint": moderation_queue.event_fingerprint(event, issues),
    }
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    decisions_path.write_text(json.dumps([decision]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: None)

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["moderation_status"] == "approved"
    assert saved["needs_review"] is False


def test_changed_event_requires_new_approval(tmp_path, monkeypatch):
    old = {
        "id": "approved1", "source_url": "https://example.test/post",
        "artist": "Артист", "date": "2026-09-01", "venue": "Клуб",
        "time": "", "price": "", "image": "",
    }
    event = {**old, "artist": "Другой артист"}
    issues = moderation_queue.reasons(old)
    decision = {
        "event_id": event["id"], "status": "approved", "reasons": issues,
        "decided_at": "2026-08-28T01:00:00Z",
        "fingerprint": moderation_queue.event_fingerprint(old, issues),
    }
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    decisions_path.write_text(json.dumps([decision]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [
        {key: value for key, value in decision.items() if key != "fingerprint"}
    ])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["needs_review"] is True
    assert "moderation_status" not in saved


def test_worker_failure_preserves_cached_rejection(tmp_path, monkeypatch):
    event = {"id": "rejected1", "source_url": "https://example.test/post", "artist": "Артист"}
    decision = {"event_id": event["id"], "status": "rejected", "reasons": [
        "нет времени", "нет площадки", "нет цены", "нет постера"
    ]}
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    decisions_path.write_text(json.dumps([decision]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: None)

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["moderation_status"] == "rejected"
    assert saved["needs_review"] is False


def test_successful_empty_response_does_not_use_stale_cache(tmp_path, monkeypatch):
    event = {"id": "rejected1", "source_url": "https://example.test/post", "artist": "Артист"}
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    decisions_path.write_text(json.dumps([
        {"event_id": event["id"], "status": "rejected"}
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["needs_review"] is True
    assert "moderation_status" not in saved


def test_legacy_source_decision_is_not_applied_to_shared_url(tmp_path, monkeypatch):
    events = [
        {"id": "one", "source_url": "https://example.test/post", "artist": "A"},
        {"id": "two", "source_url": "https://example.test/post", "artist": "B"},
    ]
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "moderation_decisions.json"
    events_path.write_text(json.dumps(events), encoding="utf-8")
    decisions_path.write_text(json.dumps([
        {"source_url": "https://example.test/post", "status": "rejected"}
    ]), encoding="utf-8")
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: None)

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))
    assert all(event["needs_review"] is True for event in saved)


def test_cache_write_failure_does_not_cancel_current_remote_decision(tmp_path, monkeypatch):
    event = {
        "id": "approved1", "source_url": "https://example.test/post",
        "artist": "Артист", "date": "2026-09-01", "venue": "Клуб",
        "time": "", "price": "", "image": "",
    }
    events_path = tmp_path / "events.json"
    queue_path = tmp_path / "moderation.json"
    decisions_path = tmp_path / "cache-as-directory"
    events_path.write_text(json.dumps([event]), encoding="utf-8")
    decisions_path.mkdir()
    monkeypatch.setattr(moderation_queue, "EVENTS", events_path)
    monkeypatch.setattr(moderation_queue, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_queue, "DECISIONS_CACHE", decisions_path)
    monkeypatch.setattr(moderation_queue, "load_decisions", lambda: [{
        "event_id": event["id"], "status": "approved",
        "reasons": moderation_queue.reasons(event),
        "decided_at": "2026-08-30T01:00:00Z",
    }])

    moderation_queue.main()

    saved = json.loads(events_path.read_text(encoding="utf-8"))[0]
    assert saved["moderation_status"] == "approved"
    assert saved["needs_review"] is False
    # Даже без журнала состояние в events.json содержит отпечаток и может
    # пережить следующую недоступность Worker-а.
    assert saved["moderation_decision_fingerprint"] == moderation_queue.event_fingerprint(
        event, moderation_queue.reasons(event)
    )
