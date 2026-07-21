"""Проверки вёрстки в реальном браузере (headless Chromium через Playwright).

Осознанно не делаем pixel-diff со скриншотом-эталоном: контент (даты, число
событий, картинки) меняется каждый день, pixel-diff будет ложно падать почти
на каждом прогоне. Вместо этого проверяем структурные признаки поломки
вёрстки — горизонтальный скролл, ошибки в консоли, отсутствие ключевых
элементов — они не зависят от того, что именно сегодня в афише.
"""
import socket
import subprocess
import sys
import time
from contextlib import closing

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800},
    "mobile": {"width": 390, "height": 844},
}

# Допуск на скролл (px) — не считаем поломкой, если контент шире вьюпорта
# на пару пикселей (субпиксельное округление браузера).
OVERFLOW_TOLERANCE_PX = 4

# Известные исключения из строгой проверки переполнения на мобильном
# (ratchet, см. tests/conftest.py). Пусто — переполнение вёрстки не
# считается допустимым ни на одной странице.
KNOWN_MOBILE_OVERFLOW_PAGES = set()

ARTIFACTS_DIR_NAME = "artifacts"


def _free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(project_root):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "preview_server.py", str(port)],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://localhost:{port}"
    deadline = time.time() + 10
    connected = False
    while time.time() < deadline:
        # Каждая попытка — новый socket: на macOS повторный connect() на том
        # же объекте после неудачи падает с "already connected", а не с
        # обычным ConnectionRefusedError.
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
                connected = True
                break
            except OSError:
                time.sleep(0.1)
    if not connected:
        proc.terminate()
        pytest.fail("Локальный preview-сервер не поднялся за 10 секунд")
    yield base_url
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def _pages_to_check(sample_event, sample_venue, sample_city):
    return {
        "home": "/",
        "event": f"/event/{sample_event['id']}",
        "venue": f"/venues/{sample_venue['slug']}",
        "city": f"/cities/{sample_city['slug']}.html",
        "map": "/map.html",
        "404": "/404.html",
    }


class TestLayout:
    @pytest.mark.parametrize("viewport_name", list(VIEWPORTS.keys()))
    def test_pages_render_without_layout_breakage(
        self, live_server, browser, sample_event, sample_venue, sample_city,
        project_root, viewport_name,
    ):
        viewport = VIEWPORTS[viewport_name]
        page = browser.new_page(viewport=viewport)

        # Настоящие баги JS — необработанные исключения, а не сетевые
        # ошибки подгрузки ресурсов (те слишком зависят от окружения:
        # блокировщики рекламы, sandboxed CI без доступа к mc.yandex.ru
        # и т.п. — недогрузившийся счётчик метрики не ломает вёрстку).
        js_errors = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))

        failures = []
        artifacts_dir = project_root / "tests" / ARTIFACTS_DIR_NAME
        for name, path in _pages_to_check(sample_event, sample_venue, sample_city).items():
            js_errors.clear()
            page.goto(f"{live_server}{path}", wait_until="networkidle")

            body_text = page.inner_text("body").lower()
            if "местов" not in body_text:
                failures.append(f"{name}: страница не содержит текста «местов» — похоже, пустая/сломанная")

            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            is_known_overflow = viewport_name == "mobile" and name in KNOWN_MOBILE_OVERFLOW_PAGES
            if scroll_width > viewport["width"] + OVERFLOW_TOLERANCE_PX and not is_known_overflow:
                failures.append(
                    f"{name}: горизонтальное переполнение "
                    f"({scroll_width}px > {viewport['width']}px) — вёрстка поехала"
                )
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts_dir / f"overflow-{viewport_name}-{name}.png"), full_page=True)

            if js_errors:
                failures.append(f"{name}: необработанные ошибки JS: {js_errors}")

            if name != "404" and not page.locator("nav.nav").count():
                failures.append(f"{name}: не найдена навигация nav.nav")

        page.close()
        assert not failures, "\n".join(failures)

    def test_event_pages_have_at_least_one_card_when_events_exist(
        self, live_server, browser, upcoming_events,
    ):
        if not upcoming_events:
            pytest.skip("Нет предстоящих событий — проверять карточки нечем")
        page = browser.new_page(viewport=VIEWPORTS["desktop"])
        page.goto(f"{live_server}/", wait_until="networkidle")
        card_count = page.locator(".card").count()
        page.close()
        assert card_count > 0, "На главной нет ни одной карточки события, хотя события есть в events.json"
