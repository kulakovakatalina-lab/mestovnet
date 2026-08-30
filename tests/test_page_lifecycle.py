from datetime import datetime, timezone
from pathlib import Path

import generate_pages
from generate_pages import (
    cleanup_stale_generated_pages,
    load_legacy_generated_pages_for_migration,
    load_generated_pages_manifest,
    save_legacy_generated_pages_migration,
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


def test_legacy_venue_requires_its_old_generator_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_pages, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        generate_pages, "LEGACY_GENERATED_PAGES_MANIFEST", tmp_path / ".legacy.json"
    )
    monkeypatch.setattr(
        generate_pages, "LEGACY_GENERATED_PAGES_MIGRATION", tmp_path / ".migrated.json"
    )
    (tmp_path / "venues").mkdir()
    venue = tmp_path / "venues" / "old"
    venue.write_text(
        '<link rel="canonical" href="https://mestov.net/venues/old">'
        '<div class="genre-hero"></div><div id="events-list"></div>',
        encoding="utf-8",
    )
    (tmp_path / ".legacy.json").write_text('["venues/old"]', encoding="utf-8")

    assert load_legacy_generated_pages_for_migration() == {Path("venues/old")}


def test_manifest_rejects_archive_paths_and_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_pages, "BASE_DIR", tmp_path)
    manifest = tmp_path / ".generated-pages.json"
    monkeypatch.setattr(generate_pages, "GENERATED_PAGES_MANIFEST", manifest)
    manifest.write_text(
        '["cities/yalta.html", "event/archive", "artist/name", "../settings.json"]',
        encoding="utf-8",
    )

    assert load_generated_pages_manifest() == {Path("cities/yalta.html")}


def test_legacy_migration_only_adopts_explicit_verified_collection_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_pages, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        generate_pages, "LEGACY_GENERATED_PAGES_MANIFEST", tmp_path / ".legacy.json"
    )
    monkeypatch.setattr(
        generate_pages, "LEGACY_GENERATED_PAGES_MIGRATION", tmp_path / ".migrated.json"
    )
    (tmp_path / "cities").mkdir()
    (tmp_path / "venues").mkdir()
    (tmp_path / "event").mkdir()

    city = tmp_path / "cities" / "old.html"
    city.write_text(
        '<link rel="canonical" href="https://mestov.net/cities/old.html">'
        '<div id="city-filter"></div><div id="events-grid"></div>',
        encoding="utf-8",
    )
    manual_venue = tmp_path / "venues" / "manual"
    manual_venue.write_text("hand-written page", encoding="utf-8")
    archived_event = tmp_path / "event" / "archive"
    archived_event.write_text("archive", encoding="utf-8")
    (tmp_path / ".legacy.json").write_text(
        '["cities/old.html", "venues/manual", "event/archive", "../settings.json"]',
        encoding="utf-8",
    )

    assert load_legacy_generated_pages_for_migration() == {Path("cities/old.html")}
    assert cleanup_stale_generated_pages(
        load_legacy_generated_pages_for_migration(), set()
    ) == 1
    assert not city.exists()
    assert manual_venue.exists()
    assert archived_event.exists()


def test_legacy_migration_never_runs_again_after_recording_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_pages, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        generate_pages, "LEGACY_GENERATED_PAGES_MANIFEST", tmp_path / ".legacy.json"
    )
    monkeypatch.setattr(
        generate_pages, "LEGACY_GENERATED_PAGES_MIGRATION", tmp_path / ".migrated.json"
    )
    (tmp_path / "cities").mkdir()
    page = tmp_path / "cities" / "old.html"
    page.write_text(
        '<link rel="canonical" href="https://mestov.net/cities/old.html">'
        '<div id="city-filter"></div><div id="events-grid"></div>',
        encoding="utf-8",
    )
    (tmp_path / ".legacy.json").write_text('["cities/old.html"]', encoding="utf-8")

    save_legacy_generated_pages_migration({Path("cities/old.html")})
    assert load_legacy_generated_pages_for_migration() == set()
    assert page.exists()
