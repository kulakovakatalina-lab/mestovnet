#!/usr/bin/env python3
"""Найти заведения из venues.json без собственного прямого источника в channels.json.

Заведение считается «найденным только через агрегатор», если ни один venue-канал
(любого типа: telegram/vk/max/instagram) из channels.json не совпадает по названию
(с учётом алиасов) и городу. Такие заведения сейчас видны сайту только через
Яндекс.Афишу / Афишу.ру / чужие afisha-каналы — у них нет своего канала для
более полного и раннего покрытия событий.

Вывод: markdown-чеклист, отсортированный по event_count (сначала самые активные
заведения — они дают наибольшую отдачу от точечного поиска).

Запуск:
    python3 find_venues_without_source.py [--min-events N] [--out FILE]
"""

import argparse
import difflib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

NAME_MATCH_THRESHOLD = 0.6

# Из build_venues.py — чтобы сравнивать «API Balaklava» и «API Балаклава» как одно.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[«»\"'.,()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "".join(TRANSLIT.get(ch, ch) for ch in text)


def load_venue_channels(channels: dict) -> list[dict]:
    """Собрать все venue-каналы (не afisha) из всех типов источников."""
    result = []
    for key in ("channels", "max_channels", "vk_channels", "instagram_channels"):
        for c in channels.get(key, []):
            if c.get("type") == "venue":
                result.append(c)
    return result


def cities_compatible(venue_city: str, channel_city: str) -> bool:
    if channel_city in ("Крым", venue_city):
        return True
    return normalize(channel_city) == normalize(venue_city)


def has_own_channel(venue: dict, venue_channels: list[dict]) -> bool:
    names_to_check = [venue["name"]] + venue.get("aliases", [])
    normalized_names = [normalize(n) for n in names_to_check]

    for ch in venue_channels:
        if not cities_compatible(venue["city"], ch.get("city", "")):
            continue
        ch_title = normalize(ch.get("title", ""))
        for vname in normalized_names:
            if not vname or not ch_title:
                continue
            if vname in ch_title or ch_title in vname:
                return True
            ratio = difflib.SequenceMatcher(None, vname, ch_title).ratio()
            if ratio >= NAME_MATCH_THRESHOLD:
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-events", type=int, default=0, help="Показывать только заведения с event_count >= N")
    parser.add_argument("--out", type=str, default=None, help="Путь для сохранения markdown (по умолчанию — только stdout)")
    args = parser.parse_args()

    venues = json.loads((PROJECT_ROOT / "venues.json").read_text(encoding="utf-8"))
    channels = json.loads((PROJECT_ROOT / "channels.json").read_text(encoding="utf-8"))
    venue_channels = load_venue_channels(channels)

    missing = [v for v in venues if not has_own_channel(v, venue_channels)]
    missing = [v for v in missing if v.get("event_count", 0) >= args.min_events]
    missing.sort(key=lambda v: v.get("event_count", 0), reverse=True)

    lines = [
        "# Заведения без собственного источника",
        "",
        f"Всего заведений: {len(venues)}. Без своего канала: {len(missing)}.",
        "",
        "Найдены только через агрегаторы (Яндекс.Афиша / Афиша.ру / чужие afisha-каналы).",
        "Отсортировано по количеству событий — начинать сверху.",
        "",
        "| # | Заведение | Город | Адрес | Событий |",
        "|---|---|---|---|---|",
    ]
    for i, v in enumerate(missing, 1):
        addr = v.get("address", "") or "—"
        lines.append(f"| {i} | {v['name']} | {v['city']} | {addr} | {v.get('event_count', 0)} |")

    output = "\n".join(lines)
    print(output)

    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
        print(f"\nСохранено в {args.out}")


if __name__ == "__main__":
    main()
