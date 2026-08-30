from pathlib import Path


def test_manual_telegram_delivery_check_uses_the_configured_chat():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
                "test-telegram-delivery.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "secrets.TELEGRAM_BOT_TOKEN" in workflow
    assert "secrets.TELEGRAM_CHAT_ID" in workflow
    assert "/sendMessage" in workflow
