"""New admissions only: format rules, mixed programmes and legacy preservation."""
import copy
import json

import pytest

from live_music import classify_event
from parser import filter_new_live_music, _verify_music_excerpt, retain_existing_events


def event(**fields):
    return {"date": "2026-10-18", "time": "19:00", "artist": "Тестовый исполнитель",
            "venue": "Клуб", "source_city": "Севастополь", "genre": "поп",
            "source_url": "https://t.me/test/1", **fields}


@pytest.mark.parametrize("artist,description,action", [
    ("Ольга Воронина", "Женский Круг. Проживание энергий через Интуитивный Танец.", "ignore"),
    ("Юрий Гео", "Вводный однодневный интенсив Ecstatic-DJ.", "ignore"),
    ("Юрий Гео", "Экстатик-дэнс с Юрием Гео.", "ignore"),
    ("Евгения Сухачева", "Музыкальное рок-лото: вспоминаем любимые песни.", "ignore"),
    ("Ирина Депутович", "Игра «Угадай мелодию». Живая музыка и призы.", "ignore"),
    ("Живая музыка", "Классический квиз «Музыкальный ринг». Живая музыка.", "ignore"),
    ("Фёдор Старовойтов", "Караоке с боссом! Ведущий Фёдор Старовойтов.", "ignore"),
    ("Живая музыка", "Вечер живого пения под фонограмму (аналог каоке).", "ignore"),
    ("Halloween", "О концерте. Розыгрыш за лучший костюм. Лучшие диджеи.", "ignore"),
    ("Катя Зимцерла", "Вечер с вином и музыкой с винила.", "ignore"),
    ("Антон Дарочкин", "Stand Up концерт. Живой юмор.", "ignore"),
    ("Команда Союз", "Чемпионы КВН, большой концерт.", "ignore"),
    ("Звуки Вселенной", "Звукотерапевтический сеанс с гонгами и чашами.", "ignore"),
    ("Анна", "Медитация с флейтой и гитарой.", "ignore"),
    ("Анна", "Ритуал с живой музыкой.", "ignore"),
    ("СНИМКИ", "Группа записала новый клип «В поезде».", "ignore"),
    ("RAman", "За пультом RAman, танцуем до последнего трека.", "ignore"),
    ("Диана", "DJ‑сет с Дианой.", "ignore"),
    ("Анна (вокал), DJ", "Анна — вокал, Тимофей — DJ.", "publish"),
    ("Певица Анна", "Певица исполнит песни под инструментальную фонограмму.", "publish"),
    ("Оркестр Таева", "Караоке-концерт с живым оркестром.", "publish"),
    ("Группа ШАМ, NIRVANA TRIBUTE", "Концерт группы ШАМ. После концерта рок-караоке.", "publish"),
    ("Андрей Ясинский", "Медитативный концерт: фортепиано, ханг и флейты.", "publish"),
    ("Елена, Андрей", "До концерта джаз на виниле, затем концерт: фортепиано и голос.", "publish"),
    ("Кавер-группа Будни", "Винная маёвка. Концерт кавер-группы Будни.", "publish"),
    ("Группа Канальи", "Выступление группы Канальи и танцы средневековья.", "publish"),
    ("Ирина Круг", "Концерт Ирины Круг.", "publish"),
    ("Паша Грей", "Авторский камеди-рок и каверы в акустике.", "publish"),
    ("Иван", "Без DJ, живой саксофон.", "publish"),
    ("Оркестр", "Классическая музыка.", "publish"),
    ("Анна", "Живой электронный перформанс: синтезаторы, драм-машины и лупер.", "publish"),
    ("Сет музыканта", "Live DJ set до утра.", "review"),
    ("Живая музыка", "Гастрономический ужин, welcome drink, живая музыка.", "review"),
    ("диджей", "Гриль-вечер с живой гитарой и музыкой от диджея.", "review"),
    ("Скрипка под куполом. Концерт", "Посещение дома-музея и прогулка к телескопам.", "review"),
    ("CUPSIZE, KSB COVER SHOW", "Рок-караоке на всю ночь.", "review"),
    ("Лаунж-музыка", "Настольные игры и лаунж-музыка.", "review"),
    ("Имя", "Музыкальная атмосфера, море, закат.", "review"),
])
def test_format_rules(artist, description, action):
    assert classify_event(event(artist=artist, description=description)).action == action


def test_hardcoded_concert_type_and_model_claim_do_not_override_dj():
    candidate = event(description="DJ set до утра", event_type="концерт", live_music=True)
    assert classify_event(candidate).action == "ignore"


def test_raw_weekly_post_is_not_evidence_for_every_candidate():
    candidate = event(artist="Ведущий", description="Музыкальное лото",
                      source_excerpt="Концерт группы в пятницу", source_text="Концерт группы в пятницу")
    # Only the parser's verified private field is considered, not arbitrary LLM output.
    assert classify_event(candidate).action == "ignore"
    _verify_music_excerpt(candidate, {"text": "Музыкальное лото в понедельник"})
    assert "_live_music_source_excerpt" not in candidate
    assert "source_excerpt" not in candidate


def test_verified_excerpt_can_recover_truncated_programme():
    candidate = event(description="Особенный вечер", source_excerpt="Анна — вокал, Иван — фортепиано")
    _verify_music_excerpt(candidate, {"text": "Суббота. Анна — вокал, Иван — фортепиано. Приходите!"})
    accepted, held = filter_new_live_music([candidate], [])
    assert len(accepted) == 1 and held == []
    assert not any(key.startswith("_live_music") for key in accepted[0])


def test_no_grandfathering_entire_source_or_artist_or_untrusted_id():
    old = event(id="old", description="Женский круг")
    new_date = event(id="old", date="2026-10-19", description="Женский круг")
    other_act = event(artist="Другая ведущая", description="Квиз", time="20:00")
    before = copy.deepcopy(old)
    accepted, held = filter_new_live_music([dict(old), new_date, other_act], [old])
    assert accepted == []
    assert len(held) == 2
    assert old == before


def test_legacy_future_rows_survive_cleanup_but_source_corrections_still_apply():
    legacy = event(id="legacy", artist="Живая музыка", description="Музыкальное лото")
    cancelled = event(id="cancelled", description="Концерт группы Канальи")
    corrected = {**cancelled, "cancelled": True, "source_status": "cancelled"}
    assert retain_existing_events([legacy, cancelled], [corrected]) == [corrected, legacy]


def test_mixed_post_filters_each_event_before_deduplication():
    concert = event(artist="Группа Канальи", description="Концерт группы Канальи")
    game = event(description="Музыкальное лото", artist="Ведущая", time="18:00")
    accepted, held = filter_new_live_music([game, concert], [])
    assert accepted == [concert]
    assert held[0]["reason"] == "music_game"


def configure_run(tmp_path, monkeypatch, fresh, refreshed=()):
    import parser
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(parser, "load_channels", lambda: ([], [], [], []))
    monkeypatch.setattr(parser, "process_channels", lambda *a, **k: None)
    monkeypatch.setattr(parser, "process_yandex_afisha", lambda output, *a: output.extend(copy.deepcopy(fresh)))
    monkeypatch.setattr(parser, "process_afisha_ru", lambda *a: None)
    monkeypatch.setattr(parser, "process_afisha_goroda", lambda *a: None)
    monkeypatch.setattr(parser, "_redistribute_images", lambda *a: 0)
    monkeypatch.setattr(parser, "_drop_unpublished_image_links", lambda *a: 0)
    monkeypatch.setattr(parser, "recheck_published_telegram_sources", lambda *a: copy.deepcopy(list(refreshed)))
    monkeypatch.setattr(parser, "moscow_today", lambda: "2026-10-16")
    return parser


def test_full_run_keeps_legacy_and_blocks_new_from_all_sources(tmp_path, monkeypatch):
    legacy = event(id="old", artist="Ольга Воронина", description="Женский Круг. Интуитивный Танец.")
    fresh = [event(date="2026-10-19", description="Женский круг"),
             event(artist="Группа Канальи", description="Концерт группы Канальи", source_url="https://t.me/test/2"),
             event(artist="Живая музыка", description="Ужин с живой музыкой", source_url="https://t.me/test/3")]
    parser = configure_run(tmp_path, monkeypatch, fresh, [legacy])
    generic_legacy = event(id="generic", artist="Живая музыка", date="2026-10-20", description="Фоновая музыка")
    (tmp_path / "events.json").write_text(json.dumps([legacy, generic_legacy]))
    parser.main()
    saved = json.loads((tmp_path / "events.json").read_text())
    assert next(e for e in saved if e["id"] == "old") == legacy
    assert next(e for e in saved if e["id"] == "generic") == generic_legacy
    assert len(saved) == 3
    assert {e["artist"] for e in saved} == {"Ольга Воронина", "Группа Канальи", "Живая музыка"}
    report = json.loads((tmp_path / ".cache/live_music_report.json").read_text())
    assert {item["decision"] for item in report["candidates"]} == {"ignore", "review"}
    assert len(report["candidates"]) == 2
    assert all(item["event"].get("id") != "old" for item in report["candidates"])


def test_dry_run_does_not_write_catalogue_or_report(tmp_path, monkeypatch):
    parser = configure_run(tmp_path, monkeypatch, [event(description="DJ set")])
    original = '[ ]\n'
    (tmp_path / "events.json").write_text(original)
    assert parser.main(dry_run=True) == []
    assert (tmp_path / "events.json").read_text() == original
    assert not (tmp_path / ".cache/live_music_report.json").exists()
