"""Неблокирующая проверка здоровья источников после запуска парсера.

Скрипт намеренно не исправляет и не удаляет карточки. Он сохраняет
снимок результата прогона и печатает предупреждения, если один из
источников не был проверен, упал или перестал приносить события, а также
если из витрины полностью исчез город. Это позволяет заметить проблему
до того, как она станет незаметной из-за архивного объединения events.json.
"""
import argparse
import html
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


DEFAULT_CHANNELS = Path("channels.json")
DEFAULT_CITIES = Path("cities.json")
DEFAULT_EVENTS = Path("events.json")
DEFAULT_SNAPSHOT = Path("source_health.json")
DEFAULT_CURRENT_EVENTS = Path("current-events/index.html")

_REPORT_LINE = re.compile(
    r"^(?P<label>.+?) \((?P<title>.*?)\): постов (?P<posts>\d+), "
    r"извлечено (?P<extracted>\d+), прошло (?P<accepted>\d+), "
    r"склеено дублей (?P<merged>\d+), отклонено (?P<rejected>.*)$"
)
_READING_LINE = re.compile(r"^Читаю (?P<label>.+?) \(")
_EXPLICIT_ANNOUNCEMENT = re.compile(r"^[ \t]*Проверить анонс: (https://t\.me/[A-Za-z0-9_]+/\d+)$", re.MULTILINE)
_SCHEDULE_SLOT = re.compile(
    r"^[ \t]*Проверить программу: (https://t\.me/([A-Za-z0-9_]+)/\d+) "
    r"(\d{4}-\d{2}-\d{2}) ([0-2]\d:[0-5]\d)$", re.MULTILINE,
)
_PUBLISHED_SOURCE = re.compile(r'href="(https://t\.me/[A-Za-z0-9_]+/\d+)"')
_PUBLISHED_EVENT = re.compile(r'href="https://mestov\.net/event/([0-9a-f]{8})"')


def missing_explicit_announcements(log_path: Optional[Path], page_path: Path) -> list[str]:
    """Находит ясные анонсы, которым не досталось строки в публичной афише."""
    if not log_path or not log_path.exists() or not page_path.exists():
        return []
    expected = set(_EXPLICIT_ANNOUNCEMENT.findall(log_path.read_text(encoding="utf-8")))
    page = html.unescape(page_path.read_text(encoding="utf-8"))
    published = set(_PUBLISHED_SOURCE.findall(page))
    return sorted(expected - published)


def missing_schedule_slots(log_path: Optional[Path], events_path: Path,
                           page_path: Path) -> list[tuple[str, str, str]]:
    """Проверяет каждую музыкальную дату программы, а не только ссылку на пост."""
    if not log_path or not log_path.exists() or not events_path.exists() or not page_path.exists():
        return []
    expected = set(_SCHEDULE_SLOT.findall(log_path.read_text(encoding="utf-8")))
    if not expected:
        return []
    try:
        events = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [(url, day, time) for url, _, day, time in sorted(expected)]
    published_ids = set(_PUBLISHED_EVENT.findall(page_path.read_text(encoding="utf-8")))
    covered = {(event.get("source_channel"), event.get("date"), event.get("time"))
               for event in events if event.get("id") in published_ids}
    return [(url, day, time) for url, channel, day, time in sorted(expected)
            if (channel, day, time) not in covered]


def _source_label(channel: dict) -> str:
    return str(channel.get("username") or channel.get("domain") or channel.get("chat_id") or "")


def _source_url(channel: dict, group_name: str) -> str:
    """Возвращает публичный адрес источника, не делая сетевых запросов."""
    if group_name == "channels":
        return f"https://t.me/s/{channel['username']}"
    if group_name == "vk_channels":
        return f"https://vk.com/{channel['domain']}"
    if group_name == "instagram_channels":
        return f"https://www.instagram.com/{channel['username']}/"
    # В MAX ссылку-приглашение иногда нельзя восстановить по username. Не
    # подменяем её догадкой: реестр должен показывать именно известный URL.
    notes = str(channel.get("notes") or "")
    match = re.search(r"https?://\S+", notes)
    return match.group(0) if match else ""


def configured_sources(channels_path: Path) -> dict[str, dict]:
    """Возвращает явный реестр включённых источников.

    Реестр строится только из уже подключённого ``channels.json``. Он не
    ищет и тем более не активирует источники из интернета.
    """
    data = json.loads(channels_path.read_text(encoding="utf-8"))
    sources = {}
    for group_name in ("channels", "max_channels", "vk_channels", "instagram_channels"):
        for channel in data.get(group_name, []):
            if channel.get("active", True) is False:
                continue
            label = _source_label(channel)
            if label:
                sources[label] = {
                    "title": channel.get("title", label),
                    "kind": group_name,
                    "city": channel.get("city", "Крым"),
                    "type": channel.get("type", "afisha"),
                    "url": _source_url(channel, group_name),
                }
    # Эти два источника вызываются parser.py без записи в channels.json.
    sources.setdefault("yandex_afisha", {
        "title": "Яндекс Афиша", "kind": "web", "city": "Крым", "type": "afisha",
        "url": "https://afisha.yandex.ru/",
    })
    sources.setdefault("afisha_ru", {
        "title": "Afisha.ru", "kind": "web", "city": "Крым", "type": "afisha",
        "url": "https://www.afisha.ru/",
    })
    sources.setdefault("afisha_goroda", {
        "title": "Афиша Города", "kind": "web", "city": "Крым", "type": "afisha",
        "url": "https://afishagoroda.ru/",
    })
    return sources


def supported_cities(cities_path: Path) -> list[str]:
    """Список городов, для которых сайт обещает отдельную афишу."""
    data = json.loads(cities_path.read_text(encoding="utf-8"))
    return [entry["name"] for entry in data if entry.get("name") != "Крым"]


def coverage_by_city(configured: dict[str, dict], cities: list[str]) -> dict[str, dict]:
    """Показывает, где есть локальный источник, а где только крымский общий.

    ``gap`` — не ошибка парсера и не повод скрывать архив. Это явный сигнал
    для ручного поиска и проверки кандидата, прежде чем добавлять его в JSON.
    """
    regional_count = sum(1 for source in configured.values() if source.get("city") == "Крым")
    result = {}
    for city in sorted(cities):
        direct = [label for label, source in configured.items() if source.get("city") == city]
        result[city] = {
            "status": "covered" if direct else ("regional_only" if regional_count else "gap"),
            "source_count": len(direct),
            "sources": direct,
            "regional_source_count": regional_count,
        }
    return result


def parse_parser_log(log_path: Optional[Path]) -> tuple[dict[str, dict], dict[str, str]]:
    """Достаёт счётчики и сетевые ошибки из штатного отчёта parser.py."""
    if not log_path or not log_path.exists():
        return {}, {}
    stats, errors = {}, {}
    current_label = None
    for raw_line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        reading = _READING_LINE.match(line)
        if reading:
            current_label = reading.group("label")
            continue
        if current_label and line.startswith("Ошибка:"):
            errors[current_label] = line.removeprefix("Ошибка:").strip()
        match = _REPORT_LINE.match(line)
        if match:
            values = match.groupdict()
            label = values.pop("label")
            values.pop("title")
            stats[label] = {key: int(value) for key, value in values.items() if key != "rejected"}
            current_label = None
    return stats, errors


def active_city_counts(events_path: Path, today: date) -> dict[str, int]:
    if not events_path.exists():
        return {}
    events = json.loads(events_path.read_text(encoding="utf-8"))
    counts = Counter()
    for event in events:
        if event.get("cancelled") or event.get("source_status") == "cancelled":
            continue
        raw_date = event.get("date") or ""
        try:
            event_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        city = event.get("source_city")
        if event_date >= today and city and city != "Крым":
            counts[city] += 1
    return dict(sorted(counts.items()))


def build_snapshot(configured: dict[str, dict], stats: dict[str, dict], errors: dict[str, str],
                   previous: dict, city_counts: dict[str, int], now: datetime,
                   coverage_cities: Optional[list[str]] = None) -> dict:
    previous_sources = previous.get("sources", {}) if previous else {}
    alerts = []
    sources = {}
    for label, meta in configured.items():
        old = previous_sources.get(label, {})
        result = {
            "title": meta["title"], "kind": meta["kind"], "city": meta.get("city", "Крым"),
            "type": meta.get("type", "afisha"), "url": meta.get("url", ""),
            "last_checked_at": now.astimezone(timezone.utc).isoformat(),
        }
        if label in errors:
            result.update({"status": "error", "error": errors[label]})
            alerts.append({"level": "error", "source": label, "message": "источник недоступен"})
        elif label not in stats:
            result["status"] = "not_checked"
            alerts.append({"level": "warning", "source": label, "message": "источник не проверен"})
        else:
            result.update({"status": "checked", **stats[label]})
            result["last_successful_fetch_at"] = now.astimezone(timezone.utc).isoformat()
            zero_runs = int(old.get("consecutive_zero_extractions", 0)) + 1 if result["extracted"] == 0 else 0
            result["consecutive_zero_extractions"] = zero_runs
            if zero_runs >= 2 and int(old.get("extracted", 0)) > 0:
                alerts.append({"level": "warning", "source": label,
                               "message": f"нет извлечённых событий {zero_runs} запуска подряд"})
        sources[label] = result

    coverage = coverage_by_city(configured, coverage_cities or [])
    old_coverage = previous.get("coverage", {}) if previous else {}
    # О постоянных пробелах не спамим ежедневно. Уведомление создаётся только
    # при регрессии: город был покрыт отдельным источником и перестал быть им.
    for city, state in coverage.items():
        if old_coverage.get(city, {}).get("status") == "covered" and state["status"] != "covered":
            alerts.append({"level": "warning", "city": city,
                           "message": "город остался без локального источника"})

    old_cities = previous.get("cities", {}) if previous else {}
    for city, old_count in old_cities.items():
        if old_count and not city_counts.get(city):
            alerts.append({"level": "warning", "city": city,
                           "message": "все будущие события города исчезли из витрины"})

    return {
        "version": 2,
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "sources": sources,
        "cities": city_counts,
        "coverage": coverage,
        "alerts": alerts,
    }


def _load_snapshot(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_snapshot(path: Path, snapshot: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    argp = argparse.ArgumentParser(description="Проверить здоровье источников после parser.py")
    argp.add_argument("--log", type=Path, help="Лог текущего запуска parser.py")
    argp.add_argument("--channels", type=Path, default=DEFAULT_CHANNELS)
    argp.add_argument("--cities", type=Path, default=DEFAULT_CITIES)
    argp.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    argp.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    argp.add_argument("--current-events", type=Path, default=DEFAULT_CURRENT_EVENTS)
    argp.add_argument("--today", type=date.fromisoformat,
                      default=datetime.now(ZoneInfo("Europe/Moscow")).date(),
                      help="YYYY-MM-DD; для проверки")
    args = argp.parse_args()

    stats, errors = parse_parser_log(args.log)
    snapshot = build_snapshot(configured_sources(args.channels), stats, errors,
                              _load_snapshot(args.snapshot), active_city_counts(args.events, args.today),
                              datetime.now(timezone.utc), supported_cities(args.cities))
    for url in missing_explicit_announcements(args.log, args.current_events):
        snapshot["alerts"].append({
            "level": "warning", "source": url,
            "message": "концерт из поста не опубликован в актуальной афише",
        })
    for url, day, time in missing_schedule_slots(args.log, args.events, args.current_events):
        snapshot["alerts"].append({
            "level": "warning", "source": url,
            "message": f"музыкальное событие {day} в {time} из программы не опубликовано",
        })
    save_snapshot(args.snapshot, snapshot)
    print(f"=== Контроль источников: {len(snapshot['sources'])} ===")
    for alert in snapshot["alerts"]:
        subject = alert.get("source") or alert.get("city")
        print(f"⚠️  {subject}: {alert['message']}")
    if not snapshot["alerts"]:
        print("✓ Отклонений не обнаружено")
    # Предупреждения не прерывают ежедневную публикацию: это наблюдаемость,
    # а не причина скрыть уже проверенные карточки.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
