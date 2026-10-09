"""Защита от пропуска ясного концертного анонса в батче и на сайте."""

import json

import parser
from source_health import missing_explicit_announcements, missing_schedule_slots, unmatched_posters


POST = {
    "url": "https://t.me/artcafesnezhinka/2040",
    "date": "2026-10-02T19:59:32+00:00",
    "text": (
        "3 октября в субботу в 19:00 арт-кафе «Снежинка» приглашает "
        "на концерт «Музыкальный городок» — трибьют Леонида Агутина "
        "и Анжелики Варум."
    ),
    "image": None,
    "images": None,
}
CHANNEL = {"username": "artcafesnezhinka", "title": "Арт-кафе «Снежинка»",
           "city": "Севастополь", "type": "venue"}
WEEKLY_POST = {
    "url": "https://t.me/artcafesnezhinka/2034",
    "date": "2026-09-29T11:59:33+00:00",
    "text": (
        "1 октября | 20:00\nКино на стене — «Вам письмо»\n"
        "2 октября | 19:00\nParanormal Jazz Trio — новая программа\n"
        "3 октября | 19:00\n«Музыкальный городок» — трибьют Леонида Агутина и Анжелики Варум\n"
        "4 октября | 19:00\nPiano Battle. Концерт-перформанс двух пианистов\n"
        "7 октября | 18:30\nБеседы об искусстве с Ольгой Щукиной"
    ),
    "images": ["first", "second"],
}
LIVADIA_POST = {
    "url": "https://t.me/dlyadushi_Crimea/6617",
    "date": "2026-10-07T20:45:48+00:00",
    "text": (
        "КОНЦЕРТЫ В ОРГАННОМ ЗАЛЕ LIVADIA\n"
        "РАСПИСАНИЕ КОНЦЕРТОВ НА ОКТЯБРЬ\n"
        "Вторник\n1️⃣3️⃣.1️⃣0️⃣\n2️⃣0️⃣.1️⃣0️⃣\n2️⃣7️⃣.1️⃣0️⃣\n🕰️ Начало в 16:30\n"
        "Четверг\n0️⃣8️⃣.1️⃣0️⃣\n1️⃣5️⃣.1️⃣0️⃣\n2️⃣2️⃣.1️⃣0️⃣\n2️⃣9️⃣.1️⃣0️⃣\n🕰️ Начало в 16:30\n"
        "Суббота\n1️⃣0️⃣.1️⃣0️⃣\n1️⃣7️⃣.1️⃣0️⃣\n2️⃣4️⃣.1️⃣0️⃣\n3️⃣1️⃣.1️⃣0️⃣\n🕰️ Начало в 17:00\n"
        "Воскресенье\n1️⃣1️⃣.1️⃣0️⃣\n1️⃣8️⃣.1️⃣0️⃣\n2️⃣5️⃣.1️⃣0️⃣\n🕰️ Начало в 14:30\n"
    ),
    "images": ["first", "second"],
}


def test_weekly_sections_include_music_and_exclude_cinema_and_lecture():
    sections = parser._schedule_music_sections(WEEKLY_POST, today="2026-09-29")
    assert [(section["date"], section["time"]) for section in sections] == [
        ("2026-10-02", "19:00"),
        ("2026-10-03", "19:00"),
        ("2026-10-04", "19:00"),
    ]


def test_livadia_weekday_blocks_assign_time_to_their_own_dates():
    slots = parser._weekday_schedule_slots(LIVADIA_POST)
    assert slots["2026-10-15"] == {"16:30"}
    assert slots["2026-10-18"] == {"14:30"}
    assert "14:30" not in slots["2026-10-15"]


def test_livadia_extraction_corrects_false_second_show(monkeypatch):
    monkeypatch.setattr(parser, "download_image", lambda url: None)
    monkeypatch.setattr(parser, "extract_events_multi", lambda post, channel, images: [
        {"date": "2026-10-15", "time": "14:30", "artist": "Юлия, Антон Хромченко",
         "venue": "Органный зал Livadia"},
        {"date": "2026-10-15", "time": "16:30", "artist": "Юлия, Антон Хромченко",
         "venue": "Органный зал Livadia"},
    ])
    events = []
    parser.process_channels(
        [{"username": "dlyadushi_Crimea", "title": "Для души | Крым",
          "city": "Крым", "type": "afisha"}],
        events, lambda channel: [LIVADIA_POST],
    )
    assert [event["time"] for event in events] == ["16:30", "16:30"]
    assert len(parser.deduplicate_events(events)) == 1


def test_explicit_future_concert_excludes_recaps_and_cancellations():
    assert parser._explicit_future_concert(POST, today="2026-10-03")
    assert not parser._explicit_future_concert(POST, today="2026-10-04")
    assert not parser._explicit_future_concert({**POST, "text": "Концерт отменён 3 октября в 19:00"},
                                                today="2026-10-03")


def test_missed_batch_post_is_retried_individually(monkeypatch):
    monkeypatch.setattr(parser, "moscow_today", lambda: "2026-10-03")
    monkeypatch.setattr(parser, "_download_all_images", lambda posts: {})
    monkeypatch.setattr(parser, "extract_events_batch", lambda posts, channel: {})
    monkeypatch.setattr(parser, "extract_events_single", lambda post, channel, image: [
        {"date": "2026-10-03", "time": "19:00", "artist": "Трибьют Леонида Агутина и Анжелики Варум"}
    ])
    events = []
    parser.process_channels([CHANNEL], events, lambda channel: [POST])
    assert len(events) == 1
    assert events[0]["source_url"] == POST["url"]


def test_multi_image_announcement_survives_image_download_failure(monkeypatch):
    monkeypatch.setattr(parser, "moscow_today", lambda: "2026-10-03")
    monkeypatch.setattr(parser, "download_image", lambda url: None)
    monkeypatch.setattr(parser, "extract_events_multi", lambda post, channel, images: [
        {"date": "2026-10-03", "artist": "Трибьют"}
    ])
    events = []
    parser.process_channels([CHANNEL], events, lambda channel: [{**POST, "images": ["a", "b"]}])
    assert len(events) == 1
    assert events[0]["source_url"] == POST["url"]
    assert events[0]["image"] is None


def test_publication_check_finds_missing_source(tmp_path):
    log = tmp_path / "parser.log"
    page = tmp_path / "current-events.html"
    log.write_text(f"  Проверить анонс: {POST['url']}\n", encoding="utf-8")
    page.write_text("<table><tr><td>Другой концерт</td></tr></table>", encoding="utf-8")
    assert missing_explicit_announcements(log, page) == [POST["url"]]
    page.write_text(f'<a href="{POST["url"]}">Источник</a>', encoding="utf-8")
    assert missing_explicit_announcements(log, page) == []


def test_weekly_schedule_retries_each_missing_music_event(monkeypatch):
    monkeypatch.setattr(parser, "moscow_today", lambda: "2026-10-03")
    monkeypatch.setattr(parser, "download_image", lambda url: None)
    monkeypatch.setattr(parser, "extract_events_multi", lambda post, channel, images: (_ for _ in ()).throw(
        AssertionError("Нельзя смешивать текст разных пунктов программы")
    ))

    def extract_section(post, channel, image):
        return [{"date": "2026-10-03", "artist": "Трибьют"}] if "Музыкальный городок" in post["text"] else [
            {"date": "2026-10-04", "artist": "Piano Battle"}
        ]

    monkeypatch.setattr(parser, "extract_events_single", extract_section)
    events = []
    parser.process_channels([CHANNEL], events, lambda channel: [WEEKLY_POST])
    assert [(e["date"], e["time"], e["artist"]) for e in events] == [
        ("2026-10-03", "19:00", "Трибьют"),
        ("2026-10-04", "19:00", "Piano Battle"),
    ]
    assert all(e["source_url"] == WEEKLY_POST["url"] for e in events)


def test_weekly_schedule_retries_only_missing_date(monkeypatch):
    sections = parser._schedule_music_sections(WEEKLY_POST, today="2026-10-03")
    retried = []

    def extract_section(post, channel, image):
        retried.append(post["text"])
        return [{"date": "2026-10-04", "artist": "Piano Battle"}]

    monkeypatch.setattr(parser, "extract_events_single", extract_section)
    events = parser._recover_schedule_events(
        WEEKLY_POST, CHANNEL, [{"date": "2026-10-03", "time": "19:00", "artist": "Трибьют"}],
        sections, "",
    )
    assert len(retried) == 1 and "Piano Battle" in retried[0]
    assert [(e["date"], e["time"]) for e in events] == [
        ("2026-10-03", "19:00"), ("2026-10-04", "19:00"),
    ]


def test_publication_check_catches_missing_date_inside_weekly_post(tmp_path):
    log = tmp_path / "parser.log"
    data = tmp_path / "events.json"
    page = tmp_path / "current-events.html"
    url = WEEKLY_POST["url"]
    log.write_text(f"Проверить программу: {url} 2026-10-03 19:00\n"
                   f"Проверить программу: {url} 2026-10-04 19:00\n", encoding="utf-8")
    data.write_text(json.dumps([{"id": "934974ea", "source_channel": "artcafesnezhinka",
                                 "date": "2026-10-03", "time": "19:00"}]), encoding="utf-8")
    page.write_text('<a href="https://mestov.net/event/934974ea">Трибьют</a>', encoding="utf-8")
    assert missing_schedule_slots(log, data, page) == [(url, "2026-10-04", "19:00")]
    data.write_text(json.dumps([{"id": "934974ea", "source_channel": "artcafesnezhinka",
                                 "date": "2026-10-03", "time": "19:00"},
                                {"id": "1234abcd", "source_channel": "artcafesnezhinka",
                                 "date": "2026-10-04", "time": "19:00"}]), encoding="utf-8")
    page.write_text(page.read_text() + '<a href="https://mestov.net/event/1234abcd">Piano Battle</a>',
                    encoding="utf-8")
    assert missing_schedule_slots(log, data, page) == []


def test_unmatched_weekly_poster_is_reported(tmp_path):
    log = tmp_path / "parser.log"
    log.write_text("  Не сопоставлен постер: https://t.me/artcafesnezhinka/2034 "
                   "2026-10-04 Piano Battle\n", encoding="utf-8")
    assert unmatched_posters(log) == [
        ("https://t.me/artcafesnezhinka/2034", "2026-10-04", "Piano Battle")
    ]
