import json
from datetime import date, datetime, timezone
from pathlib import Path

from source_health import (active_city_counts, build_snapshot, configured_sources,
                           coverage_by_city, parse_parser_log)


def test_daily_workflow_creates_report_and_notifies_only_about_alerts():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "parser-daily.yml").read_text(encoding="utf-8")

    assert 'python parser.py --days "$DAYS" | tee parser_output.log' in workflow
    assert "python source_health.py --log parser_output.log" in workflow
    assert "python source_health_notify.py" in workflow


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


def test_registry_keeps_source_identity_url_and_last_success(tmp_path):
    channels = tmp_path / "channels.json"
    channels.write_text(json.dumps({
        "channels": [{"username": "club", "title": "Клуб", "city": "Ялта", "type": "venue"}],
        "max_channels": [], "vk_channels": [], "instagram_channels": [],
    }), encoding="utf-8")

    configured = configured_sources(channels)
    snapshot = build_snapshot(
        configured, {"club": {"posts": 1, "extracted": 1, "accepted": 1, "merged": 0}},
        {}, {}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc), ["Ялта"],
    )

    club = snapshot["sources"]["club"]
    assert {key: club[key] for key in ("city", "type", "url", "status")} == {
        "city": "Ялта", "type": "venue", "url": "https://t.me/s/club", "status": "checked",
    }
    assert club["last_checked_at"] == club["last_successful_fetch_at"]


def test_coverage_identifies_gaps_without_enabling_candidates():
    coverage = coverage_by_city(
        {"yalta": {"city": "Ялта"}, "regional": {"city": "Крым"}},
        ["Ялта", "Керчь"],
    )

    assert coverage["Ялта"]["status"] == "covered"
    assert coverage["Керчь"]["status"] == "regional_only"


def test_coverage_alerts_only_on_regression_not_on_initial_gap():
    configured = {"regional": {"title": "Крым", "kind": "web", "city": "Крым"}}
    initial = build_snapshot(configured, {}, {}, {}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc), ["Керчь"])
    regressed = build_snapshot(configured, {}, {}, {"coverage": {"Керчь": {"status": "covered"}}}, {},
                               datetime(2026, 1, 2, tzinfo=timezone.utc), ["Керчь"])

    assert initial["coverage"]["Керчь"]["status"] == "regional_only"
    assert not any(alert.get("city") == "Керчь" for alert in initial["alerts"])
    assert regressed["alerts"][-1]["message"] == "город остался без локального источника"
