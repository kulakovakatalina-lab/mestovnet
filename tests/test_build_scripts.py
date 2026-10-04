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


def test_black_sea_venue_variants_merge_on_rebuild(tmp_path, events):
    _copy_for_build(tmp_path)
    _run(tmp_path, "build_venues.py")
    venues = json.loads((tmp_path / "venues.json").read_text(encoding="utf-8"))
    by_slug = {venue["slug"]: venue for venue in venues}
    assert "resto-bar-u-chernogo-morya" not in by_slug
    canonical = by_slug["restoran-u-chernogo-morya"]
    variants = {
        "Ресторан 'У Чёрного моря'",
        "Ресторан «У Чёрного моря»",
        "Ресто-бар «У Чёрного моря»",
    }
    assert variants <= set(canonical["aliases"])
    assert canonical["event_count"] == sum(
        event.get("venue") in variants for event in events
    )
    assert (canonical["lat"], canonical["lon"]) == (44.614484, 33.525136)


class TestBuildArtistsPreservesManualFields:
    @pytest.mark.parametrize("variant", [
        "Группа Маяк. Хиты группы Пламя",
        "Маяк. Хиты группы Пламя",
        "Маяк. Хиты Пламя",
        "Маяк. Хиты группой Пламя",
    ])
    def test_group_word_forms_do_not_change_artist_key(self, variant):
        from build_artists import norm_key

        assert norm_key(variant) == norm_key("Маяк. Хиты Пламя")
        assert norm_key("Группировка") != norm_key("ировка")

    def test_new_artist_program_titles_share_one_page(self, tmp_path, monkeypatch):
        import build_artists

        monkeypatch.setattr(build_artists, "EVENTS_FILE", tmp_path / "events.json")
        monkeypatch.setattr(build_artists, "VENUES_FILE", tmp_path / "venues.json")
        monkeypatch.setattr(build_artists, "OUT_FILE", tmp_path / "artists.json")
        variants = ["Группа Маяк. Хиты группы Пламя", "Маяк. Хиты Пламя"]
        events = [
            {"artist": title, "date": f"2026-10-{23 + i}"}
            for i, title in enumerate(variants)
        ]
        (tmp_path / "events.json").write_text(
            json.dumps(events, ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / "venues.json").write_text("[]", encoding="utf-8")
        (tmp_path / "artists.json").write_text("[]", encoding="utf-8")

        build_artists.main()
        artists = json.loads((tmp_path / "artists.json").read_text(encoding="utf-8"))

        assert len(artists) == 1
        assert artists[0]["slug"] == "mayak-hity-plamya"
        assert artists[0]["event_count"] == 2
        assert set(variants) == set(artists[0]["aliases"])

    def test_existing_group_page_keeps_its_address(self, tmp_path, monkeypatch):
        import build_artists

        monkeypatch.setattr(build_artists, "EVENTS_FILE", tmp_path / "events.json")
        monkeypatch.setattr(build_artists, "VENUES_FILE", tmp_path / "venues.json")
        monkeypatch.setattr(build_artists, "OUT_FILE", tmp_path / "artists.json")
        old_name = "Группа Маяк. Хиты группы Пламя"
        new_name = "Маяк. Хиты Пламя"
        (tmp_path / "events.json").write_text(json.dumps([
            {"artist": new_name, "date": "2026-10-24"},
            {"artist": new_name, "date": "2026-10-25"},
        ], ensure_ascii=False), encoding="utf-8")
        (tmp_path / "venues.json").write_text("[]", encoding="utf-8")
        (tmp_path / "artists.json").write_text(json.dumps([{
            "slug": "gruppa-mayak-hity-gruppy-plamya",
            "name": old_name,
            "aliases": [old_name],
            "event_count": 1,
        }], ensure_ascii=False), encoding="utf-8")

        build_artists.main()
        artists = json.loads((tmp_path / "artists.json").read_text(encoding="utf-8"))

        assert len(artists) == 1
        assert artists[0]["slug"] == "gruppa-mayak-hity-gruppy-plamya"

    def test_jawa_program_titles_share_one_artist(self, tmp_path, monkeypatch):
        import build_artists

        monkeypatch.setattr(build_artists, "EVENTS_FILE", tmp_path / "events.json")
        monkeypatch.setattr(build_artists, "VENUES_FILE", tmp_path / "venues.json")
        monkeypatch.setattr(build_artists, "OUT_FILE", tmp_path / "artists.json")
        variants = [
            "Jawa. Хиты «Сектор Газа»",
            "Группа Jawa. Хиты группы «Сектор Газа»",
        ]
        events = [
            {"artist": title, "date": f"2026-10-{23 + i}", "source_city": "Симферополь"}
            for i, title in enumerate(variants)
        ]
        (tmp_path / "events.json").write_text(
            json.dumps(events, ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / "venues.json").write_text("[]", encoding="utf-8")
        (tmp_path / "artists.json").write_text("[]", encoding="utf-8")

        build_artists.main()
        artists = json.loads((tmp_path / "artists.json").read_text(encoding="utf-8"))

        assert len(artists) == 1
        assert artists[0]["slug"] == "jawa"
        assert artists[0]["event_count"] == 2
        assert set(variants) <= set(artists[0]["aliases"])

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
