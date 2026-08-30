import json
from datetime import date, datetime, timezone

from source_health import active_city_counts, build_snapshot, parse_parser_log


def test_parse_log_marks_fetch_error_and_keeps_report_counts(tmp_path):
    log = tmp_path / "parser.log"
    log.write_text(
        "Читаю broken (Broken Club)...\n  Ошибка: 503 Service Unavailable\n"
        "good (Good Club): постов 4, извлечено 2, прошло 2, склеено дублей 0, отклонено 0\n",
        encoding="utf-8",
    )

    stats, errors = parse_parser_log(log)

    assert stats["good"] == {"posts": 4, "extracted": 2, "accepted": 2, "merged": 0}
    assert errors == {"broken": "503 Service Unavailable"}


def test_snapshot_alerts_for_error_and_repeated_empty_source():
    configured = {"broken": {"title": "Broken", "kind": "channels"},
                  "quiet": {"title": "Quiet", "kind": "channels"}}
    previous = {"sources": {"quiet": {"extracted": 3, "consecutive_zero_extractions": 1}},
                "cities": {"Ялта": 2}}

    snapshot = build_snapshot(
        configured, {"quiet": {"posts": 2, "extracted": 0, "accepted": 0, "merged": 0}},
        {"broken": "timeout"}, previous, {}, datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert snapshot["sources"]["broken"]["status"] == "error"
    assert snapshot["sources"]["quiet"]["consecutive_zero_extractions"] == 2
    assert {alert["message"] for alert in snapshot["alerts"]} == {
        "источник недоступен", "нет извлечённых событий 2 запуска подряд",
        "все будущие события города исчезли из витрины",
    }


def test_active_city_counts_skips_past_and_cancelled_events(tmp_path):
    events = tmp_path / "events.json"
    events.write_text(json.dumps([
        {"date": "2026-02-02", "source_city": "Ялта"},
        {"date": "2026-02-02", "source_city": "Севастополь", "cancelled": True},
        {"date": "2026-01-01", "source_city": "Ялта"},
        {"date": "not-a-date", "source_city": "Керчь"},
    ]), encoding="utf-8")

    assert active_city_counts(events, date(2026, 2, 1)) == {"Ялта": 1}
