import json

import repair_event_data


def test_rocknroll_weekend_keeps_confirmed_dates_on_repeated_cleanup(tmp_path, monkeypatch):
    """A weekly poster must not create a second Jokers concert on Friday."""
    path = tmp_path / "events.json"
    events = [
        {"id": "144c14a0", "artist": "Jokers Band", "date": "2026-10-16"},
        {"id": "49e3c711", "artist": "группа «Денайро»", "date": "2026-10-16"},
        {"id": "3c7b9cb7", "artist": "Jokers Band", "date": "2026-10-17"},
    ]
    for event in events:
        event.update(time="21:00", venue="Рок-н-рольщики", source_city="Симферополь")
    path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(repair_event_data, "EVENTS_FILE", path)

    repair_event_data.main()
    first = path.read_text(encoding="utf-8")
    repair_event_data.main()

    assert path.read_text(encoding="utf-8") == first
    remaining = json.loads(first)
    assert [(e["id"], e["date"], e["time"]) for e in remaining] == [
        ("49e3c711", "2026-10-16", "21:00"),
        ("3c7b9cb7", "2026-10-17", "21:00"),
    ]
