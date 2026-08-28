"""Формирует очередь ручной проверки неполных или противоречивых карточек."""

import json
import re
from pathlib import Path


EVENTS = Path("events.json")
QUEUE = Path("moderation.json")
CITY_RE = re.compile(r"\b(Симферополь|Севастополь|Ялта|Керчь|Феодосия|Судак|Гурзуф)\b", re.I)


def reasons(event: dict) -> list[str]:
    result = []
    for field, label in (("time", "нет времени"), ("venue", "нет площадки"),
                         ("price", "нет цены"), ("image", "нет постера")):
        if not event.get(field):
            result.append(label)
    city = (event.get("source_city") or "").casefold()
    mentioned = {m.group(1).casefold() for m in CITY_RE.finditer(event.get("description") or "")}
    if mentioned and city and city not in mentioned:
        result.append("город в описании не совпадает с карточкой")
    return result


def main() -> None:
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    queue = []
    for event in events:
        issues = reasons(event)
        event["needs_review"] = bool(issues)
        event["review_reasons"] = issues
        if issues:
            queue.append({
                "id": event.get("id"), "date": event.get("date"),
                "artist": event.get("artist"), "source_url": event.get("source_url"),
                "reasons": issues,
            })
    EVENTS.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Очередь модерации: {len(queue)} событий")


if __name__ == "__main__":
    main()
