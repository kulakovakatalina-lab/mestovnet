import parser


def test_restore_single_poster_to_all_current_events(monkeypatch):
    events = [{"date": "2999-01-01", "source_url": "https://t.me/example/1"},
              {"date": "2999-01-02", "source_url": "https://t.me/example/1"},
              {"date": "2000-01-01", "source_url": "https://t.me/example/1"}]
    monkeypatch.setattr(parser, "_fetch_images_from_url", lambda url: ["poster"])
    monkeypatch.setattr(parser, "download_image", lambda url: "/images/events/shared.jpg")
    assert parser._redistribute_images(events) == 2
    assert events[0]["image"] == events[1]["image"] == "/images/events/shared.jpg"
    assert "image" not in events[2]


def test_restore_preserves_existing_poster_and_uses_saved_album(monkeypatch):
    events = [{"date": "2999-01-01", "source_url": "source", "image": "/one.jpg", "images": ["/one.jpg", "/two.jpg"]},
              {"date": "2999-01-01", "source_url": "source"}]
    monkeypatch.setattr(parser.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(parser, "_fetch_images_from_url", lambda url: (_ for _ in ()).throw(AssertionError("unneeded fetch")))
    assert parser._redistribute_images(events) == 1
    assert events[1]["images"] == ["/one.jpg", "/two.jpg"]
    assert events[0]["image"] == "/one.jpg"


def test_restore_failure_leaves_event_unchanged(monkeypatch):
    events = [{"date": "2999-01-01", "source_url": "source"}]
    monkeypatch.setattr(parser, "_fetch_images_from_url", lambda url: [])
    assert parser._redistribute_images(events) == 0
    assert events == [{"date": "2999-01-01", "source_url": "source"}]
