#!/usr/bin/env python3
"""Отправляет в Telegram только предупреждения из source_health.json."""

import html
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx


DEFAULT_REPORT = Path("source_health.json")


def load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_message(report: dict) -> Optional[str]:
    alerts = report.get("alerts") or []
    if not alerts:
        return None

    lines = ["⚠️ <b>Проверьте источники Местов.Нет</b>"]
    for alert in alerts:
        subject = alert.get("source") or alert.get("city") or "Источник"
        message = alert.get("message") or "требует проверки"
        lines.append(f"• <b>{html.escape(str(subject))}</b>: {html.escape(str(message))}")
    return "\n".join(lines)


def send(bot_token: str, chat_id: str, text: str) -> None:
    response = httpx.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()


def main() -> int:
    path = Path(os.environ.get("SOURCE_HEALTH_REPORT", DEFAULT_REPORT))
    message = build_message(load_report(path))
    if message is None:
        print("Отклонений здоровья источников нет — сообщение не отправлено.")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat_id):
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы — сообщение не отправлено.", file=sys.stderr)
        return 2
    send(token, chat_id, message)
    print("Предупреждение о здоровье источников отправлено в Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
