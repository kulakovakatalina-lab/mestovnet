#!/usr/bin/env python3
"""Черновая сборка реестра артистов (artists.json) из events.json.

Что делает:
  1. Пропускает события, помеченные как generic-фолбэк (is_generic_artist) —
     «DJ-сет», «Музыкальное лото» и т.п. не считаются артистами.
  2. Разбирает поле artist на отдельные имена (запятая + _artist_parts:
     и/&/+/feat./ft./при участии/с участием).
  3. Группирует упоминания по норм-ключу (регистр/кавычки/ё, без префиксов
     «группа»/«band») и транслит-ключу (кириллица ⇄ латиница, SHAMAN/ШАМАН),
     плюс курируемые слияния MERGE_GROUPS.
  4. Кросс-сверяет кандидатов с venues.json (имя/алиасы) — совпадение
     с площадкой исключает кандидата из артистов (см. отчёт).
  5. Публикует только артистов с event_count >= MIN_EVENTS.
  6. Пишет artists.json (черновик) + отчёт: исключённые как площадка,
     ниже порога, подозрения на дубли среди опубликованных.

Это ЧЕРНОВИК для ручной проверки, не финальные данные (по образцу build_venues.py).
"""

import json
import re
import difflib
from collections import defaultdict, Counter
from pathlib import Path

import parser as parser_mod  # переиспользуем канонические _artist_parts/_normalize/_TRANSLIT/is_generic_artist

BASE_DIR = Path(__file__).parent
EVENTS_FILE = BASE_DIR / "events.json"
VENUES_FILE = BASE_DIR / "venues.json"
OUT_FILE = BASE_DIR / "artists.json"

MIN_EVENTS = 2

# ── Курируемые слияния ────────────────────────────────────────────────────
# (canon_id, каноническое имя, [норм-ключи вариантов]) — заполняется по факту
# разбора отчёта о подозрениях на дубли, как MERGE_GROUPS в build_venues.py.
# «Скажите Джаз»/«Скажите Jazz» не слились автоматически: слово «джаз» —
# заимствование, механический транслит даёт «dzhaz», а не «jazz», так что
# translit_key их не пересекает. Отдельный частный случай, не общее правило.
MERGE_GROUPS: list[tuple[str, str, list[str]]] = [
    ("skazhite-jazz", "Скажите Джаз",
     ["скажите джаз", "скажите jazz", "джазбэнд скажите jazz"]),
    # «Ирина и Александр Круг»: сплит по « и » отрезал фамилию у Ирины Круг
    ("irina-krug", "Ирина Круг", ["ирина"]),
    # Название программы приклеено к имени коллектива в исходных постах
    ("kubanskiy-kazachiy-hor", "Кубанский казачий хор",
     ["кубанский казачий хор русь от края до края"]),
    ("jawa", "Jawa", ["jawa хиты сектор газа"]),
    ("elena-novikova", "Елена Новикова", ["елена новикова stand up"]),
    # Каноническое написание с «ё» (частотный выбор дал вариант без неё)
    ("chernyy-kofe", "Чёрный Кофе", ["черный кофе", "чёрный кофе"]),
]

# ── Курируемый exclude-список ──────────────────────────────────────────────
# Норм-ключи явных не-артистов, которые не поймала автоматика
# (venue-сверка/generic-фолбэк). Заполняется по факту разбора отчёта.
# Найдено при разборе отчёта build_artists.py (2026-07-15): реальные варианты
# текста из source-постов, не совпадающие точно со списком плейсхолдеров
# _GENERIC_ARTIST_LITERALS в parser.py («DJ-сет» с дефисом vs «DJ сет» без).
EXCLUDE_ARTISTS: set[str] = {
    "dj сет", "dj set",
    "дегустация настоек",
}

MERGE_MAP: dict[str, str] = {}
MERGE_NAME: dict[str, str] = {}
for cid, name, keys in MERGE_GROUPS:
    MERGE_NAME[cid] = name
    for k in keys:
        MERGE_MAP[k] = cid


def norm_key(name: str) -> str:
    n = parser_mod._normalize(name)
    for prefix in ("группа ", "band ", "группа «", "«"):
        if n.startswith(prefix):
            n = n[len(prefix):].strip()
    return n


def translit_key(name: str) -> str:
    return "".join(parser_mod._TRANSLIT.get(ch, ch) for ch in norm_key(name))


def slugify(name: str) -> str:
    s = name.lower().replace("ё", "е")
    out = []
    for ch in s:
        if ch in parser_mod._TRANSLIT:
            out.append(parser_mod._TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    return re.sub(r"-+", "-", "".join(out)).strip("-")


def load_venue_keys(venues: list[dict]) -> set[str]:
    keys = set()
    for v in venues:
        keys.add(norm_key(v["name"]))
        for a in v.get("aliases", []):
            keys.add(norm_key(a))
    return keys


def needs_desc_update(description, event_count: int, baseline) -> bool:
    """Описание пора переписать: его нет, либо событийная история заметно
    выросла с момента последней ручной правки (см. ACTUALIZATION.md)."""
    if not description:
        return True
    baseline = baseline or 0
    if baseline <= 0:
        return True
    if event_count - baseline >= 5:
        return True
    if event_count >= baseline * 1.3:
        return True
    return False


def main():
    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    venues = json.loads(VENUES_FILE.read_text(encoding="utf-8")) if VENUES_FILE.exists() else []
    venue_keys = load_venue_keys(venues)

    # Рукописные описания из прошлой версии реестра переживают пересборку:
    # мерджим по slug, а если slug не совпал (переименование/ручная чистка) —
    # по имени, как fallback (см. тот же приём в build_venues.py). Написание
    # описаний — отдельный ручной шаг, скрипт их только сохраняет, никогда не
    # генерирует и не затирает. desc_baseline_count — снимок event_count на
    # момент последней ручной правки описания, для детекта дрейфа.
    prev_by_slug: dict[str, dict] = {}
    prev_by_name: dict[str, dict] = {}
    if OUT_FILE.exists():
        for prev in json.loads(OUT_FILE.read_text(encoding="utf-8")):
            if prev.get("slug"):
                prev_by_slug[prev["slug"]] = prev
            if prev.get("name"):
                prev_by_name[prev["name"]] = prev

    # is_generic_artist проверяет ПОЛЕ ЦЕЛИКОМ — событие вида «Фёдор Старовойтов,
    # Вечеринка» им не ловится (в поле есть и реальное имя). Поэтому отдельно
    # фильтруем generic-плейсхолдеры и на уровне отдельных имён после сплита.
    generic_norm = {parser_mod._normalize(s) for s in parser_mod._GENERIC_ARTIST_LITERALS}

    # Собираем все упоминания артистов: raw_name -> [индексы событий]
    mentions: dict[str, list[int]] = defaultdict(list)
    skipped_generic = 0
    skipped_generic_fragments = 0
    for i, e in enumerate(events):
        if parser_mod.is_generic_artist(e):
            skipped_generic += 1
            continue
        artist = (e.get("artist") or "").strip()
        if not artist:
            continue
        for raw in parser_mod._split_artist_field(artist):
            for name in parser_mod._artist_parts(raw.strip()):
                name = name.strip()
                if not name:
                    continue
                if parser_mod._normalize(name) in generic_norm:
                    skipped_generic_fragments += 1
                    continue
                mentions[name].append(i)

    names = list(mentions.keys())
    idx = {n: i for i, n in enumerate(names)}
    parent = list(range(len(names)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    # Группируем по норм-ключу, транслит-ключу и курируемым слияниям
    by_norm: dict[str, list[int]] = defaultdict(list)
    by_translit: dict[str, list[int]] = defaultdict(list)
    by_merge: dict[str, list[int]] = defaultdict(list)
    for n in names:
        i = idx[n]
        nk = norm_key(n)
        by_norm[nk].append(i)
        by_translit[translit_key(n)].append(i)
        mid = MERGE_MAP.get(nk)
        if mid:
            by_merge[mid].append(i)

    for bucket in list(by_norm.values()) + list(by_translit.values()) + list(by_merge.values()):
        for j in range(1, len(bucket)):
            union(bucket[0], bucket[j])

    groups: dict[int, list[str]] = defaultdict(list)
    for n in names:
        groups[find(idx[n])].append(n)

    excluded_venue_match: list[tuple[str, int]] = []
    below_threshold: list[tuple[str, int]] = []
    excluded_curated: list[tuple[str, int]] = []
    artists: list[dict] = []
    slug_seen: dict[str, bool] = {}

    for variant_names in groups.values():
        event_indices: set[int] = set()
        for n in variant_names:
            event_indices.update(mentions[n])
        event_count = len(event_indices)

        variant_counts = Counter({n: len(set(mentions[n])) for n in variant_names})
        canon_name = variant_counts.most_common(1)[0][0]

        # Курируемое имя (MERGE_GROUPS) перебивает частотный выбор
        curated_cid = next(
            (MERGE_MAP[norm_key(n)] for n in variant_names if norm_key(n) in MERGE_MAP),
            None,
        )
        if curated_cid:
            canon_name = MERGE_NAME[curated_cid]

        nk = norm_key(canon_name)

        if nk in EXCLUDE_ARTISTS:
            excluded_curated.append((canon_name, event_count))
            continue
        if nk in venue_keys:
            excluded_venue_match.append((canon_name, event_count))
            continue
        if event_count < MIN_EVENTS:
            below_threshold.append((canon_name, event_count))
            continue

        cities: Counter = Counter()
        venues_played: Counter = Counter()
        dates: list[str] = []
        for i in event_indices:
            e = events[i]
            if e.get("source_city"):
                cities[e["source_city"]] += 1
            if e.get("venue"):
                venues_played[e["venue"]] += 1
            if e.get("date"):
                dates.append(e["date"])

        slug = slugify(canon_name)
        if slug in slug_seen:
            slug = f"{slug}-{len(artists)}"
        slug_seen[slug] = True

        prev = prev_by_slug.get(slug) or prev_by_name.get(canon_name) or {}
        description = prev.get("description")
        baseline = prev.get("desc_baseline_count")
        if description and baseline is None:
            baseline = prev.get("event_count") or event_count
        elif not description:
            baseline = 0

        artists.append({
            "slug": slug,
            "name": canon_name,
            "aliases": sorted(set(variant_names)),
            "event_count": event_count,
            "cities": [c for c, _ in cities.most_common()],
            "venues": [v for v, _ in venues_played.most_common()],
            "first_seen": min(dates) if dates else None,
            "last_seen": max(dates) if dates else None,
            "description": description,
            "desc_baseline_count": baseline,
        })

    artists.sort(key=lambda a: -a["event_count"])
    OUT_FILE.write_text(
        json.dumps(artists, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── отчёт ────────────────────────────────────────────────────────────
    print(f"Событий пропущено как generic-фолбэк: {skipped_generic}")
    print(f"Generic-фрагментов отфильтровано внутри смешанных полей: {skipped_generic_fragments}")
    print(f"Уникальных упоминаний артистов (до группировки): {len(names)}")
    print(f"Опубликовано артистов (event_count >= {MIN_EVENTS}): {len(artists)}")
    print(f"Ниже порога (1 событие, не публикуются): {len(below_threshold)}")
    print(f"Исключено curated-списком EXCLUDE_ARTISTS: {len(excluded_curated)}")
    print(f"Исключено — совпадает с площадкой в venues.json: {len(excluded_venue_match)}")

    if excluded_venue_match:
        print("\nИсключено как площадка (проверить, что это не артист):")
        for name, cnt in sorted(excluded_venue_match, key=lambda x: -x[1]):
            print(f"  • {name} ({cnt} событий)")

    stale = [a for a in artists
             if needs_desc_update(a["description"], a["event_count"], a["desc_baseline_count"])]
    print(f"\nТребует обновления описания ({len(stale)}):")
    for a in sorted(stale, key=lambda a: -a["event_count"]):
        state = "нет описания" if not a["description"] else (
            f"было {a['desc_baseline_count']} → стало {a['event_count']}"
        )
        print(f"  • {a['name']} — {state}")

    print("\nВозможные дубли среди опубликованных (проверить вручную):")
    keys = [(a["name"], norm_key(a["name"])) for a in artists]
    shown = set()
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            n1, k1 = keys[i]
            n2, k2 = keys[j]
            r = difflib.SequenceMatcher(None, k1, k2).ratio()
            if r >= 0.62 and (i, j) not in shown:
                shown.add((i, j))
                print(f"  ? «{n1}»  ≈  «{n2}»   [{r:.2f}]")

    if below_threshold:
        print(f"\nНиже порога (первые 20 из {len(below_threshold)}):")
        for name, cnt in sorted(below_threshold, key=lambda x: -x[1])[:20]:
            print(f"  • {name} ({cnt})")


if __name__ == "__main__":
    main()
