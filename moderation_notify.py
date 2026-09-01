"""Отправляет администратору Telegram кнопку для разбора очереди событий."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


QUEUE = Path("moderation.json")
API = "https://api.telegram.org/bot{token}/sendMessage"
CURRENT_EVENTS_URL = "https://mestov.net/current-events/"


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Telegram не настроен — уведомление модерации пропущено.")
        return
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    if not queue:
        print("Очередь модерации пуста.")
        return
    seo_collisions = sum(
        1 for event in queue
        if any("дубли мета-тегов" in reason for reason in event.get("reasons", []))
    )
    seo_note = (
        f"\n\n⚠️ <b>{seo_collisions}</b> из них — дубли мета-тегов "
        "(совпадают title и description). До решения они не публикуются."
        if seo_collisions else ""
    )
    payload = {
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "text": (
            "🔎 <b>Очередь модерации</b>\n\n"
            f"После ночного парсинга ждут решения: <b>{len(queue)}</b>.\n"
            "Открой карточки и одобряй или отклоняй их по одной. "
            "Одобренные события попадут в следующую ночную публикацию."
            f"{seo_note}\n\n<a href=\"{CURRENT_EVENTS_URL}\">Вся актуальная афиша</a>"
        ),
        "reply_markup": {"inline_keyboard": [[{
            "text": "Разобрать события ▶",
            "callback_data": "mod:start",
        }]]},
    }
    request = urllib.request.Request(
        API.format(token=token),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise SystemExit(f"Не удалось отправить Telegram-уведомление: {exc}") from exc
    if not result.get("ok"):
        raise SystemExit(f"Telegram API вернул ошибку: {result}")
    print(f"Telegram: отправлено уведомление о {len(queue)} карточках.")


if __name__ == "__main__":
    main()
