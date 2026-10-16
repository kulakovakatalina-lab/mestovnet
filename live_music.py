"""Conservative, source-independent admission policy for NEW event candidates.

Existing catalogue rows must never be passed here for retroactive cleanup.
No network/model calls: decisions are reproducible and include their evidence.
"""
import re
import unicodedata
from dataclasses import dataclass

POLICY_VERSION = "live-music-v1"


def _text(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[‐‑‒–—−]", "-", value)).strip()


def _find(pattern, text):
    return re.search(pattern, text, re.I)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    evidence: str = ""


# Main format signals, rather than unbounded substring blacklists.
_FORMATS = (
    ("education", r"\b(?:интенсив\w*|мастер[- ]класс\w*|обучени\w*|танцевальн\w* класс\w*|курс(?:ы|а|ов)? (?:dj|дидже\w*|вокал\w*|танц\w*))\b"),
    ("practice", r"\b(?:женск\w* круг\w*|мужск\w* круг\w*|интуитивн\w* тан\w*|ecstatic[- ](?:dance|дэнс)|экстатик[- ]д[эе]нс\w*|звукотерапевтическ\w* сеанс\w*|звукотерапи\w*|звуков\w* ванн\w*|медитаци\w*|ритуал\w*|церемони\w*|йога[- ]практик\w*)\b"),
    ("music_game", r"\b(?:муз[- ]?лото|(?:музыкальн\w*|рок)[- ]лото|музыкальн\w* (?:квиз\w*|бинго)|квиз\w*|угадай мелодию)\b"),
    ("karaoke", r"\b(?:караоке|каоке|юбокс\w*|jukebox)\b"),
    ("non_music", r"\b(?:stand[- ]?up|стенд[- ]?ап\w*|квн|лекци\w*|кинопоказ\w*|кино под (?:звездами|открытым небом)|показ фильма|экскурси\w*|прогулк\w*|посещение дома[- ]музея|забег\w*|выставк\w*|показ\w* мод|поэтическ\w* вечер\w*|вечер\w* поэзии|спектакл\w*|чтени\w* стих\w*|пиво[- ]понг|beerpong|профориентационн\w*)\b"),
    ("dj_only", r"\b(?:dj(?:[- ](?:сет\w*|set))?|дидже[йяеюи]\w*|винил\w*|vinyl(?: set)?|за (?:пультом|вертушками))\b"),
)
_INSTRUMENT = r"(?:фортепиано|пианист\w*|скрипк\w*|саксофон\w*|клавиш\w*|гитар\w*|контрабас\w*|ударн\w*|виолончел\w*|перкусси\w*|флейт\w*|синтезатор\w*|драм[- ]машин\w*|лупер\w*)"
_LIVE = rf"\b(?:жив(?:ая|ую|ой|ое|ые|ом) (?:музык\w*|звук\w*|вокал\w*|исполнени\w*|{_INSTRUMENT})|вокал\w*|{_INSTRUMENT}|оркестр\w*|хор(?:а|ом)?|джаз[- ]трио|акустик\w*)\b"
_CONCERT = r"\b(?:концерт\w*|трибьют\w*|tribute|джем\w*)\b"
# An explicit musical block can rescue a mixed programme, not just the word concert.
_PERFORMANCE = rf"\b(?:(?:концерт|выступление) (?:группы|оркестра|хора|ансамбля|певиц\w*|пианист\w*|скрипач\w*)|(?:группа|оркестр|хор|ансамбль) [^.!?]{{0,70}}(?:выступ\w*|сыгра\w*|исполн\w*)|(?:исполнит|сыграет|споет|исполняет|исполняют)\b[^.!?]{{0,100}}(?:песн\w*|хит\w*|романс\w*|произведени\w*|музык\w*))"
_GENERIC = r"(?:живая музыка|музыкальный вечер|лаунж[- ]музыка|dj[- ]?сеты?|диджей|неизвестно|не указано|концерт|фестиваль)"


def classify_event(event):
    """Return publish / ignore / review without trusting event_type or LLM labels.

    Only event-specific title/description and a verified source excerpt are used.
    A whole weekly post must never become evidence for all of its candidates.
    """
    title = _text(event.get("artist"))
    description = _text(event.get("description"))
    # Parser sets this private field only after checking a verbatim model excerpt.
    excerpt = _text(event.get("_live_music_source_excerpt"))
    body = " ".join(filter(None, [description, excerpt]))
    text = f"{title}. {body}"
    # A negated DJ reference is not the format of the programme.
    text = re.sub(r"\bбез\s+(?:dj|дидже\w*)(?:[- ]сет\w*)?\b", "", text)
    specific_artist = bool(title and not re.fullmatch(_GENERIC, title))
    performance = _find(_PERFORMANCE, body)
    concert = _find(_CONCERT, text)
    live = _find(_LIVE, body)
    role_in_title = _find(rf"\b(?:вокал\w*|{_INSTRUMENT}|оркестр\w*|хор(?:а)?|групп\w*|band|trio|трио|дуэт)\b", title)
    # Do not confuse negated instrumentation with proof of a performance.
    if _find(r"\b(?:без|нет|никакой) жив\w* (?:музык\w*|вокал\w*|звук\w*)", body):
        return Decision("ignore", "no_live_performance", body[:200])

    for reason, pattern in _FORMATS:
        signal = _find(pattern, text)
        if not signal:
            continue
        if reason in {"education", "practice"}:
            if performance and concert:
                return Decision("publish", "separate_concert", performance.group())
            return Decision("ignore", reason, signal.group())
        if reason == "music_game":
            if performance:
                return Decision("publish", "separate_concert", performance.group())
            return Decision("ignore", reason, signal.group())
        if reason == "karaoke":
            if _find(r"\bоркестр\w*\b", text) or performance or (concert and (role_in_title or live)):
                return Decision("publish", "live_program_with_karaoke", (performance or live or concert or role_in_title or signal).group())
            if concert or role_in_title or _find(r"\b(?:cover|show)\b", title):
                return Decision("review", "conflicting_program", signal.group())
            return Decision("ignore", reason, signal.group())
        if reason == "non_music":
            if performance or (concert and live and specific_artist):
                return Decision("publish", "separate_concert", (performance or live).group())
            if live or role_in_title or (concert and not _find(r"\b(?:stand[- ]?up|стенд[- ]?ап\w*|квн)\b", text)):
                return Decision("review", "mixed_program", signal.group())
            return Decision("ignore", reason, signal.group())
        if reason == "dj_only":
            if performance or (specific_artist and (role_in_title or _find(r"\bвокал\w*\b", body))) or (concert and live and _find(r"\b(?:до|перед|затем|после)\b", body)):
                return Decision("publish", "live_program_with_dj", (performance or role_in_title or live).group())
            # Explicit live instruments but no stated programme: don't claim DJ only.
            if live or _find(r"\blive\b", text):
                return Decision("review", "mixed_program", signal.group())
            return Decision("ignore", reason, signal.group())

    if _find(r"\b(?:выпуст\w*|записал\w*)[^.!?]{0,60}\b(?:клип|трек|альбом|песню)\b|\b(?:трансляция|остановились в отеле)\b", body) and not performance:
        return Decision("ignore", "not_event", body[:200])
    if _find(r"\b(?:ужин\w*|дегустаци\w*|гриль[- ]вечер\w*|праздничн\w* гуляни\w*)\b", body) and not (performance or role_in_title):
        return Decision("review", "background_or_concert", body[:200])
    if performance or (specific_artist and (live or role_in_title)):
        return Decision("publish", "live_performance", (performance or live or role_in_title).group())
    if concert and specific_artist:
        return Decision("publish", "concert_program", concert.group())
    # Actual concert page is supporting context; event_type is often hardcoded.
    url = _text(event.get("source_url")).split("?", 1)[0]
    if specific_artist and _find(r"/concert/", url):
        return Decision("publish", "concert_source", "/concert/")
    return Decision("review", "insufficient_live_evidence", body[:200])
