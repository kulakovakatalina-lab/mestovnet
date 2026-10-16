import copy
import json

import pytest

import moderation_queue as moderation
from generate_pages import published_events


def weekend():
    return [
        dict(id="jokers", artist="Jokers Band", venue="Рок-н-рольщики",
             source_city="Симферополь", date="2999-10-16", time="21:00",
             source_url="https://example.test/weekly", price="бесплатно", image="/poster.jpg"),
        dict(id="denairo", artist="Денайро", venue="Рок-н-рольщики (Симферополь)",
             source_city="Симферополь", date="2999-10-16", time="21:00",
             source_url="https://example.test/friday", price="бесплатно", image="/poster.jpg"),
    ]


def test_weekly_poster_conflict_includes_both_cards_without_mutating_data():
    events = weekend()
    events[1]["source_url"] = events[0]["source_url"]
    before = copy.deepcopy(events)
    assert set(moderation.schedule_conflicts(events)) == {"jokers", "denairo"}
    assert events == before


@pytest.mark.parametrize("field,value", [
    ("date", "2999-10-17"), ("time", "20:00"), ("time", None),
    ("source_city", "Севастополь"), ("venue", "Jam Club"),
    ("artist", "Jokers Band"), ("date", "2000-01-01"),
    ("venue", None), ("source_city", None), ("artist", "Живая музыка"),
])
def test_unrelated_or_incomplete_cards_do_not_conflict(field, value):
    events = weekend()
    events[1][field] = value
    assert moderation.schedule_conflicts(events) == {}


def test_time_format_and_registered_venue_aliases():
    events = weekend()
    events[1]["time"] = "21.00"
    events[1]["venue"] = "Рок-н-рольщики, Симферополь, ул. Екатерининская, 14"
    assert len(moderation.schedule_conflicts(events)) == 2


def test_cancelled_and_rejected_cards_do_not_block_publication():
    events = weekend()
    events[1]["cancelled"] = True
    assert moderation.schedule_conflicts(events) == {}
    events[1].pop("cancelled")
    assert moderation.schedule_conflicts(events, {"denairo"}) == {}


def test_source_cancellation_does_not_block_other_concert():
    events = weekend()
    events[1]["source_status"] = "cancelled"
    assert moderation.schedule_conflicts(events) == {}


def test_artist_aliases_are_not_different_performers(monkeypatch):
    events = weekend()
    events[1]["artist"] = "Jokers Band Show"
    monkeypatch.setattr(moderation, "load_artists", lambda: [
        dict(name="Jokers Band", aliases=["Jokers Band Show"]),
    ])
    assert moderation.schedule_conflicts(events) == {}


def test_conflicts_require_explicit_review_and_rejection_unblocks_survivor(tmp_path, monkeypatch):
    events = weekend()
    events[0]["auto_updated"] = True
    decisions = [dict(event_id=e["id"], status="approved", reasons=[],
                      fingerprint=moderation.event_fingerprint(e, [])) for e in events]
    for name, filename in (("EVENTS", "events.json"), ("QUEUE", "queue.json"), ("DECISIONS_CACHE", "decisions.json")):
        monkeypatch.setattr(moderation, name, tmp_path / filename)
    moderation.EVENTS.write_text(json.dumps(events), encoding="utf-8")
    monkeypatch.setattr(moderation, "load_decisions", lambda: decisions)
    moderation.main()
    saved = json.loads(moderation.EVENTS.read_text())
    queue = json.loads(moderation.QUEUE.read_text())
    assert len(queue) == 2
    assert all(e["needs_review"] for e in saved)
    assert published_events(saved) == []
    assert all(any(moderation.SCHEDULE_CONFLICT in r for r in e["reasons"]) for e in queue)

    # Модератор подтвердил один концерт с явно показанным конфликтом.
    decisions[0] = dict(event_id="jokers", status="approved", reasons=queue[0]["reasons"],
                        decided_at="2999-01-01")
    moderation.main()
    saved = json.loads(moderation.EVENTS.read_text())
    assert [e["id"] for e in published_events(saved)] == ["jokers"]
    # Одобрение сохраняется и при следующей синхронизации.
    moderation.main()
    assert [e["id"] for e in published_events(json.loads(moderation.EVENTS.read_text()))] == ["jokers"]

    decisions[1] = dict(event_id="denairo", status="rejected", reasons=queue[1]["reasons"])
    moderation.main()
    saved = json.loads(moderation.EVENTS.read_text())
    assert not saved[0]["needs_review"]
    assert [e["id"] for e in published_events(saved)] == ["jokers"]
    assert json.loads(moderation.QUEUE.read_text()) == []
