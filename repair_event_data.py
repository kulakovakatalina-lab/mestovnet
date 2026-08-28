"""Разовая, идемпотентная очистка уже опубликованной афиши.

Скрипт хранит только исправления, подтверждённые первоисточниками. Он не
делает сетевых запросов и безопасен для повторного запуска.
"""

import json
from pathlib import Path

from parser import deduplicate_events


EVENTS_FILE = Path("events.json")


def main() -> None:
    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    by_id = {event.get("id"): event for event in events}

    # Первичный билетный источник подтверждает именно это название; в старой
    # карточке к нему был ошибочно присоединён соседний концерт хора.
    if event := by_id.get("59e0e5af"):
        event["artist"] = "Хиты 2000-х. Караоке с оркестром"

    # Романсы на стихи Пушкина — классическая программа, а не поп-концерт.
    if event := by_id.get("d3f6d3ad"):
        event["genre"] = "классика"

    # В сводной публикации организатора места названы явно. Раньше парсер
    # ошибочно записал город в поле площадки.
    if event := by_id.get("8884d494"):
        event["venue"] = "Арт-кафе «Снежинка»"
    if event := by_id.get("e5674032"):
        event["venue"] = "Ресторан «Мотивы»"

    # Официальный пост Jam Club подтверждает для Rammlied время начала 19:00
    # (двери открываются в 17:00). Карточка агрегатора потеряла это поле.
    if event := by_id.get("18d5049c"):
        event["time"] = "19:00"
        event["venue"] = "Jam Club"
        event["source_url"] = "https://t.me/clubjam/1125"

    # В тексте агрегатора присутствует чужой фрагмент про Набережные Челны.
    # Шапка источника и карточка сеанса подтверждают Симферополь/«Депо».
    if event := by_id.get("4993369e"):
        event["description"] = event.get("description", "").replace(
            "ЙОРШ. 04 ноября.Набережные Челны. Депо. ",
            "ЙОРШ. 04 ноября. Депо, Симферополь. ",
        )

    # Олена Уутай — один сеанс, продублированный Яндекс.Афишей и Afisha.ru.
    # Оставляем полную карточку Afisha.ru, у которой есть развёрнутое описание.
    events = [event for event in events if event.get("id") != "259b8985"]

    # Инструментальное трио 2 августа — перепост одной программы с одинаковым
    # составом; сохраняем карточку с более полным названием коллектива.
    events = [event for event in events if event.get("id") != "3248641f"]

    # `crimea_event/5631` — вторичный список афиши Jam Club: карточка
    # Metallica дублирует официальный анонс Blackened. А ссылку
    # `clubjam/1125` парсер ошибочно привязал к AC/DC и Beatles, хотя в этом
    # посте опубликован только Rammlied. Эти три карточки не имеют верного
    # первоисточника и не должны возвращаться на сайт.
    rejected_ids = {"19b4212a", "fa1ea514", "317a62df"}
    events = [event for event in events if event.get("id") not in rejected_ids]

    # Применяем те же критерии к историческим карточкам: они могли попасть в
    # файл до появления более строгой дедупликации.
    events = deduplicate_events(events)

    EVENTS_FILE.write_text(
        json.dumps(events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
