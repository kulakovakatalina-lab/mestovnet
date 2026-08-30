"""Формирует очередь ручной проверки и применяет решения из Telegram."""

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional


EVENTS = Path("events.json")
QUEUE = Path("moderation.json")
DECISIONS_CACHE = Path("moderation_decisions.json")
CITY_RE = re.compile(r"\b(Симферополь|Севастополь|Ялта|Керчь|Феодосия|Судак|Гурзуф)\b", re.I)
# Цена и постер полезны, но их отсутствие не должно останавливать публикацию:
# цена часто отсутствует у бесплатных/донатных событий, а сайт умеет показать
# аккуратную заглушку постера. Остальные неполные поля требуют решения человека.
OPTIONAL_ISSUES = {"нет цены", "нет постера"}


def load_decisions() -> Optional[list[dict]]:
    """Забирает решения модератора из Cloudflare Worker.

    None означает ошибку синхронизации. Это не то же самое, что успешный
    пустой список решений: при сбое нельзя сбрасывать локальные статусы.
    """
    base_url = os.environ.get("MODERATION_WORKER_URL", "").rstrip("/")
    token = os.environ.get("MODERATION_SYNC_TOKEN", "")
    if not base_url or not token:
        return None
    request = urllib.request.Request(
        f"{base_url}/moderation/decisions",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    # urlopen может выбросить не только URLError: например, SSL/сокетные
    # ошибки приходят как OSError, а неверный URL из переменной окружения —
    # как ValueError. Для очереди это всё один случай: синхронизация не
    # состоялась и нельзя стирать ранее известные решения.
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Не удалось получить решения модерации: {exc}")
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions", []), list):
        print("Не удалось получить решения модерации: некорректный ответ Worker")
        return None
    return payload.get("decisions", [])


def load_cached_decisions() -> list[dict]:
    """Читает последнюю успешно синхронизированную копию решений."""
    try:
        data = json.loads(DECISIONS_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_cached_decisions(decisions: list[dict]) -> bool:
    """Атомарно сохраняет снимок; ошибка кэша не отменяет решение Worker-а."""
    temporary = DECISIONS_CACHE.with_suffix(".tmp")
    try:
        temporary.write_text(
            json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(DECISIONS_CACHE)
    except OSError as exc:
        print(f"Не удалось сохранить локальный журнал модерации: {exc}")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


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


def event_fingerprint(event: dict, issues: list[str]) -> str:
    """Отпечаток версии карточки, которую проверил модератор."""
    fields = (
        "id", "date", "time", "artist", "venue", "source_city", "source_url",
        "price", "description", "event_type", "genre",
    )
    payload = {field: event.get(field) for field in fields}
    payload["reasons"] = issues
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _decision_signature(decision: dict) -> tuple:
    return (
        decision.get("event_id"), decision.get("status"),
        tuple(decision.get("reasons", [])), decision.get("decided_at", ""),
    )


def enrich_remote_decisions(
    remote: list[dict], cached: list[dict], events: list[dict]
) -> list[dict]:
    """Сохраняет fingerprint прежней версии, пока решение Worker не менялось."""
    cached_by_id = {d.get("event_id"): d for d in cached if d.get("event_id")}
    events_by_id = {e.get("id"): e for e in events if e.get("id")}
    enriched = []
    for raw in remote:
        if not isinstance(raw, dict):
            continue
        decision = dict(raw)
        event_id = decision.get("event_id")
        previous = cached_by_id.get(event_id)
        current = events_by_id.get(event_id)
        if previous and _decision_signature(previous) == _decision_signature(decision):
            fingerprint = previous.get("fingerprint")
        else:
            fingerprint = event_fingerprint(current, reasons(current)) if current else None
        if fingerprint:
            decision["fingerprint"] = fingerprint
        enriched.append(decision)
    return enriched


def decision_for(event: dict, by_id: dict, legacy_by_source: dict) -> Optional[dict]:
    """URL используется лишь для старых решений и только при одной карточке."""
    return by_id.get(event.get("id")) or legacy_by_source.get(event.get("source_url"))


def decision_embedded_in_event(event: dict) -> Optional[dict]:
    """Фолбэк для старых events.json при недоступности Worker."""
    status = event.get("moderation_status")
    if status not in {"approved", "rejected"}:
        return None
    return {
        "event_id": event.get("id"),
        "status": status,
        "reasons": event.get("moderation_decision_reasons", event.get("review_reasons", [])),
        "decided_at": event.get("moderated_at", ""),
        "fingerprint": event.get("moderation_decision_fingerprint"),
    }


def main() -> None:
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    remote_decisions = load_decisions()
    cached_decisions = load_cached_decisions()
    sync_failed = remote_decisions is None
    if sync_failed:
        decisions = cached_decisions
        print("Модерация: Worker недоступен, использую локальный журнал решений.")
    else:
        decisions = enrich_remote_decisions(remote_decisions, cached_decisions, events)
        save_cached_decisions(decisions)
    by_id = {d.get("event_id"): d for d in decisions if d.get("event_id")}
    event_url_counts: dict[str, int] = {}
    for event in events:
        url = event.get("source_url")
        if url:
            event_url_counts[url] = event_url_counts.get(url, 0) + 1
    legacy_by_source = {
        d.get("source_url"): d for d in decisions
        if d.get("source_url") and not d.get("event_id")
        and event_url_counts.get(d["source_url"]) == 1
    }
    queue = []
    for event in events:
        issues = reasons(event)
        decision = decision_for(event, by_id, legacy_by_source)
        if decision is None and sync_failed:
            decision = decision_embedded_in_event(event)
        status = (decision or {}).get("status")
        fingerprint = event_fingerprint(event, issues)

        # Одобрение действует на конкретную версию карточки. У старых данных
        # без fingerprint допускаем разовую миграцию только в офлайн-режиме.
        legacy_approved = sync_failed and decision and not decision.get("fingerprint")
        approved = status == "approved" and decision.get("reasons", []) == issues and (
            decision.get("fingerprint") == fingerprint or legacy_approved
        )
        rejected = status == "rejected"
        archived = bool(event.get("date")) and event["date"] < today
        # Однозначно сверенные изменения существующей карточки применяются
        # автоматически: это не новый LLM-кандидат, а обновление того же
        # первоисточника с сохранённым event_id.
        auto_approved = (
            bool(event.get("auto_updated"))
            or (bool(issues) and set(issues).issubset(OPTIONAL_ISSUES))
        )
        event["needs_review"] = bool(issues) and not approved and not rejected and not archived and not auto_approved
        event["review_reasons"] = issues
        if approved or rejected:
            event["moderation_status"] = status
            event["moderated_at"] = decision.get("decided_at", "")
            event["moderation_decision_reasons"] = decision.get("reasons", [])
            event["moderation_decision_fingerprint"] = fingerprint
        elif archived:
            event["moderation_status"] = "archived"
            event.pop("moderated_at", None)
            event.pop("moderation_decision_reasons", None)
            event.pop("moderation_decision_fingerprint", None)
        elif auto_approved:
            event["moderation_status"] = "approved"
            event.pop("moderated_at", None)
            event.pop("moderation_decision_reasons", None)
            event.pop("moderation_decision_fingerprint", None)
        else:
            event.pop("moderation_status", None)
            event.pop("moderated_at", None)
            event.pop("moderation_decision_reasons", None)
            event.pop("moderation_decision_fingerprint", None)
        if issues and not approved and not rejected and not archived and not auto_approved:
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
