from datetime import date
from fetch_afisha_goroda import CITIES, _parse_date_time, parse_listing

HTML = '''<div class="events-elem"><img class="img" src="/poster.jpg"><div class="events-elem_content"><a class="title" href="/events/jazz">Джазовый вечер</a><div class="date date--date-start">09 сентября | 19:00</div><div class="place"><a>Дом культуры «Корабел»</a></div><div class="price">800 - 2200 ₽</div></div></div>'''


def test_parses_listing_card_with_absolute_urls():
    posts = parse_listing(HTML, "Керчь", "https://kerch.afishagoroda.ru", date(2026, 8, 30))
    assert len(posts) == 1
    assert posts[0]["_prefilled"]["date"] == "2026-09-09"
    assert posts[0]["_prefilled"]["source_url"] == "https://kerch.afishagoroda.ru/events/jazz"


def test_rolls_date_to_next_year_and_rejects_bad_date():
    assert _parse_date_time("1 января | 18:00", date(2026, 8, 30)) == ("2027-01-01", "18:00")
    assert _parse_date_time("99 января | 18:00", date(2026, 8, 30)) == (None, None)


def test_covers_all_supported_afisha_goroda_cities():
    assert {city["city"] for city in CITIES} == {
        "Симферополь", "Севастополь", "Ялта", "Алушта", "Коктебель", "Судак",
        "Керчь", "Феодосия", "Евпатория",
    }


def test_skips_standup_card():
    standup = HTML.replace("Джазовый вечер", "Андрей Атлас. Стендап")
    assert parse_listing(standup, "Евпатория", "https://evp.afishagoroda.ru", date(2026, 8, 30)) == []
