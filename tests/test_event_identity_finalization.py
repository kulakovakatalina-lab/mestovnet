"""Regression coverage for stable, collision-safe event IDs."""

import json
from types import SimpleNamespace

import pytest

import parser
from generate_pages import make_sitemap


def _shadow_event(**overrides):
    event = {
        "id": "67c8bb8c",
        "date": "2026-11-28",
        "time": "21:00",
        "artist": "Группа «Тень Клоуна»",
        "venue": "Рок-н-рольщики (Симферополь)",
        "source_url": "https://vk.com/wall-237501275_211",
        "source_channel": "rocknroll_82",
        "source_city": "Симферополь",
        "event_type": "трибьют",
        "description": "Большая премьера: трибьют «Короля и Шута»",
        "price": "1000₽",
        "post_date": "2026-11-02T12:05:22+00:00",
    }
    event.update(overrides)
    return event


def test_repeated_extraction_keeps_one_published_event_and_id(tmp_path):
    published = _shadow_event()
    repeated = {**published, "description": "Уточнённое описание"}

    deduplicated = parser.deduplicate_events([published, repeated])
    result = parser.finalize_event_ids(
        deduplicated, existing=[published], diagnostic_path=str(tmp_path / "diag.json")
    )

    assert len(result) == 1
    assert result[0]["id"] == "67c8bb8c"


def test_different_confirmed_sessions_keep_both_stable_ids_and_published_id():
    published = _shadow_event()
    second = _shadow_event(time="22:30")

    deduplicated = parser.deduplicate_events([published, second])
    first_run = parser.finalize_event_ids(deduplicated, existing=[published])
    second_run = parser.finalize_event_ids(deduplicated, existing=[published])

    assert len(first_run) == 2
    assert len({event["id"] for event in first_run}) == 2
    by_time = {event["time"]: event["id"] for event in first_run}
    assert by_time["21:00"] == "67c8bb8c"
    assert by_time["22:30"] != "67c8bb8c"
    assert {event["time"]: event["id"] for event in second_run} == by_time

    sitemap = make_sitemap([], event_ids=[event["id"] for event in first_run])
    assert sitemap.count("<loc>https://mestov.net/event/") == 2
    assert len({line.split("<loc>", 1)[1].split("</loc>", 1)[0]
                for line in sitemap.splitlines() if "<loc>https://mestov.net/event/" in line}) == 2


def test_ambiguous_collision_fails_closed_with_actionable_diagnostic(tmp_path):
    first = _shadow_event(time=None)
    second = _shadow_event(time=None, venue="Другая площадка")
    diagnostic = tmp_path / "event-id-conflicts.json"

    with pytest.raises(parser.EventIdentityConflict, match="event-id-conflicts.json"):
        parser.finalize_event_ids([first, second], diagnostic_path=str(diagnostic),
                                  stage="after-archive-restoration")

    payload = json.loads(diagnostic.read_text(encoding="utf-8"))
    conflict = payload["conflicts"][0]
    assert conflict["stage"] == "after-archive-restoration"
    assert conflict["classification"] == "ambiguous"
    assert {row["venue"] for row in conflict["events"]} == {
        "Рок-н-рольщики (Симферополь)", "Другая площадка"
    }
    assert "source_excerpt" not in diagnostic.read_text(encoding="utf-8")


def test_archive_restoration_is_included_in_final_uniqueness_check():
    archived = _shadow_event()
    repeated = {**archived}
    restored = parser.retain_existing_events([archived], [repeated])

    result = parser.finalize_event_ids(
        parser.deduplicate_events(restored), existing=[archived]
    )

    assert len(result) == 1
    assert result[0]["id"] == "67c8bb8c"
    assert len({event["id"] for event in result}) == len(result)


def test_archive_row_is_restored_when_same_id_candidate_is_another_session():
    published = _shadow_event()
    second_session = _shadow_event(time="22:30")

    retained = parser.retain_existing_events([published], [second_session])
    result = parser.finalize_event_ids(
        parser.deduplicate_events(retained), existing=[published]
    )

    assert len(result) == 2
    assert {event["time"] for event in result} == {"21:00", "22:30"}
    assert next(event for event in result if event["time"] == "21:00")["id"] == "67c8bb8c"
    assert len({event["id"] for event in result}) == 2


def test_synthetic_legacy_eight_character_hash_collision_is_disambiguated(monkeypatch):
    first = _shadow_event(time="21:00", source_url="https://example.test/a", id=None)
    second = _shadow_event(time="22:30", source_url="https://example.test/b", id=None)
    monkeypatch.setattr(
        parser.hashlib, "md5",
        lambda *_args, **_kwargs: SimpleNamespace(hexdigest=lambda: "deadbeef01234567"),
    )

    first_run = parser.finalize_event_ids([first, second])
    reversed_run = parser.finalize_event_ids([second, first])

    by_time = {event["time"]: event["id"] for event in first_run}
    assert "deadbeef" in by_time.values()
    assert len(set(by_time.values())) == 2
    assert {event["time"]: event["id"] for event in reversed_run} == by_time
    assert set(by_time) == {"21:00", "22:30"}
