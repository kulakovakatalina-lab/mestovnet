import json

import pytest

from notify_new import build_message


def snapshot(path, events, settings=None, pages=()):
    path.mkdir()
    (path / "events.json").write_text(json.dumps(events), encoding="utf-8")
    (path / "settings.json").write_text(json.dumps(settings or {}), encoding="utf-8")
    (path / "event").mkdir()
    for event_id in pages:
        (path / "event" / event_id).write_text("event page", encoding="utf-8")
    return path


@pytest.mark.parametrize("fields,settings", [
    ({"needs_review": True}, {}),
    ({"moderation_status": "rejected"}, {}),
    ({}, {"hidden": ["https://t.me/clubjam/1146"]}),
])
def test_unpublished_event_is_not_announced_even_with_old_page(tmp_path, fields, settings):
    before = snapshot(tmp_path / "before", [])
    event = {"id": "957d09e0", "source_url": "https://t.me/clubjam/1146", **fields}
    after = snapshot(tmp_path / "after", [event], settings, pages=[event["id"]])
    assert build_message(before, after) is None


def test_missing_page_is_not_linked(tmp_path):
    before = snapshot(tmp_path / "before", [])
    after = snapshot(tmp_path / "after", [{"id": "missing"}])
    assert build_message(before, after) is None


def test_approved_event_is_announced_with_corrected_title(tmp_path):
    event = {"id": "957d09e0", "artist": "СПЛИН", "source_url": "https://t.me/clubjam/1146"}
    before = snapshot(tmp_path / "before", [{**event, "needs_review": True}])
    after = snapshot(tmp_path / "after", [event],
                     {"names": {event["source_url"]: "Трибьют Сплина"}}, pages=[event["id"]])
    message = build_message(before, after)
    assert "https://mestov.net/event/957d09e0" in message
    assert "Трибьют Сплина" in message
    assert "Новое на Местов.Нет (1)" in message


def test_previously_published_event_is_not_announced_again(tmp_path):
    event = {"id": "957d09e0", "moderation_status": "archived"}
    before = snapshot(tmp_path / "before", [event])
    after = snapshot(tmp_path / "after", [event], pages=[event["id"]])
    assert build_message(before, after) is None


def test_unhidden_event_is_announced(tmp_path):
    event = {"id": "957d09e0", "source_url": "https://t.me/clubjam/1146"}
    before = snapshot(tmp_path / "before", [event], {"hidden": [event["source_url"]]})
    after = snapshot(tmp_path / "after", [event], pages=[event["id"]])
    assert "https://mestov.net/event/957d09e0" in build_message(before, after)
