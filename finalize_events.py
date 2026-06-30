"""
Шаг 3: принимает извлечённые события (extracted_events.json + yandex_events.json),
мёрджит с архивом events.json, дедуплицирует, определяет жанры, пушит на GitHub.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

OUTPUT_FILE = "events.json"
EXTRACTED_FILE = "extracted_events.json"
YANDEX_FILE = "yandex_events.json"
AFISHA_FILE = "afisha_events.json"

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


def _fallback_artist(event: dict) -> "str | None":
    etype = (event.get("event_type") or "").lower()
    desc = event.get("description") or ""
    desc_lower = desc.lower()
    if "музыкальное лото" in desc_lower or "музыкальный квиз" in desc_lower:
        return "Музыкальное лото"
    if etype == "вечеринка" and ("dj" in desc_lower or "диджей" in desc_lower):
        return "DJ-сет"
    if "звукотерап" in desc_lower or "тибетск" in desc_lower or "гонг" in desc_lower:
        return "Звукотерапия"
    if "квартирник" in desc_lower:
        return "Квартирник"
    if "спектакль" in desc_lower or "театральная постановка" in desc_lower:
        m = re.search(r"«([^»]+)»", desc)
        return f"Спектакль «{m.group(1)}»" if m else "Спектакль"
    if etype == "фестиваль":
        m = re.search(r"«([^»]+)»", desc)
        return m.group(1) if m else "Фестиваль"
    if etype == "концерт":
        for pat in [r"[Кк]онцерт\s+«([^»]+)»", r"«([^»]+)»"]:
            m = re.search(pat, desc)
            if m:
                return m.group(1)
        if "живой концерт" in desc_lower:
            return "Живой концерт"
        if "музыкальный вечер" in desc_lower:
            return "Музыкальный вечер"
        if "летний концерт" in desc_lower:
            return "Летний концерт"
        if "живой звук" in desc_lower or "живого звука" in desc_lower:
            return "Живой звук"
        if "открытие сезона" in desc_lower:
            return "Открытие сезона"
        if "литературно-музыкальная" in desc_lower:
            m = re.search(r"«([^»]+)»", desc)
            return m.group(1) if m else "Литературно-музыкальная гостиная"
    if etype == "вечеринка":
        return "Вечеринка"
    if "дегустац" in desc_lower:
        return "Дегустация"
    return None


# ── Стабильный ID ───────────────────────────────────────────────────────────

def _make_id(event: dict) -> str:
    key = event.get("source_url") or f"{event.get('artist','')}-{event.get('date','')}-{event.get('venue','')}"
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
    return bool(w1 and w2 and w1 & w2)


def _artist_parts(name: str) -> list[str]:
    result = re.split(r'\s+(и|&|\+)\s+', name)
    return [p.strip() for p in result if p.strip() and p.strip() not in ("и", "&", "+")]


def _artist_set(event: dict) -> set:
    artist = event.get("artist") or ""
    names = set()
    for raw in artist.split(","):
        for name in _artist_parts(raw.strip()):
            n = _normalize(name)
            for prefix in ("группа ", "band ", "«"):
                if n.startswith(prefix):
                    n = n[len(prefix):].strip()
            if n:
                names.add(n)
    return names


def _bare_artist_key(text: str) -> str:
    k = _normalize(text)
    for p in ("группа", "band"):
        if k.startswith(p):
            k = k[len(p):].strip()
    return k


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
        for a in (e.get("artist") or "").split(","):
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
                ai = _artist_set(stage1[i])
                aj = _artist_set(stage1[j])
                vi = stage1[i].get("venue") or ""
                vj = stage1[j].get("venue") or ""
                ti = stage1[i].get("time") or ""
                tj = stage1[j].get("time") or ""
                if ai and aj and ai & aj:
                    union(i, j)
                elif vi and vj and _venue_match(vi, vj) and ti and tj and ti == tj:
                    union(i, j)

    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(stage1[i])
    return [_merge_group(g) if len(g) > 1 else g[0] for g in groups.values()]


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

    existing_urls = {e["source_url"] for e in existing if e.get("source_url")}
    truly_new = [e for e in new_events if e.get("source_url") not in existing_urls]
    merged_raw = existing + truly_new

    before2 = len(merged_raw)
    merged = deduplicate_events(merged_raw)
    print(f"Новых: {len(truly_new)}, было: {len(existing)}, итого: {len(merged)} (убрано дублей: {before2 - len(merged)})")

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
        parts = _artist_parts(e["artist"])
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
            fb = _extract_artist_from_description(e.get("description") or "") or _fallback_artist(e)
            if fb:
                e["artist"] = fb
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

    # Назначаем стабильный id (сохраняем существующий, генерируем для новых)
    for e in merged:
        if not e.get("id"):
            e["id"] = _make_id(e)

    # Сортировка: будущие по дате вперёд, прошедшие в конце по убыванию даты
    from datetime import date
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
        subprocess.run(["git", "add", OUTPUT_FILE, "images/events/"], check=False)
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
