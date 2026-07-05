"""Тесты страховки от неверно угаданного года события."""

from parser import fix_event_year, _post_date_str


class TestFixEventYear:
    def test_wrong_year_two_back(self):
        # Реальный кейс из базы: пост от 2026-05-25, модель поставила 2024
        event = {"date": "2024-06-07"}
        fix_event_year(event, "2026-05-25T10:00:00+00:00")
        assert event["date"] == "2026-06-07"

    def test_wrong_year_same_day(self):
        event = {"date": "2024-05-20"}
        fix_event_year(event, "2026-05-20T10:00:00+00:00")
        assert event["date"] == "2026-05-20"

    def test_december_post_january_event(self):
        # Анонс январского концерта в декабре: год публикации не подходит — берём следующий
        event = {"date": "2026-01-15"}
        fix_event_year(event, "2026-12-20T10:00:00+00:00")
        assert event["date"] == "2027-01-15"

    def test_future_date_untouched(self):
        event = {"date": "2026-08-01"}
        fix_event_year(event, "2026-05-25T10:00:00+00:00")
        assert event["date"] == "2026-08-01"

    def test_recently_past_untouched(self):
        # Пост о только что прошедшем событии — не переносим на год вперёд
        event = {"date": "2026-05-20"}
        fix_event_year(event, "2026-05-25T10:00:00+00:00")
        assert event["date"] == "2026-05-20"

    def test_null_date(self):
        event = {"date": None}
        fix_event_year(event, "2026-05-25T10:00:00+00:00")
        assert event["date"] is None

    def test_garbage_date(self):
        event = {"date": "скоро"}
        fix_event_year(event, "2026-05-25T10:00:00+00:00")
        assert event["date"] == "скоро"

    def test_empty_post_date(self):
        event = {"date": "2024-06-07"}
        fix_event_year(event, "")
        assert event["date"] == "2024-06-07"

    def test_feb_29_to_non_leap_year(self):
        event = {"date": "2024-02-29"}
        fix_event_year(event, "2026-02-01T10:00:00+00:00")
        assert event["date"] == "2026-02-28"


class TestPostDateStr:
    def test_iso_datetime(self):
        assert _post_date_str({"date": "2026-05-25T10:00:00+00:00"}) == "2026-05-25"

    def test_missing_date(self):
        assert _post_date_str({}) == ""
