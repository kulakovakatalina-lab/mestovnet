"""Защита от пропуска ясного концертного анонса в батче и на сайте."""

import parser
from source_health import missing_explicit_announcements


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
