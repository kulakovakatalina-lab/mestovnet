from datetime import datetime, timezone
from pathlib import Path

import generate_pages
from generate_pages import (
    cleanup_stale_generated_pages,
    load_generated_pages_manifest,
    save_generated_pages_manifest,
    today_str,
)
from parser import moscow_today


def test_today_is_calculated_in_moscow_for_generator_and_parser():
    # В UTC ещё 31 декабря, а в Москве уже 1 января.
    instant = datetime(2026, 12, 31, 21, 30, tzinfo=timezone.utc)

    assert today_str(instant) == "2027-01-01"
    assert moscow_today(instant) == "2027-01-01"


def test_cleanup_only_removes_pages_recorded_by_previous_build(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_pages, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        generate_pages, "GENERATED_PAGES_MANIFEST", tmp_path / ".generated-pages.json"
    )
    (tmp_path / "cities").mkdir()
    (tmp_path / "venues").mkdir()
    (tmp_path / "event").mkdir()
    (tmp_path / "artist").mkdir()

    stale_city = tmp_path / "cities" / "old.html"
    stale_city.write_text("generated", encoding="utf-8")
    current_venue = tmp_path / "venues" / "current"
    current_venue.write_text("generated", encoding="utf-8")
    archived_event = tmp_path / "event" / "archived"
    archived_event.write_text("archive", encoding="utf-8")
    archived_artist = tmp_path / "artist" / "archived"
    archived_artist.write_text("archive", encoding="utf-8")

    previous = {Path("cities/old.html"), Path("venues/current")}
    current = {Path("venues/current")}
    save_generated_pages_manifest(previous)

    assert cleanup_stale_generated_pages(load_generated_pages_manifest(), current) == 1
    assert not stale_city.exists()
    assert current_venue.exists()
    assert archived_event.exists()
    assert archived_artist.exists()


def test_manifest_rejects_archive_paths_and_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_pages, "BASE_DIR", tmp_path)
    manifest = tmp_path / ".generated-pages.json"
    monkeypatch.setattr(generate_pages, "GENERATED_PAGES_MANIFEST", manifest)
    manifest.write_text(
        '["cities/yalta.html", "event/archive", "artist/name", "../settings.json"]',
        encoding="utf-8",
    )

    assert load_generated_pages_manifest() == {Path("cities/yalta.html")}
