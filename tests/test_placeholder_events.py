import pytest
from parser import _event_validation_reason, _is_refusal_event, is_placeholder_title
from moderation_queue import reasons


@pytest.mark.parametrize('title', [None, '', 'не указано', ' НЕ  УКАЗАНО ', 'Без названия', 'null'])
def test_placeholder_cannot_pass_validation(title):
    assert is_placeholder_title(title)
    assert _event_validation_reason({'date': '2026-09-24', 'artist': title}) == 'missing_artist'
    assert 'нет названия' in reasons({'artist': title})


def test_cinema_meeting_is_not_music():
    event = {'artist': 'не указано', 'event_type': 'другое', 'description':
             'Встреча с Джаником Файзиевым. Режиссёр расскажет о своём пути в киноиндустрии и ответит на вопросы о кино.'}
    assert _is_refusal_event(event)
    event['description'] += ' Затем концерт группы с живой музыкой.'
    assert not _is_refusal_event(event)


def test_auto_update_does_not_bypass_missing_title(tmp_path, monkeypatch):
    import json
    import moderation_queue as queue
    events = [
        {'id': 'bad', 'date': '2999-01-01', 'artist': 'не указано', 'auto_updated': True},
        {'id': 'fixed', 'date': '2999-01-02', 'artist': 'не указано',
         'source_url': 'corrected', 'time': '19:00', 'venue': 'Клуб'},
    ]
    for name, filename in [('EVENTS', 'events.json'), ('QUEUE', 'moderation.json'),
                           ('SETTINGS', 'settings.json'), ('DECISIONS_CACHE', 'decisions.json')]:
        monkeypatch.setattr(queue, name, tmp_path / filename)
    queue.EVENTS.write_text(json.dumps(events))
    queue.SETTINGS.write_text(json.dumps({'names': {'corrected': 'Группа'}}))
    monkeypatch.setattr(queue, 'load_decisions', lambda: [])
    queue.main()
    saved = json.loads(queue.EVENTS.read_text())
    assert saved[0]['needs_review'] is True
    assert 'нет названия' in saved[0]['review_reasons']
    assert saved[1]['needs_review'] is False
    assert 'нет названия' not in saved[1]['review_reasons']
