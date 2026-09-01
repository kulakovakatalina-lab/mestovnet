import source_health_notify as notify


def test_build_message_skips_healthy_report():
    assert notify.build_message({"alerts": []}) is None


def test_build_message_lists_each_alert_and_escapes_html():
    message = notify.build_message({"alerts": [
        {"source": "club <main>", "message": "источник недоступен"},
        {"city": "Ялта", "message": "все будущие события города исчезли из витрины"},
    ]})

    assert "Проверьте источники" in message
    assert "club &lt;main&gt;" in message
    assert "Ялта" in message
    assert "https://mestov.net/current-events/" in message
