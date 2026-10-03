from bs4 import BeautifulSoup
from pathlib import Path

from generate_pages import make_current_events_page


def test_current_events_page_shows_image_and_source_link():
    page = make_current_events_page([
        {"id": "deadbeef", "date": "2999-01-01", "time": "19:00", "venue": "Клуб",
         "source_city": "Ялта", "artist": "Артист", "image": "/images/events/poster.jpg",
         "source_url": "https://example.test/post"},
    ], "2999-01-01", "")
    soup = BeautifulSoup(page, "html.parser")

    assert soup.find("img")["src"] == "../images/events/poster.jpg"
    assert soup.find("a", string="Источник")["href"] == "https://example.test/post"
    assert soup.find("a", string="Артист")["href"] == "https://mestov.net/event/deadbeef"


def test_home_and_city_load_published_catalog_first():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "index.html", root / "cities/sevastopol.html"):
        page = path.read_text(encoding="utf-8")
        assert page.index("fetch('/events.json')") < page.index("fetch('https://mestov-bot.")
        assert "fetch('/settings.json')" in page
        assert "fetch('/cities.json')" in page
