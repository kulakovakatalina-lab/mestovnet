"""
Шаг 3: принимает извлечённые события (extracted_events.json + yandex_events.json),
мёрджит с архивом events.json, дедуплицирует, определяет жанры, пушит на GitHub.
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date

OUTPUT_FILE = "events.json"
EXTRACTED_FILE = "extracted_events.json"
YANDEX_FILE = "yandex_events.json"
AFISHA_FILE = "afisha_events.json"

# ── Вспомогательные ────────────────────────────────────────────────────────────

def _to_scalar(value):
    """Приводит значение поля к строке, если LLM вернул список/число."""
    if isinstance(value, str):
        if value.strip().lower() in ("null", "none", "undefined", "nan"):
            return None
        return value
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, "") and str(v).lower() not in ("null", "none"))
    if value is None:
        return None
    return str(value)


def _valid_date_or_none(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _sanitize_event_dates(events: list[dict]) -> int:
    cleaned = 0
    for event in events:
        raw = event.get("date")
        if not raw:
            continue
        valid = _valid_date_or_none(raw)
        if valid is None:
            event["date"] = None
            cleaned += 1
        else:
            event["date"] = valid
    return cleaned


def _valid_time_or_none(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    labelled_start = re.search(r"(\d{1,2}:\d{2})\s*\((?:начало|старт)[^)]*\)", value, re.IGNORECASE)
    if labelled_start:
        return _valid_time_or_none(labelled_start.group(1))
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*[-–—]\s*(\d{1,2}):(\d{2}))?", value)
    if not match:
        return None

    def canonical(hour: str, minute: str):
        h, m = int(hour), int(minute)
        return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m <= 59 else None

    start = canonical(match.group(1), match.group(2))
    if start is None:
        return None
    if match.group(3) is None:
        return start
    end = canonical(match.group(3), match.group(4))
    return f"{start}–{end}" if end is not None else None


def _sanitize_event_times(events: list[dict]) -> tuple[int, int]:
    normalized = cleaned = 0
    for event in events:
        raw = event.get("time")
        if not raw:
            continue
        valid = _valid_time_or_none(raw)
        if valid is None:
            event["time"] = None
            cleaned += 1
        elif valid != raw:
            event["time"] = valid
            normalized += 1
    return normalized, cleaned


# ── Жанры ──────────────────────────────────────────────────────────────────

_CHANNEL_GENRES: dict[str, str] = {
    "skazhitejazz": "джаз",
}

_GENRE_RULES: list[tuple[list[str], str]] = [
    (["фолк-метал", "folk metal"],                                             "фолк-метал"),
    (["панк", "punk"],                                                         "панк-рок"),
    (["метал", "metal", "radio tapok", "blackened"],                           "метал"),
    (["хип-хоп", "hip-hop", "хип хоп", "рэп", "rap"],                        "хип-хоп"),
    (["джаз", "jazz", "свинг", "swing"],                                      "джаз"),
    (["блюз", "blues", "blues night"],                                        "блюз"),
    (["симфони", "камерн", "опер", "сонат", "классическ"],                    "классика"),
    (["хор сретен", "мужской хор", "женский хор", "детский хор", "хоровой"], "хоровая"),
    (["оркестр русских народных", "народный оркестр"],                         "классика"),
    (["духовой оркестр", "эстрадно-духовой", "духовой ансамбль"],              "классика"),
    (["этно", "этническ", "уутай"],                                           "этно"),
    (["народн", "народная", "фолк", "folk"],                                   "фолк"),
    (["авторская", "авторские", "авторской"],                                  "авторская"),
    (["музыкальное лото", "угадыванием хитов", "музыкальный квиз"],           "интерактив"),
    (["инди", "indie"],                                                        "инди"),
    (["лаунж", "lounge"],                                                      "лаунж"),
    (["при свечах", "легенды 90", "легенды мтв", "легенды mtv", "суперхиты 90"], "поп"),
    (["поп-рок", "рок-поп", "pop-rock"],                                      "поп-рок"),
    (["русский рок", "русских рок", "каверы на рок", "рок-хиты", "рок хиты"],"русский рок"),
    (["рок", "rock"],                                                          "рок"),
    (["поп", "pop"],                                                           "поп"),
    (["квн", "юмор", "комедия", "стендап"],                                   "юмор"),
    (["кавер", "cover"],                                                       "каверы"),
    (["трибьют", "tribute"],                                                   "рок"),
    (["киномаёвка", "кинофест"],                                               "поп"),
    (["песни побед", "день побед", "9 мая", "военн", "катюш"],                "поп"),
    (["виолончель", "cello", "виолончели"],                                    "классика"),
    (["скрипач", "скрипка", "скрипк"],                                         "классика"),
    (["пианин", "фортепиано", "рояль"],                                        "классика"),
    (["балет", "танц"],                                                        "другое"),
    (["кельтск", "средневеков", "барбакан"],                                   "фолк"),
    (["drum'n'bass", "drum and bass", "dnb", "breakbeat"],                    "поп"),
    (["trance", "goa trance", "транс"],                                        "поп"),
    (["jungle", "джангл"],                                                     "поп"),
    (["house", "хаус", "mtv hits", "mtv хиты"],                                "поп"),
    (["диско", "disco", "disco time"],                                         "поп"),
    (["dj-сет", "dj сет", "dj"],                                               "поп"),
    (["живая музыка на пляже", "живая музыка на набережной"],                  "поп"),
    (["настойк", "дегустац"],                                                  "другое"),
    (["сказки с оркестром", "незнайк"],                                        "классика"),
    (["чехов в музыке"],                                                       "классика"),
    (["песни любимого кино", "песни из кино"],                                 "поп"),
    (["самая красивая музыка"],                                                "классика"),
    (["танцуем все", "танцевальная вечеринка"],                                "поп"),
    (["открытие фестиваля", "открытие сезона"],                                "поп"),
]


def detect_genre(event: dict) -> "str | None":
    ch = (event.get("source_channel") or "").lower()
    for key, genre in _CHANNEL_GENRES.items():
        if key in ch:
            return genre
    text = " ".join(filter(None, [
        event.get("description") or "",
        event.get("artist") or "",
        event.get("event_type") or "",
    ])).lower()
    for keywords, genre in _GENRE_RULES:
        if any(kw in text for kw in keywords):
            return genre
    etype = (event.get("event_type") or "").lower()
    if etype in ("трибьют", "tribute"):
        return "рок"
    if etype == "вечеринка":
        return "поп"
    if etype == "фестиваль":
        return "рок"
    if etype == "концерт":
        return "поп"
    return None


# ── Артисты-фолбэк ─────────────────────────────────────────────────────────

def _extract_artist_from_description(desc: str) -> "str | None":
    if not desc:
        return None
    patterns = [
        r"[Вв]ыступление\s+([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)(?:\s+в\s+|\s+на\s+|\s+—\s+|\s+исполняет|\s+с\s+лидером|\s+—\s+|\s+\(|$)",
        r"([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)\s+выступает",
        r"[Кк]онцерт\s+(?:дуэта\s+)?(?:группы\s+)?([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)(?:\s+в\s+|\s+на\s+|\s+—\s+|\s+от\s+|$)",
        r"[Жж]ивая\s+музыка[:\s]+([А-ЯЁ][А-Яа-яё«»\s\-\.\,]+?)(?:\s+—\s+|\s+на\s+|\s+в\s+|$)",
        r"DJ\s+([А-ЯЁA-Za-z][А-Яа-яёA-Za-z0-9\s\-\,]+?)(?:\s+—\s+|\s+сет|\s+в\s+|$)",
        r"DJ-сет\s+(?:с\s+)?([А-ЯЁA-Za-z][А-Яа-яёA-Za-z0-9\s\-\,]+?)(?:\s+с\s+|\s+до\s+|$)",
        r"группа\s+«([^»]+)»",
        r"«([^»]+)»\s+исполняет",
    ]
    for pat in patterns:
        m = re.search(pat, desc)
        if m:
            artist = m.group(1).strip().rstrip(".,")
            if 2 < len(artist) < 80:
                return artist
    return None


# Безусловные плейсхолдеры, которые может вернуть _fallback_artist — не имя
# исполнителя, а тип мероприятия (в отличие от веток с извлечением реального
# названия из кавычек типа «Концерт «X»» — те МОГУТ совпасть с настоящим
# артистом, поэтому в этот список не входят).
_GENERIC_ARTIST_LITERALS = {
    "Музыкальное лото", "DJ-сет", "Звукотерапия", "Квартирник", "Спектакль",
    "Фестиваль", "Живой концерт", "Музыкальный вечер", "Летний концерт",
    "Живой звук", "Открытие сезона", "Литературно-музыкальная гостиная",
    "Открытие летнего сезона", "Вечеринка", "Дегустация",
    "Массовое мероприятие", "Этно-проект",
}


def _fallback_artist(event: dict) -> "str | None":
    """Фолбэк артиста по event_type и описанию.
    Возвращает None для случаев, где нет реального исполнителя
    (это не музыкальные мероприятия с конкретным артистом)."""
    import re
    etype = (event.get("event_type") or "").lower()
    desc = event.get("description") or ""
    desc_lower = desc.lower()

    # Музыкальное лото / квиз — не музыкальное мероприятие с артистом
    if "музыкальное лото" in desc_lower or "музыкальный квиз" in desc_lower:
        return None

    # DJ-сеты без имени — не конкретный артист
    if etype == "вечеринка" and ("dj" in desc_lower or "диджей" in desc_lower):
        return None

    # Звукотерапия / медитация — не концерт
    if "звукотерап" in desc_lower or "тибетск" in desc_lower or "гонг" in desc_lower:
        return None

    # Квартирник / акустика без имени — не конкретный артист
    if "квартирник" in desc_lower:
        return None

    # Театральная постановка / спектакль — может быть мюзикл/опера, берём название из кавычек
    if "спектакль" in desc_lower or "театральная постановка" in desc_lower:
        m = re.search(r"«([^»]+)»", desc)
        if m:
            return m.group(1)
        return None  # Не возвращаем "Спектакль" как артиста

    # Фестиваль — берём название из описания, если есть в кавычках
    if etype == "фестиваль":
        m = re.search(r"«([^»]+)»", desc)
        if m:
            return m.group(1)
        return None  # Не возвращаем "Фестиваль" как артиста

    # Концерт — ищем название в кавычках
    if etype == "концерт":
        for pat in [r"[Кк]онцерт\s+«([^»]+)»", r"«([^»]+)»"]:
            m = re.search(pat, desc)
            if m:
                return m.group(1)
        # "Живой концерт X" / "Летний концерт" — не конкретный артист
        m = re.search(r"[Жж]ивой\s+концерт\s+«([^»]+)»", desc)
        if m:
            return m.group(1)
        return None  # Не возвращаем generic названия

    # Вечеринка — не конкретный артист
    if etype == "вечеринка":
        return None

    # Дегустация — не музыкальное мероприятие
    if "дегустац" in desc_lower:
        return None

    return None


def is_generic_artist(event: dict) -> bool:
    """True, если event['artist'] — не имя исполнителя, а тип мероприятия
    («DJ-сет», «Музыкальное лото», «Фестиваль» и т.п.), либо событие явно
    помечено флагом artist_is_generic.

    Сверяется с фиксированным списком безусловных плейсхолдеров
    (_GENERIC_ARTIST_LITERALS), а не пересчитывает _fallback_artist заново —
    иначе ветки с извлечением реального названия из кавычек («Концерт «X»»)
    ложно считались бы generic, если название совпало с уже настоящим
    значением artist (так ловилось «Скажите Джаз» — реальная джаз-группа).
    Применим и к событиям без проставленного флага (старые записи в
    events.json из прошлых прогонов).
    """
    if event.get("artist_is_generic"):
        return True
    return (event.get("artist") or "").strip() in _GENERIC_ARTIST_LITERALS


# ── Стабильный ID ───────────────────────────────────────────────────────────

def _make_id(event: dict) -> str:
    key = f"{event.get('source_url','')}-{event.get('date','')}-{event.get('artist','')}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


# ── Нормализация и дедупликация ─────────────────────────────────────────────

def _normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[«»\"'']", "", text)
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_venue(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[«»\"'']", "", text)
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    stops = {"отель", "resort", "spa", "palace", "дворец", "гостиница", "inn",
             "hotel", "club", "дк", "кдк", "дом культуры", "дворец культуры", "зал"}
    words = [w for w in text.split() if w not in stops]
    return " ".join(words).strip()


def _venue_match(v1: str, v2: str) -> bool:
    w1 = set(_normalize_venue(v1).split())
    w2 = set(_normalize_venue(v2).split())
    if not w1 or not w2:
        return False
    if w1 & w2:
        return True
    return any(
        len(a) >= 5 and len(b) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.86
        for a in w1 for b in w2
    )


def _split_artist_field(artist: str) -> list[str]:
    """Разбивает поле artist по запятым верхнего уровня — не внутри скобок/«».

    Наивный artist.split(",") ломает случаи вроде «Дуэт «МысКрыма»
    (Дмитрий Ванханов, Вета)», где запятая — часть перечисления внутри
    скобок, а не разделитель артистов.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in artist:
        if ch in "(«":
            depth += 1
            current.append(ch)
        elif ch in ")»":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


_ARTIST_JOIN_RE = re.compile(
    r'\s+(и|&|\+|feat\.?|ft\.?|при участии|с участием)\s+', re.IGNORECASE,
)
_ARTIST_JOIN_WORDS = {"и", "&", "+", "feat", "feat.", "ft", "ft.",
                      "при участии", "с участием"}


def _artist_parts(name: str) -> list[str]:
    """Разбивает имя по «и»/«&»/«+»/feat. и т.п. — не внутри скобок/«».

    Наивный regex.split() ломает случаи вроде «МыКрымы (Диана Ванх и Вета)»,
    где «и» — часть перечисления внутри скобок, а не разделитель артистов.
    """
    depth = 0
    depths = []
    for ch in name:
        if ch in "(«":
            depth += 1
        elif ch in ")»":
            depth = max(0, depth - 1)
        depths.append(depth)
    parts = []
    last = 0
    for m in _ARTIST_JOIN_RE.finditer(name):
        start, end = m.span()
        if start < len(depths) and depths[start] == 0:
            parts.append(name[last:start])
            last = end
    parts.append(name[last:])
    return [p.strip() for p in parts
            if p.strip() and p.strip().lower() not in _ARTIST_JOIN_WORDS]


# Транслит для сравнения имён между кириллицей и латиницей (SHAMAN vs ШАМАН).
# Таблица та же, что в build_venues.py:slugify, для единообразия.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit_key(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in _normalize(text))


def _artist_set(event: dict) -> set:
    artist = event.get("artist") or ""
    names = set()
    for raw in _split_artist_field(artist):
        for name in _artist_parts(raw.strip()):
            n = _normalize(name)
            for prefix in ("группа ", "band ", "«"):
                if n.startswith(prefix):
                    n = n[len(prefix):].strip()
            if n:
                names.add(n)
                names.add(_translit_key(n))  # ловит кириллица/латиница дубли
    return names


def _bare_artist_key(text: str) -> str:
    k = _normalize(text)
    for p in ("группа", "band"):
        if k.startswith(p):
            k = k[len(p):].strip()
    return k


def _artists_look_alike(a: str, b: str) -> bool:
    """Нечёткое сравнение вариантов одного имени для дедупликации."""
    ka = _bare_artist_key(re.sub(r"\([^)]*\)", "", a))
    kb = _bare_artist_key(re.sub(r"\([^)]*\)", "", b))
    if not ka or not kb:
        return False
    if ka in kb or kb in ka:
        return True
    return difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.86


_NON_MUSIC_PREFIXES = (
    "экскурсия", "лекция", "мастер-класс", "кинопоказ", "выставка", "standup", "стендап", "музлото",
)


def is_non_music_event(event: dict) -> bool:
    """Отсекает явно немузкальные карточки, ошибочно извлечённые как события."""
    artist = _normalize(event.get("artist") or "")
    event_type = _normalize(event.get("event_type") or "")
    return artist.startswith(_NON_MUSIC_PREFIXES) or event_type in {
        "экскурсия", "лекция", "мастер класс", "кинопоказ", "выставка", "standup", "стендап", "музлото",
    }


def _field_count(e: dict) -> int:
    fields = ("date", "time", "artist", "event_type", "venue", "price", "description", "source_city")
    return sum(1 for f in fields if e.get(f))


def _merge_events(group: list[dict]) -> dict:
    group_sorted = sorted(group, key=lambda e: e.get("post_date") or "", reverse=True)
    best = max(group, key=_field_count)
    merged = {}
    for field in ("id", "date", "time", "artist", "event_type", "venue", "price",
                  "description", "source_city", "source_channel", "genre"):
        for e in group_sorted:
            v = e.get(field)
            if v and str(v).strip():
                merged[field] = v
                break
        else:
            merged[field] = None
    merged["source_url"] = best.get("source_url") or group_sorted[0].get("source_url")
    all_images = []
    for e in group_sorted:
        img = e.get("image")
        if img and img not in all_images:
            all_images.append(img)
    best_img = best.get("image")
    if best_img and best_img in all_images:
        all_images.remove(best_img)
        all_images.insert(0, best_img)
    merged["images"] = all_images if all_images else None
    merged["image"] = all_images[0] if all_images else None
    merged["post_date"] = group_sorted[0].get("post_date")
    return merged


def _merge_group(group: list[dict]) -> dict:
    merged = _merge_events(group)
    seen: set = set()
    artists: list = []
    for e in group:
        for a in _split_artist_field(e.get("artist") or ""):
            for name in _artist_parts(a.strip()):
                bare = _bare_artist_key(name)
                if not name or bare in seen:
                    continue
                seen.add(bare)
                is_sub = False
                for other in artists[:]:
                    obare = _bare_artist_key(other)
                    if bare and obare and (bare in obare or obare in bare):
                        if len(bare) >= len(obare):
                            artists.remove(other)
                        else:
                            is_sub = True
                            break
                if not is_sub:
                    artists.append(name)
    merged["artist"] = ", ".join(artists) if artists else None
    return merged


def deduplicate_events(events: list[dict]) -> list[dict]:
    by_post: dict[tuple, list] = {}
    no_url: list[dict] = []
    for event in events:
        url = event.get("source_url") or ""
        date = event.get("date") or ""
        if url and date:
            by_post.setdefault((date, url), []).append(event)
        else:
            no_url.append(event)
    stage1: list[dict] = []
    for group in by_post.values():
        stage1.append(_merge_group(group) if len(group) > 1 else group[0])
    stage1.extend(no_url)

    n = len(stage1)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    by_date: dict[str, list[int]] = {}
    for i, e in enumerate(stage1):
        by_date.setdefault(e.get("date") or "", []).append(i)

    for indices in by_date.values():
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                i, j = indices[a], indices[b]
                ci = (stage1[i].get("source_city") or "").strip()
                cj = (stage1[j].get("source_city") or "").strip()
                if ci and cj and ci.lower() != cj.lower():
                    continue  # разные города — точно разные события
                ai = _artist_set(stage1[i])
                aj = _artist_set(stage1[j])
                vi = stage1[i].get("venue") or ""
                vj = stage1[j].get("venue") or ""
                ti = stage1[i].get("time") or ""
                tj = stage1[j].get("time") or ""
                same_venue = bool(vi and vj and _venue_match(vi, vj))
                if ai and aj and ai & aj and (same_venue or not vi or not vj):
                    union(i, j)
                elif same_venue and _artists_look_alike(
                    stage1[i].get("artist") or "",
                    stage1[j].get("artist") or "",
                ):
                    union(i, j)
                elif same_venue and ti and tj and ti == tj:
                    union(i, j)

    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(stage1[i])
    return [_merge_group(g) if len(g) > 1 else g[0] for g in groups.values()]


# ── Нечёткий матч площадок ─────────────────────────────────────────────────

def _build_venue_index(venues: list) -> dict:
    """Все известные варианты названий (норм.) → (slug, canonical_name)."""
    index = {}
    for v in venues:
        canonical = v["name"]
        slug = v["slug"]
        for variant in [canonical] + v.get("aliases", []):
            key = _normalize_venue(variant)
            if key:
                index[key] = (slug, canonical)
    return index


def _fuzzy_match_venue(incoming: str, venue_index: dict) -> "tuple[str, str] | None":
    """
    Ищет ближайшую площадку из venue_index для строки incoming.
    Возвращает (slug, canonical_name) при уверенном совпадении, иначе None.
    Порог: subset_score или seq_score ≥ 0.65.
    """
    norm_in = _normalize_venue(incoming)
    if not norm_in:
        return None
    if norm_in in venue_index:
        return venue_index[norm_in]

    tokens_in = {t for t in norm_in.split() if len(t) > 2 and not t.isdigit()}
    if not tokens_in:
        return None

    best_score = 0.0
    best_match = None
    for known_norm, (slug, canonical) in venue_index.items():
        tokens_known = {t for t in known_norm.split() if len(t) > 2 and not t.isdigit()}
        if not tokens_known:
            continue
        # токены меньшего множества целиком входят в большее
        if tokens_known <= tokens_in:
            subset_score = len(tokens_known) / len(tokens_in)
        elif tokens_in <= tokens_known:
            subset_score = len(tokens_in) / len(tokens_known)
        else:
            subset_score = 0.0
        seq_score = difflib.SequenceMatcher(None, norm_in, known_norm).ratio()
        score = max(subset_score, seq_score)
        if score > best_score:
            best_score = score
            best_match = (slug, canonical)

    return best_match if best_score >= 0.65 else None


def resolve_venues(events: list, venues_data: list) -> tuple:
    """
    Для каждого события пытается сопоставить venue с venues.json.
    Если совпадение найдено — подставляет canonical name и добавляет
    исходную строку как алиас (если её ещё нет).
    Возвращает (modified_venues_data, aliases_added).
    """
    venue_index = _build_venue_index(venues_data)
    venues_by_slug = {v["slug"]: v for v in venues_data}
    aliases_added = []

    for event in events:
        venue = event.get("venue")
        if not venue:
            continue
        norm = _normalize_venue(venue)
        if norm in venue_index:
            _, canonical = venue_index[norm]
            event["venue"] = canonical
            continue
        match = _fuzzy_match_venue(venue, venue_index)
        if match:
            slug, canonical = match
            event["venue"] = canonical
            v = venues_by_slug.get(slug)
            if v:
                aliases = set(v.get("aliases", []))
                if venue not in aliases:
                    aliases.add(venue)
                    v["aliases"] = sorted(aliases)
                    venue_index[norm] = (slug, canonical)
                    aliases_added.append(f"«{venue}» → {canonical}")

    return venues_data, aliases_added


# ── Main ────────────────────────────────────────────────────────────────────

def main(push: bool = True):
    # Загружаем новые события (от Claude) и Яндекс.Афишу
    new_events: list[dict] = []

    if os.path.exists(EXTRACTED_FILE):
        with open(EXTRACTED_FILE, encoding="utf-8") as f:
            new_events = json.load(f)
        print(f"Telegram-события: {len(new_events)}")
    else:
        print(f"{EXTRACTED_FILE} не найден — только Яндекс.Афиша")

    if os.path.exists(YANDEX_FILE):
        with open(YANDEX_FILE, encoding="utf-8") as f:
            yandex = json.load(f)
        print(f"Яндекс.Афиша: {len(yandex)}")
        new_events.extend(yandex)
    else:
        print(f"{YANDEX_FILE} не найден")

    if os.path.exists(AFISHA_FILE):
        with open(AFISHA_FILE, encoding="utf-8") as f:
            afisha = json.load(f)
        print(f"Афиша (afisha.ru): {len(afisha)}")
        new_events.extend(afisha)
    else:
        print(f"{AFISHA_FILE} не найден")

    invalid_dates = _sanitize_event_dates(new_events)
    if invalid_dates:
        print(f"Очищено некорректных дат: {invalid_dates}")
    normalized_times, invalid_times = _sanitize_event_times(new_events)
    if normalized_times or invalid_times:
        print(f"Время: нормализовано {normalized_times}, очищено {invalid_times}")

    # Нечёткий матч площадок → canonical names + автоалиасы
    venues_file = "venues.json"
    venues_data: list[dict] = []
    if os.path.exists(venues_file):
        with open(venues_file, encoding="utf-8") as f:
            venues_data = json.load(f)
    venues_data, aliases_added = resolve_venues(new_events, venues_data)
    if aliases_added:
        with open(venues_file, "w", encoding="utf-8") as f:
            json.dump(venues_data, f, ensure_ascii=False, indent=2)
        for a in aliases_added:
            print(f"  Алиас: {a}")

    # Явно немузкальные события не должны попадать в музыкальную афишу.
    new_events = [e for e in new_events if not is_non_music_event(e)]

    # Дедупликация новых
    before = len(new_events)
    new_events = deduplicate_events(new_events)
    print(f"Дедупликация новых: {before} → {len(new_events)}")

    # Загружаем архив
    existing: list[dict] = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    old_invalid_dates = _sanitize_event_dates(existing)
    old_normalized_times, old_invalid_times = _sanitize_event_times(existing)
    if old_invalid_dates or old_normalized_times or old_invalid_times:
        print(f"Архив очищен: дат {old_invalid_dates}, "
              f"времён нормализовано {old_normalized_times}, очищено {old_invalid_times}")

    # Один URL (афиша на неделю, страница тура) может содержать
    # несколько дат. Мерджим весь свежий набор и полагаемся на
    # deduplicate_events, чтобы повторный запуск не плодил дубли.
    merged_raw = [e for e in existing + new_events if not is_non_music_event(e)]

    before2 = len(merged_raw)
    merged = deduplicate_events(merged_raw)
    existing_ids = {e.get("id") for e in existing if e.get("id")}
    truly_new_count = sum(1 for e in merged if not e.get("id") or e.get("id") not in existing_ids)
    print(f"Новых: {truly_new_count}, было: {len(existing)}, итого: {len(merged)} (убрано дублей: {before2 - len(merged)})")

    # Убираем события-призраки
    ghost_artists = {"живой звук", "музыкальный вечер", "концерт", "живой концерт"}
    by_source: dict[str, list] = {}
    for i, e in enumerate(merged):
        by_source.setdefault(e.get("source_url") or "", []).append(i)
    keep = set(range(len(merged)))
    for url, indices in by_source.items():
        if len(indices) < 2 or not url:
            continue
        descs = {merged[i].get("description", "") for i in indices}
        if len(descs) == 1:
            artists = {_normalize(merged[i].get("artist") or "") for i in indices}
            if artists & ghost_artists:
                for i in indices:
                    keep.discard(i)
    merged = [e for i, e in enumerate(merged) if i in keep]

    # Чистим имена артистов от дублей
    for e in merged:
        if not e.get("artist"):
            continue
        artist = _to_scalar(e["artist"])
        if not artist:
            continue
        parts = _artist_parts(artist)
        by_bare: dict[str, list[str]] = {}
        for name in parts:
            bare = _bare_artist_key(name)
            if bare:
                by_bare.setdefault(bare, []).append(name)
        cleaned: list[str] = []
        for bare in sorted(by_bare, key=len):
            best = min(by_bare[bare], key=len)
            is_sub = False
            for other in cleaned[:]:
                obare = _bare_artist_key(other)
                if bare in obare or obare in bare:
                    if len(bare) < len(obare):
                        cleaned.remove(other)
                    else:
                        is_sub = True
                    break
            if not is_sub:
                cleaned.append(best)
        e["artist"] = ", ".join(cleaned) if cleaned else None

    # Жанр и артист-фолбэк
    genre_added = artist_added = 0
    for e in merged:
        if not e.get("artist"):
            extracted = _extract_artist_from_description(e.get("description") or "")
            if extracted:
                # Извлечено из кавычек/паттерна — попытка настоящего имени,
                # флаг generic не ставим.
                e["artist"] = extracted
                artist_added += 1
            else:
                fb = _fallback_artist(e)
                if fb:
                    e["artist"] = fb
                    e["artist_is_generic"] = fb in _GENERIC_ARTIST_LITERALS
                    artist_added += 1
        if not e.get("genre"):
            g = detect_genre(e)
            if g:
                e["genre"] = g
                genre_added += 1

    if artist_added:
        print(f"Артист-фолбэк: {artist_added} событий")
    if genre_added:
        print(f"Жанр определён: {genre_added} событий")

    def _all_artists_generic(artist_str: str) -> bool:
        """True если все части артиста — generic плейсхолдеры."""
        if not artist_str:
            return True
        parts = _split_artist_field(artist_str)
        for part in parts:
            for name in _artist_parts(part.strip()):
                bare = _bare_artist_key(name)
                if bare and bare not in _GENERIC_ARTIST_LITERALS:
                    return False
        return True

    # Фильтруем события без реального исполнителя
    before_artist_filter = len(merged)
    merged = [e for e in merged if e.get("artist") and not _all_artists_generic(e["artist"])]
    removed_no_artist = before_artist_filter - len(merged)
    if removed_no_artist:
        print(f"Убрано событий без реального исполнителя: {removed_no_artist}")

    # Назначаем стабильный id (сохраняем существующий, генерируем для новых)
    for e in merged:
        if not e.get("id"):
            e["id"] = _make_id(e)

    # Проверка на коллизии ID
    from collections import Counter
    id_counts = Counter(e["id"] for e in merged if e.get("id"))
    for dup_id, count in id_counts.items():
        if count > 1:
            dupes = [e for e in merged if e.get("id") == dup_id]
            print(f"⚠️  Коллизия ID {dup_id}: {count} событий")
            for d in dupes:
                print(f"    -> {d.get('artist')} | {d.get('date')} | {d.get('source_url','')}")

    # Проставляем updated_at: now — для новых и изменившихся событий
    from datetime import date, datetime, timezone
    existing_by_id = {e["id"]: e for e in existing if e.get("id")}
    _TRACKED_FIELDS = ("date", "time", "artist", "venue", "price")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Заведомо прошедшая метка для событий-легаси без нормального updated_at
    # (см. _normalize_updated_at) — не now_iso, чтобы не устраивать им ещё
    # одну повторную рассылку: раз они и так уже разошлись подписчикам
    # (в этом и была причина бага), считаем их старыми, а не свежими.
    _LEGACY_EPOCH = "1970-01-01T00:00:00+00:00"

    def _normalize_updated_at(old_event: dict) -> str:
        # До 2026-07-02 у событий не было updated_at, и тогдашний фолбэк по
        # ошибке подставлял голую дату события (post_date, YYYY-MM-DD) —
        # такая строка при сравнении с полным ISO-timestamp в боте
        # сравнивается лексикографически неверно (а для событий с afisha,
        # где post_date совпадает с датой самого события, дала бы дату в
        # будущем, что тоже сломало бы сравнение). Чиним при каждом прогоне.
        prev = old_event.get("updated_at")
        return prev if prev and len(prev) > 10 else _LEGACY_EPOCH

    for e in merged:
        eid = e.get("id")
        old = existing_by_id.get(eid) if eid else None
        if old is None:
            e["updated_at"] = now_iso
        else:
            changed = any(e.get(f) != old.get(f) for f in _TRACKED_FIELDS)
            e["updated_at"] = now_iso if changed else _normalize_updated_at(old)

    # Сортировка: будущие по дате вперёд, прошедшие в конце по убыванию даты
    today = date.today().isoformat()
    future = sorted([e for e in merged if (e.get("date") or "") >= today],
                    key=lambda e: (e.get("date") or "", e.get("time") or ""))
    past = sorted([e for e in merged if (e.get("date") or "") < today],
                  key=lambda e: (e.get("date") or ""), reverse=True)
    merged = future + past
    print(f"Будущих: {len(future)}, прошедших: {len(past)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Сохранено → {OUTPUT_FILE}")

    if push:
        to_add = [OUTPUT_FILE, "images/events/"]
        if aliases_added:
            to_add.append(venues_file)
        subprocess.run(["git", "add"] + to_add, check=False)
        subprocess.run(["git", "commit", "-m", "parser: обновить events.json [автоматически]"], check=False)
        result = subprocess.run(["git", "push"], check=False)
        if result.returncode == 0:
            print("Запушено на GitHub Pages.")
        else:
            print("git push не удался.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="Не пушить в git")
    args = ap.parse_args()
    main(push=not args.no_push)
