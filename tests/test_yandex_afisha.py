"""Тесты парсера Яндекс.Афиши."""

from fetch_yandex_afisha import _parse_date_time


class TestParseDateTime:
    def test_basic(self):
        date, time = _parse_date_time("10 мая, 20:00")
        assert date is not None
        assert time == "20:00"
        assert date.endswith("-05-10")

    def test_january(self):
        date, time = _parse_date_time("15 января, 19:00")
        assert date is not None
        assert date.endswith("-01-15")
        assert time == "19:00"

    def test_december(self):
        date, time = _parse_date_time("31 декабря, 21:00")
        assert date is not None
        assert date.endswith("-12-31")
        assert time == "21:00"

    def test_invalid_format(self):
        date, time = _parse_date_time("некорректная дата")
        assert date is None
        assert time is None

    def test_empty(self):
        date, time = _parse_date_time("")
        assert date is None

    def test_future_month(self):
        date, time = _parse_date_time("1 марта, 20:00")
        assert date is not None

    def test_various_months(self):
        months = [
            ("февраля", "-02-"),
            ("марта", "-03-"),
            ("апреля", "-04-"),
            ("июня", "-06-"),
            ("июля", "-07-"),
            ("августа", "-08-"),
            ("сентября", "-09-"),
            ("октября", "-10-"),
            ("ноября", "-11-"),
        ]
        for month_name, expected in months:
            date, _ = _parse_date_time(f"5 {month_name}, 18:00")
            assert date is not None, f"Failed for month: {month_name}"
            assert expected in date, f"Expected {expected} in {date} for {month_name}"
