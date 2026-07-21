#!/usr/bin/env python3
"""Дозаполняет venues.json координатами (lat/lon) через Nominatim (OpenStreetMap).

В отличие от build_venues.py (черновая пересборка с нуля из events.json),
этот скрипт читает уже существующий venues.json, находит записи без lat/lon
и дописывает координаты — остальные поля (включая ручные description) не трогает.

Nominatim бесплатен и не требует API-ключа, но требует соблюдать usage policy:
не чаще 1 запроса/сек и осмысленный User-Agent с контактом.
https://operations.osmfoundation.org/policies/nominatim/
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).parent
VENUES_FILE = BASE_DIR / "venues.json"
CACHE_DIR = BASE_DIR / ".cache"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "MestovNet/1.0 (https://mestov.net; kulakovakatalina@gmail.com)"
RATE_LIMIT_SEC = 1.0


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cache_read(text: str):
    path = CACHE_DIR / f"{_cache_key(text)}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return "MISS"  # отличаем «не искали» от «искали, но не нашли» (кэш None)


def _cache_write(text: str, data):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(text)}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def geocode(query: str):
    """Возвращает (lat, lon) или None. Кэширует оба исхода. Делает реальный
    запрос к Nominatim только если результата ещё нет в кэше — вызывающий
    код должен соблюдать rate limit между не-кэшированными вызовами."""
    cache_text = "nominatim:" + query
    cached = _cache_read(cache_text)
    if cached != "MISS":
        return tuple(cached) if cached else None, True

    result = None
    try:
        resp = httpx.get(NOMINATIM_URL, params={
            "q": query,
            "format": "json",
            "limit": 1,
        }, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            result = (round(float(results[0]["lat"]), 6), round(float(results[0]["lon"]), 6))
    except Exception as e:
        # сетевая ошибка — НЕ кэшируем, чтобы можно было повторить
        print(f"  ! ошибка геокодирования «{query}»: {e}", file=sys.stderr)
        return None, False

    # закэшируем и «не найдено», раз запрос к API прошёл успешно
    _cache_write(cache_text, list(result) if result else None)
    return result, False


def main():
    venues = json.loads(VENUES_FILE.read_text(encoding="utf-8"))

    geocoded, cached_hit, failed, skipped = 0, 0, [], 0
    for v in venues:
        if v.get("lat") is not None and v.get("lon") is not None:
            skipped += 1
            continue

        # порядок «город, адрес» и без суффикса «Крым» — Nominatim распознаёт
        # заметно лучше (спорный статус региона путает его парсер, если
        # «Крым» стоит после номера дома)
        query = f"{v['city']}, {v['address']}" if v.get("address") else f"{v['city']}, {v['name']}"
        coords, was_cached = geocode(query)
        if not was_cached:
            time.sleep(RATE_LIMIT_SEC)  # соблюдаем usage policy Nominatim

        # фолбэк: если адрес — не улица/дом, а описание места («7 долин»,
        # название пляжа и т.п.), пробуем найти по названию заведения —
        # известные достопримечательности Nominatim часто знает по имени
        if not coords and v.get("address"):
            fallback_query = f"{v['name']}, {v['city']}"
            coords, was_cached_fb = geocode(fallback_query)
            if not was_cached_fb:
                time.sleep(RATE_LIMIT_SEC)
            was_cached = was_cached or was_cached_fb
            query = fallback_query if coords else query

        if coords:
            v["lat"], v["lon"] = coords
            geocoded += 1
            cached_hit += was_cached
        else:
            failed.append(f"{v['name']} ({v['city']}) — запрос: {query}")

    VENUES_FILE.write_text(
        json.dumps(venues, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Уже с координатами: {skipped}")
    print(f"Найдено координат: {geocoded} (из кэша: {cached_hit})")
    if failed:
        print(f"\nНе удалось геокодировать ({len(failed)}):")
        for line in failed:
            print(f"  • {line}")


if __name__ == "__main__":
    main()
