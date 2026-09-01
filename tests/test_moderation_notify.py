import json

import moderation_notify


def test_notification_mentions_meta_tag_duplicates(tmp_path, monkeypatch):
    queue_path = tmp_path / "moderation.json"
    queue_path.write_text(json.dumps([
        {"id": "duplicate", "reasons": ["дубли мета-тегов: совпадают title и description"]},
    ]), encoding="utf-8")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return Response()

    monkeypatch.setattr(moderation_notify, "QUEUE", queue_path)
    monkeypatch.setattr(moderation_notify.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    moderation_notify.main()
    assert "дубли мета-тегов" in captured["text"]
