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
    def test_description_lat_lon_survive_rebuild(self, tmp_path, venues):
        _copy_for_build(tmp_path)
        _run(tmp_path, "build_venues.py")
        after = json.loads((tmp_path / "venues.json").read_text(encoding="utf-8"))
        by_slug, by_name = _index_by_slug_and_name(after)

        lost_description, lost_coords = [], []
        for before in venues:
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
    def test_description_survives_rebuild(self, tmp_path, artists):
        _copy_for_build(tmp_path)
        _run(tmp_path, "build_artists.py")
        after = json.loads((tmp_path / "artists.json").read_text(encoding="utf-8"))
        by_slug, by_name = _index_by_slug_and_name(after)

        lost_description = []
        for before in artists:
            match = _find_after(before, by_slug, by_name)
            if before.get("description") and not (match and match.get("description")):
                lost_description.append(before["slug"])

        assert not lost_description, (
            f"Пересборка build_artists.py стёрла описание у: {lost_description}"
        )
