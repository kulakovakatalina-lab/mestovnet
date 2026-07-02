#!/usr/bin/env python3
"""Черновая сборка реестра заведений (venues.json) из events.json.

Что делает:
  1. Из строки venue отделяет «хвост-адрес» (в скобках, после запятой с улицей,
     либо дублирующий город) → база названия + кандидат в адрес.
  2. Нормализует базу названия (регистр, кавычки, ё) → ключ группировки.
  3. Группирует события по ключу, выбирает каноническое имя и город.
  4. Адрес: сначала из строки venue, иначе из description (редко), иначе пусто.
  5. Генерирует латинский slug транслитом.
  6. Пишет venues.json (черновик) + печатает отчёт и подозрения на дубли.

Это ЧЕРНОВИК для ручной проверки, не финальные данные.
"""

import json
import re
import difflib
from collections import defaultdict, Counter
from pathlib import Path

BASE_DIR = Path(__file__).parent
EVENTS_FILE = BASE_DIR / "events.json"
OUT_FILE = BASE_DIR / "venues.json"

KNOWN_CITIES = {
    "Симферополь", "Ялта", "Севастополь", "Бахчисарай", "Судак", "Евпатория",
    "Керчь", "Коктебель", "Феодосия", "Алушта", "Саки", "Крым", "Симеиз",
    "Научный (Бахчисарайский р-н)", "Бахчисарайский район",
    "Бахчисарайский район, с. Путиловка",
}

# слова-маркеры того, что дальше идёт адрес
STREET_RE = re.compile(
    r"(ул\.|улиц|пр-т|проспект|пр\.|пл\.|площад|наб\.|набережн|шоссе|"
    r"переулок|бульвар|проезд|аллея|д\.\s?\d|\bдом\s?\d)",
    re.I,
)
# «что-то Число» в скобках или после запятой — тоже адрес
ADDR_NUM_RE = re.compile(r"[А-ЯЁа-яёA-Za-z].*\d")

# ── Курируемые слияния ────────────────────────────────────────────────────
# Группы норм-ключей, которые = одно физическое заведение.
# (canon_id, каноническое имя, город, [норм-ключи вариантов])
MERGE_GROUPS = [
    ("teatr-chehova-yalta", "Театр им. А.П. Чехова", "Ялта", [
        "театр им. а. п. чехова", "театр им. а.п. чехова",
        "театр имени а.п. чехова", "ялтинский театр им. чехова",
        "колонный зал театра им. а.п. чехова",
    ]),
    ("dom-muzey-chehova", "Дом-музей А.П. Чехова (Белая дача)", "Ялта", [
        "дом-музей а.п. чехова (белая дача)", "дом-музей им. а.п. чехова",
    ]),
    ("kdk-korabel-kerch", "ДК «Корабел»", "Керчь", [
        "корабел", "кдк корабел",
        "дк корабел, малый зал", "дк корабел, театральный зал",
    ]),
    ("krongs", "Krongs", "Крым", ["krongs", "кронгс", "кронгс паб"]),
    ("santa-barbara", "Санта Барбара", "Симферополь", [
        "santa barbara", "санта барбара",
    ]),
    ("krymskiy-muz-teatr", "Крымский музыкальный театр", "Симферополь", [
        "музыкальный театр", "крымский музыкальный театр",
    ]),
    ("art-kovcheg", "Арт-Ковчег", "Бахчисарайский район, с. Путиловка", [
        "арт-ковчег", "арт-ковчег, с. путиловка",
    ]),
    ("yalta-inturist", "Отель «Ялта-Интурист»", "Ялта", [
        "отель ялта-интурист", "прогулочная аллея отеля ялта-интурист",
        "пляж изумрудный, отель ялта-интурист",
    ]),
    ("akvamarin", "Отель «Аквамарин»", "Севастополь", [
        "отель аквамарин", "отель аквамарин, летняя сцена",
        "курортный комплекс аквамарин, летняя сцена",
    ]),
    ("palmira-palace", "Palmira Palace", "Ялта", [
        "palmira palace", "palmira palace resort & spa", "отель пальмира палас",
    ]),
    ("yubileyny", "Концертный зал «Юбилейный»", "Ялта", [
        "юбилейный", "концертный зал юбилейный",
        "малый зал концертного зала юбилейный",
    ]),
    ("dof", "Дом офицеров флота", "Севастополь", ["дом офицеров флота", "доф"]),
    ("dk-profsoyuzov", "Дворец культуры профсоюзов", "Симферополь", [
        "дк профсоюзов", "дворец культуры профсоюзов",
    ]),
    ("mriya", "Мрия", "Ялта", ["мрия", "мрия, бальный зал"]),
    ("mramornaya-peschera", "Мраморная пещера", "Симферополь", [
        "мраморная пещера", "пещера мраморная",
    ]),
    ("naberezhnaya-yalta", "Набережная Ялты", "Ялта", [
        "набережная", "набережная ялты",
    ]),
    ("ali-bair", "Эко-пространство «Али-Баир»", "Севастополь", [
        "али-баир", "эко-пространство али баир",
        "эко-пространство али-баир, байдарская долина (с. широкое)",
        "байдарская долина, alibair",
    ]),
    ("paniya-park", "Пания Парк", "Севастополь", [
        "пания парк, деревня мастеров, с. соколиное",
        "таверна дирижабль, пания парк, деревня мастеров",
    ]),
    ("rodnoe-gnezdo", "Усадьба «Родное гнездо»", "Севастополь", [
        "усадьба родное гнездо", "ресторан гнездо, усадьба родное гнездо",
    ]),
    ("bely-club", "Клуб «Белый»", "Евпатория", ["белый", "ночной клуб белый"]),
    ("btr", "БТР / Бар тяжёлого рока", "Севастополь", [
        "бтр", "бтр / бар тяжелого рока",
    ]),
    ("depo", "Депо", "Симферополь", ["депо", "клуб депо"]),
    ("sev-ckii", "Севастопольский ЦКиИ", "Севастополь", [
        "центр культуры и искусства", "севастопольский цкии",
    ]),
]
# Строки, которые не являются заведениями (фестивали/организаторы/каналы).
# Им карточка не создаётся, события остаются без ссылки на заведение.
EXCLUDE_KEYS = {
    "скажите джаз", "крым event", "крымские дела", "comedy republic",
}

MERGE_MAP = {}   # норм-ключ → canon_id
MERGE_META = {}  # canon_id → (name, city)
for cid, nm, ct, keys in MERGE_GROUPS:
    MERGE_META[cid] = (nm, ct)
    for k in keys:
        MERGE_MAP[k] = cid

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def strip_address(venue: str):
    """Отделяет адрес-хвост от названия. Возвращает (name, address|None)."""
    v = venue.strip()
    address = None

    # 1) адрес в скобках, если внутри есть цифра (номер дома) или маркер улицы
    m = re.search(r"\(([^)]+)\)", v)
    if m and (STREET_RE.search(m.group(1)) or re.search(r"\d", m.group(1))):
        address = m.group(1).strip()
        v = (v[: m.start()] + v[m.end():]).strip()

    # 2) разбор по запятым: часть, начинающаяся с улицы/номера — адрес;
    #    часть, равная известному городу — отбрасываем (дублирует source_city)
    parts = [p.strip() for p in v.split(",")]
    name_parts, addr_parts = [parts[0]], []
    for p in parts[1:]:
        if p in KNOWN_CITIES:
            continue
        if STREET_RE.search(p) or ADDR_NUM_RE.search(p):
            addr_parts.append(p)
        elif addr_parts:
            addr_parts.append(p)  # продолжение адреса
        else:
            name_parts.append(p)  # уточнение названия (напр. «Театральный зал»)
    if addr_parts:
        tail = ", ".join(addr_parts)
        address = f"{address}, {tail}" if address else tail

    name = ", ".join(name_parts).strip(" ,")
    return name or venue.strip(), address


def norm_key(name: str) -> str:
    s = name.lower().replace("ё", "е")
    s = re.sub(r"[«»\"“”„'’]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def slugify(name: str) -> str:
    s = name.lower().replace("ё", "е")
    out = []
    for ch in s:
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)  # латиница/цифры как есть
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug


def addr_from_desc(desc: str):
    if not desc:
        return None
    m = re.search(r"Адрес:\s*([^.\n]+)", desc)
    if m:
        return m.group(1).strip()
    m = re.search(r"на ул\.[^.\n]+", desc)
    if m:
        return m.group(0).strip()
    return None


def main():
    events = json.load(open(EVENTS_FILE, encoding="utf-8"))
    groups = defaultdict(list)  # key -> list of (event, base_name, addr)

    for e in events:
        raw = (e.get("venue") or "").strip()
        if not raw:
            continue
        base, addr = strip_address(raw)
        if not addr:
            addr = addr_from_desc(e.get("description") or "")
        key = norm_key(base)
        if key in EXCLUDE_KEYS:
            continue  # фестиваль/организатор — не заведение
        key = MERGE_MAP.get(key, key)  # применяем курируемые слияния
        groups[key].append((e, base, addr))

    venues = []
    slug_seen = {}
    for key, items in groups.items():
        if key in MERGE_META:
            # каноническое имя и город из курируемой карты
            name, city = MERGE_META[key]
        else:
            # каноническое имя — самое частое написание базы
            name = Counter(b for _, b, _ in items).most_common(1)[0][0]
            # город — самый частый непустой
            city = Counter(
                (e.get("source_city") or "") for e, _, _ in items if e.get("source_city")
            ).most_common(1)
            city = city[0][0] if city else ""
        # адрес — первый найденный
        address = next((a for _, _, a in items if a), "")
        # алиасы — все варианты исходной строки venue
        aliases = sorted({(e.get("venue") or "").strip() for e, _, _ in items})

        slug = slugify(name)
        if slug in slug_seen:  # разрулим коллизии слагов
            slug = f"{slug}-{slugify(city) or len(venues)}"
        slug_seen[slug] = True

        venues.append({
            "slug": slug,
            "name": name,
            "city": city,
            "address": address,
            "event_count": len(items),
            "aliases": aliases,
        })

    venues.sort(key=lambda v: -v["event_count"])
    json.dump(venues, open(OUT_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # ── отчёт ────────────────────────────────────────────────────────────
    with_addr = [v for v in venues if v["address"]]
    print(f"Заведений: {len(venues)}  (было уникальных строк: "
          f"{len({(e.get('venue') or '') for e in events if e.get('venue')})})")
    print(f"С адресом: {len(with_addr)},  только город: {len(venues) - len(with_addr)}")
    print("\nС адресом:")
    for v in with_addr:
        print(f"  • {v['name']} — {v['address']} ({v['city']})")

    # подозрения на дубли (похожие ключи в одном городе)
    print("\nВозможные дубли (проверить вручную):")
    keys = [(v["name"], v["city"], norm_key(v["name"])) for v in venues]
    shown = set()
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            n1, c1, k1 = keys[i]
            n2, c2, k2 = keys[j]
            r = difflib.SequenceMatcher(None, k1, k2).ratio()
            if r >= 0.62 and (i, j) not in shown:
                shown.add((i, j))
                print(f"  ? «{n1}» ({c1})  ≈  «{n2}» ({c2})   [{r:.2f}]")


if __name__ == "__main__":
    main()
