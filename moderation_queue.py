"""Формирует очередь ручной проверки и применяет решения из Telegram."""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


EVENTS = Path("events.json")
QUEUE = Path("moderation.json")
CITY_RE = re.compile(r"\b(Симферополь|Севастополь|Ялта|Керчь|Феодосия|Судак|Гурзуф)\b", re.I)


def load_decisions() -> list[dict]:
    """Забирает решения модератора из Cloudflare Worker.

    Без настроек Worker скрипт остаётся полностью локальным: новые карточки
    попадают в очередь как прежде. Это удобно для локальной разработки.
    """
    base_url = os.environ.get("MODERATION_WORKER_URL", "").rstrip("/")
    token = os.environ.get("MODERATION_SYNC_TOKEN", "")
    if not base_url or not token:
        return []
    request = urllib.request.Request(
        f"{base_url}/moderation/decisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Не удалось получить решения модерации: {exc}")
        return []
    return payload.get("decisions", []) if isinstance(payload, dict) else []


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


def decision_for(event: dict, by_id: dict, by_source: dict) -> Optional[dict]:
    return by_id.get(event.get("id")) or by_source.get(event.get("source_url"))


def main() -> None:
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    decisions = load_decisions()
    by_id = {d.get("event_id"): d for d in decisions if d.get("event_id")}
    by_source = {d.get("source_url"): d for d in decisions if d.get("source_url")}
    queue = []
    for event in events:
        issues = reasons(event)
        decision = decision_for(event, by_id, by_source)
        status = (decision or {}).get("status")

        # Одобрение действует на тот набор замечаний, который видел
        # модератор. Если парсер нашёл новую проблему, карточка вернётся
        # в очередь, а не будет опубликована по старому решению.
        approved = status == "approved" and decision.get("reasons", []) == issues
        rejected = status == "rejected"
        event["needs_review"] = bool(issues) and not approved and not rejected
        event["review_reasons"] = issues
        if approved or rejected:
            event["moderation_status"] = status
            event["moderated_at"] = decision.get("decided_at", "")
        else:
            event.pop("moderation_status", None)
            event.pop("moderated_at", None)
        if issues and not approved and not rejected:
            queue.append({
                # В очередь кладём именно те данные, которые увидит посетитель
                # сайта. Telegram-бот показывает эту карточку модератору до
                # публикации, включая постер и полное описание.
                "id": event.get("id"),
                "date": event.get("date"),
                "time": event.get("time"),
                "artist": event.get("artist"),
                "venue": event.get("venue"),
                "source_city": event.get("source_city"),
                "price": event.get("price"),
                "genre": event.get("genre"),
                "event_type": event.get("event_type"),
                "description": event.get("description"),
                "image": event.get("image"),
                "source_url": event.get("source_url"),
                "reasons": issues,
            })
    EVENTS.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Очередь модерации: {len(queue)} событий")


if __name__ == "__main__":
    main()
