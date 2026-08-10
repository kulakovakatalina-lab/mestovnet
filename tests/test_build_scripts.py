"""Регрессия на баг, найденный при разработке ежемесячной актуализации
(см. ACTUALIZATION.md): build_venues.py раньше писал venues.json из
6 полей и безвозвратно стирал рукописные description/lat/lon при
пересборке. build_artists.py уже сохранял description и раньше — здесь
проверяем, что это продолжает работать вместе с новым desc_baseline_count.

Гоняем билдеры как реальные subprocess-скрипты в копии репозитория во
временной папке — так же, как их будет запускать ежемесячная процедура,
без монки-патчинга внутренних констант модулей.
"""
import json
import shutil
import subprocess
import sys

import pytest

from tests.conftest import PROJECT_ROOT


def _copy_for_build(tmp_path, *extra_files):
    files = ["build_venues.py", "build_artists.py", "parser.py",
             "events.json", "venues.json", "artists.json", "cities.json",
             *extra_files]
    for name in files:
        src = PROJECT_ROOT / name
        if src.exists():
            shutil.copy(src, tmp_path / name)
    return tmp_path


def _run(tmp_path, script):
    result = subprocess.run(
        [sys.executable, script], cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"{script} упал:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _index_by_slug_and_name(records):
    by_slug = {r["slug"]: r for r in records if r.get("slug")}
    by_name = {}
    for r in records:
        if r.get("name"):
            by_name.setdefault(r["name"], r)
    return by_slug, by_name


def _find_after(rec, by_slug, by_name):
    return by_slug.get(rec["slug"]) or by_name.get(rec.get("name"))


class TestBuildVenuesPreservesManualFields:
    def test_description_lat_lon_survive_rebuild(self, tmp_path, venues, events):
        _copy_for_build(tmp_path)
        _run(tmp_path, "build_venues.py")
        after = json.loads((tmp_path / "venues.json").read_text(encoding="utf-8"))
        by_slug, by_name = _index_by_slug_and_name(after)

        ev_per_venue = {}
        for e in events:
            raw = (e.get("venue") or "").strip()
            if raw:
                ev_per_venue[raw] = ev_per_venue.get(raw, 0) + 1

        lost_description, lost_coords = [], []
        for before in venues:
            # Заведение, у которого в events.json больше нет ни одного события,
            # законно выпадает из реестра (как артисты ниже MIN_EVENTS).
            event_count = sum(
                n for name, n in ev_per_venue.items()
                if name == before.get("name") or name in before.get("aliases", [])
            )
            if event_count == 0:
                continue
            match = _find_after(before, by_slug, by_name)
            if before.get("description") and not (match and match.get("description")):
                lost_description.append(before["slug"])
            if before.get("lat") and not (match and match.get("lat")):
                lost_coords.append(before["slug"])

        assert not lost_description, (
            f"Пересборка build_venues.py стёрла описание у: {lost_description}"
        )
        assert not lost_coords, (
            f"Пересборка build_venues.py стёрла координаты у: {lost_coords}"
        )


class TestBuildArtistsPreservesManualFields:
    def test_description_survives_rebuild(self, tmp_path, artists, events):
        _copy_for_build(tmp_path)
        _run(tmp_path, "build_artists.py")
        after = json.loads((tmp_path / "artists.json").read_text(encoding="utf-8"))
        by_slug, by_name = _index_by_slug_and_name(after)

        # Порог публикации страницы артиста — MIN_EVENTS (см. build_artists.py).
        # Артист, у которого после дедупликации событий стало меньше порога,
        # законно выпадает из реестра — его описание «теряется» не по ошибке
        # пересборки, а из-за удаления дубликатов в events.json.
        from build_artists import MIN_EVENTS
        from parser import _split_artist_field
        from collections import Counter

        ev_per_artist: Counter = Counter()
        for e in events:
            if e.get("date"):
                for part in _split_artist_field(e.get("artist") or ""):
                    ev_per_artist[part.strip()] += 1

        lost_description = []
        for before in artists:
            match = _find_after(before, by_slug, by_name)
            if before.get("description") and not (match and match.get("description")):
                names = {before.get("name"), *before.get("aliases", [])}
                event_count = sum(ev_per_artist[name] for name in names)
                if event_count < MIN_EVENTS:
                    # Артист опустился ниже порога — страница намеренно снята.
                    continue
                lost_description.append(before["slug"])

        assert not lost_description, (
            f"Пересборка build_artists.py стёрла описание у: {lost_description}"
        )
