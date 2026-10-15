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

from generate_pages import event_meta, load_venues, load_artists
from parser import is_placeholder_title, _GENERIC_ARTIST_LITERALS

EVENTS = Path("events.json")
QUEUE = Path("moderation.json")
DECISIONS_CACHE = Path("moderation_decisions.json")
SETTINGS = Path("settings.json")
CITY_RE = re.compile(r"\b(Симферополь|Севастополь|Ялта|Керчь|Феодосия|Судак|Гурзуф)\b", re.I)
# Цена и постер полезны, но их отсутствие не должно останавливать публикацию:
# цена часто отсутствует у бесплатных/донатных событий, а сайт умеет показать
# аккуратную заглушку постера. Остальные неполные поля требуют решения человека.
OPTIONAL_ISSUES = {"нет цены", "нет постера"}
SEO_COLLISION = "дубли мета-тегов: совпадают title и description"
SCHEDULE_CONFLICT = "разные исполнители на одной площадке в одно время"


def _schedule_name(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold().replace("ё", "е"))


def _schedule_venue(value: str, city: str) -> str:
    name = _schedule_name(value)
    return name.replace(city, "") if city else name


def schedule_conflicts(events: list[dict], settings: dict, rejected_ids=()) -> dict[str, list[dict]]:
    """Сравнивает будущие сеансы после ручных правок; не выбирает победителя."""
    today = date.today().isoformat()
    hidden = set(settings.get("hidden", [])) | set(settings.get("cancelled", []))
    venue_aliases = {}
    for venue in load_venues():
        city = _schedule_name(venue.get("city") or "")
        # Город в скобках/после запятой не создаёт отдельную площадку.
        canonical = _schedule_venue(venue["name"], city)
        for alias in [venue["name"], *venue.get("aliases", [])]:
            venue_aliases[(city, _schedule_venue(alias, city))] = canonical
    artist_aliases = {}
    for artist in load_artists():
        for alias in [artist["name"], *artist.get("aliases", [])]:
            artist_aliases[_schedule_name(alias)] = _schedule_name(artist["name"])
    generic_artists = {_schedule_name(name) for name in
                       _GENERIC_ARTIST_LITERALS | {"Живая музыка", "DJ", "диджей"}}
    slots = {}
    for original in events:
        event = dict(original)
        url = event.get("source_url") or ""
        if (not event.get("id") or str(event["id"]) in rejected_ids or url in hidden
                or event.get("cancelled") or event.get("source_status") == "cancelled"
                or (event.get("date") or "") < today):
            continue
        for setting, field in (("names", "artist"), ("venues", "venue"),
                               ("cities", "source_city"), ("times", "time")):
            if url in settings.get(setting, {}):
                event[field] = settings[setting][url]
        city = _schedule_name(event.get("source_city") or "")
        venue = _schedule_venue(event.get("venue") or "", city)
        venue = venue_aliases.get((city, venue), venue)
        artist = _schedule_name(event.get("artist") or "")
        if (not city or not venue or not artist or artist in generic_artists
                or is_placeholder_title(event.get("artist"))):
            continue
        match = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", event.get("time") or "")
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            continue
        time = f"{int(match[1]):02d}:{match[2]}"
        key = (city, venue, event["date"], time)
        slots.setdefault(key, []).append((event, artist_aliases.get(artist, artist)))
    conflicts = {}
    for group in slots.values():
        for event, artist in group:
            peers = [other for other, other_artist in group
                     if other["id"] != event["id"] and artist != other_artist]
            if peers:
                conflicts[str(event["id"])] = sorted(peers, key=lambda e: str(e["id"]))
    return conflicts


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
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "MestovNet-Moderation-Sync/1.0",
        },
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
    if is_placeholder_title(event.get("artist")):
        result.append("нет названия")
    for field, label in (("time", "нет времени"), ("venue", "нет площадки"),
                         ("price", "нет цены"), ("image", "нет постера")):
        if not event.get(field):
            result.append(label)
    city = (event.get("source_city") or "").casefold()
    mentioned = {m.group(1).casefold() for m in CITY_RE.finditer(event.get("description") or "")}
    if mentioned and city and city not in mentioned:
        result.append("город в описании не совпадает с карточкой")
    return result


def seo_collision_ids(events: list[dict], custom_names: dict[str, str], settings: dict) -> set[str]:
    """Находит карточки, которые дали бы одинаковые title и description.

    Оставляем одну наиболее заполненную карточку. Остальные не удаляем: они
    поступают в обычную очередь модерации с явной причиной, чтобы человек мог
    сравнить первоисточники и отклонить дубль или исправить данные.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for event in events:
        if not event.get("id"):
            continue
        rendered = dict(event)
        url = event.get("source_url") or ""
        if url in settings.get("venues", {}):
            rendered["venue"] = settings["venues"][url]
        if url in settings.get("cities", {}):
            rendered["source_city"] = settings["cities"][url]
        groups.setdefault(event_meta(rendered, custom_names), []).append(event)

    collision_ids: set[str] = set()
    fields = ("artist", "venue", "source_city", "date", "time", "price", "description", "image")
    for group in groups.values():
        if len(group) < 2:
            continue
        keeper = max(group, key=lambda event: (
            sum(bool(event.get(field)) for field in fields), str(event.get("id")),
        ))
        collision_ids.update(str(event["id"]) for event in group if event is not keeper)
    return collision_ids


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
    remote: list[dict], cached: list[dict], events: list[dict], event_issues=None
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
            issues = (event_issues or {}).get(str(event_id), reasons(current)) if current else []
            fingerprint = event_fingerprint(current, issues) if current else None
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
    settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    custom_names = settings.get("names", {})
    collision_ids = seo_collision_ids(events, custom_names, settings)
    today = date.today().isoformat()
    remote_decisions = load_decisions()
    cached_decisions = load_cached_decisions()
    sync_failed = remote_decisions is None
    known_decisions = cached_decisions if sync_failed else remote_decisions
    rejected_ids = {str(d.get("event_id")) for d in known_decisions if d.get("status") == "rejected"}
    if sync_failed:
        rejected_ids.update(str(e.get("id")) for e in events
                            if e.get("moderation_status") == "rejected")
    conflicts = schedule_conflicts(events, settings, rejected_ids)
    event_issues = {}
    for event in events:
        reviewed = dict(event)
        url = event.get("source_url") or ""
        if url in custom_names:
            reviewed["artist"] = custom_names[url]
        issues = reasons(reviewed)
        peers = conflicts.get(str(event.get("id")), [])
        if peers:
            # ID и имя соседней карточки входят в fingerprint: новый конфликт
            # требует нового решения, прежнее одобрение его не обходит.
            issues.append(SCHEDULE_CONFLICT + ": " + "; ".join(
                f"{p['artist']} (id {p['id']})" for p in peers))
        event_issues[str(event.get("id"))] = issues
    if sync_failed:
        decisions = cached_decisions
        print("Модерация: Worker недоступен, использую локальный журнал решений.")
    else:
        decisions = enrich_remote_decisions(remote_decisions, cached_decisions, events, event_issues)
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
        issues = list(event_issues[str(event.get("id"))])
        schedule_conflict = str(event.get("id")) in conflicts
        seo_collision = str(event.get("id")) in collision_ids
        if seo_collision:
            issues.append(SEO_COLLISION)
        decision = decision_for(event, by_id, legacy_by_source)
        if decision is None and sync_failed:
            decision = decision_embedded_in_event(event)
        status = (decision or {}).get("status")
        fingerprint = event_fingerprint(event, issues)

        # Одобрение действует на конкретную версию карточки. У старых данных
        # без fingerprint допускаем разовую миграцию только в офлайн-режиме.
        legacy_approved = sync_failed and decision and not decision.get("fingerprint")
        approved = not seo_collision and status == "approved" and decision.get("reasons", []) == issues and (
            decision.get("fingerprint") == fingerprint or legacy_approved
        )
        rejected = status == "rejected"
        archived = bool(event.get("date")) and event["date"] < today
        # Однозначно сверенные изменения существующей карточки применяются
        # автоматически: это не новый LLM-кандидат, а обновление того же
        # первоисточника с сохранённым event_id.
        auto_approved = not seo_collision and not schedule_conflict and "нет названия" not in issues and (
            bool(event.get("auto_updated"))
            or (bool(issues) and set(issues).issubset(OPTIONAL_ISSUES))
        )
        event["needs_review"] = bool(issues) and not approved and not rejected and (seo_collision or not archived) and not auto_approved
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
        if issues and not approved and not rejected and (seo_collision or not archived) and not auto_approved:
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
