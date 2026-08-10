#!/usr/bin/env python3
"""Отправка в Telegram списка того, что появилось за прогон парсера.

Сравнивает снимки реестров «до» и «после» прогона (events.json / venues.json /
artists.json) и отправляет сообщение со ссылками на новые события. По каждому
новому событию:
  1. название события (ссылка на страницу события)
  2. артист(ы) — каждый со ссылкой на страницу артиста
  3. заведение со ссылкой на страницу заведения
  4. ссылка на источник (пост в исходном канале)

Если новых событий нет — сообщение не отправляется, кроме случая
--notify-empty: тогда отправляется уведомление, что ничего нового не найдено.

Переменные окружения:
  TELEGRAM_BOT_TOKEN — токен бота (от @BotFather)
  TELEGRAM_CHAT_ID   — id получателя (число или @username)

Пример:
  python notify_new.py --before-dir /tmp/before --notify-empty
"""

import argparse
import html as html_escape
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx

import parser as parser_mod

DOMAIN = "https://mestov.net"

FILES = ("events.json", "venues.json", "artists.json")


def load(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def new_items(before: list[dict], after: list[dict], key: str) -> list[dict]:
    before_keys = {x.get(key) for x in before}
    return [x for x in after if x.get(key) and x.get(key) not in before_keys]


def build_alias_lookup(records: list[dict]) -> dict[str, str]:
    """raw имя/алиас → slug (та же логика, что в generate_pages.py)."""
    lookup: dict[str, str] = {}
    for r in records:
        for alias in r.get("aliases", []):
            alias = (alias or "").strip()
            if alias:
                lookup[alias] = r["slug"]
        name = (r.get("name") or "").strip()
        if name:
            lookup[name] = r["slug"]
    return lookup


def resolve_artist_names(raw: str, lookup: dict[str, str]) -> list[tuple[str, Optional[str]]]:
    """(имя, slug) для каждого артиста из поля artist (как resolve_artist_slugs)."""
    result: list[tuple[str, Optional[str]]] = []
    seen: set[str] = set()
    raw = (raw or "").strip()
    if not raw:
        return result
    for part in parser_mod._split_artist_field(raw):
        for name in parser_mod._artist_parts(part.strip()):
            name = name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            result.append((name, lookup.get(name)))
    return result


def esc(s: str) -> str:
    return html_escape.escape(s or "")


def render_event_block(e: dict, artist_lookup: dict, venue_lookup: dict) -> list[str]:
    lines: list[str] = []

    date = (e.get("date") or "").strip()
    venue = (e.get("venue") or "").strip()
    artist = (e.get("artist") or "").strip()

    # 1. Название события — ссылка на страницу события
    title_parts = [artist or "Событие"]
    if venue and venue != artist:
        title_parts.append(venue)
    if date:
        title_parts.append(date)
    title = " — ".join(p for p in title_parts if p)
    lines.append(f"<a href=\"{DOMAIN}/event/{e['id']}\">{esc(title)}</a>")

    # 2. Артист(ы) со ссылками
    artists = resolve_artist_names(artist, artist_lookup)
    if artists:
        links = []
        for name, slug in artists:
            if slug:
                links.append(f"<a href=\"{DOMAIN}/artist/{slug}\">{esc(name)}</a>")
            else:
                links.append(esc(name))
        lines.append(f"Артист: {', '.join(links)}")
    elif artist:
        lines.append(f"Артист: {esc(artist)}")

    # 3. Заведение со ссылкой
    if venue:
        slug = venue_lookup.get(venue)
        if slug:
            lines.append(f"Заведение: <a href=\"{DOMAIN}/venues/{slug}\">{esc(venue)}</a>")
        else:
            lines.append(f"Заведение: {esc(venue)}")

    # 4. Источник
    src = (e.get("source_url") or "").strip()
    if src:
        lines.append(f"Источник: <a href=\"{esc(src)}\">{esc(src)}</a>")

    return lines


def build_message(before_dir: Path, after_dir: Path) -> Optional[str]:
    before = {f: load(before_dir / f) for f in FILES}
    after = {f: load(after_dir / f) for f in FILES}

    new_events = new_items(before["events.json"], after["events.json"], "id")

    if not new_events:
        return None

    venue_lookup = build_alias_lookup(after["venues.json"])
    artist_lookup = build_alias_lookup(after["artists.json"])

    lines = [f"<b>Новое на Местов.Нет ({len(new_events)}):</b>"]
    for e in sorted(new_events, key=lambda x: (x.get("date") or "")):
        lines.append("")
        lines.extend(render_event_block(e, artist_lookup, venue_lookup))

    return "\n".join(lines)


def send(bot_token: str, chat_id: str, text: str) -> None:
    resp = httpx.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    resp.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-dir", required=True, help="каталог со снимками реестров до прогона")
    ap.add_argument("--after-dir", default=str(Path(__file__).parent),
                    help="каталог с актуальными реестрами (по умолчанию текущий)")
    ap.add_argument("--notify-empty", action="store_true",
                    help="отправить в Telegram «ничего нового», если новых событий не найдено")
    args = ap.parse_args()

    before_dir = Path(args.before_dir)
    after_dir = Path(args.after_dir)

    message = build_message(before_dir, after_dir)
    if message is None and not args.notify_empty:
        print("Новых событий нет — сообщение не отправлено.")
        return 0
    if message is None:
        message = "<b>Местов.Нет:</b> ничего нового не найдено 🥱"

    print(message)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat_id):
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы — сообщение не отправлено.", file=sys.stderr)
        return 2

    send(token, chat_id, message)
    print("Сообщение отправлено в Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
