import parser


def test_single_fresh_source_event_is_updated_automatically():
    old = {"id": "stable", "source_url": "https://example.test/post", "date": "2027-09-01",
           "time": "19:00", "artist": "Артист", "venue": "Клуб", "price": "500"}
    fresh = {"source_url": old["source_url"], "date": old["date"], "time": "20:00",
             "artist": "Артист", "venue": "Клуб", "price": "700"}

    existing, incoming = parser.reconcile_source_updates(
        [old], [fresh], {old["source_url"]: {"cancelled": False}}, today="2026-08-30"
    )

    assert incoming == []
    assert len(existing) == 1
    assert existing[0]["id"] == "stable"
    assert existing[0]["time"] == "20:00"
    assert existing[0]["price"] == "700"
    assert existing[0]["auto_updated"] is True


def test_explicit_cancellation_marks_all_future_events_from_source():
    url = "https://example.test/post"
    old = [
        {"id": "one", "source_url": url, "date": "2027-09-01", "artist": "А"},
        {"id": "two", "source_url": url, "date": "2027-09-02", "artist": "Б"},
    ]

    existing, incoming = parser.reconcile_source_updates(
        old, [], {url: {"cancelled": True}}, today="2026-08-30"
    )

    assert incoming == []
    assert {event["id"] for event in existing} == {"one", "two"}
    assert all(event["source_status"] == "cancelled" and event["cancelled"] for event in existing)


def test_ambiguous_weekly_poster_is_not_updated():
    url = "https://example.test/post"
    old = [
        {"id": "one", "source_url": url, "date": "2027-09-01", "artist": "А"},
        {"id": "two", "source_url": url, "date": "2027-09-02", "artist": "Б"},
    ]
    fresh = [{"source_url": url, "date": "2027-09-01", "artist": "Новый артист"}]

    existing, incoming = parser.reconcile_source_updates(
        old, fresh, {url: {"cancelled": False}}, today="2026-08-30"
    )

    assert existing == old
    assert incoming == fresh
