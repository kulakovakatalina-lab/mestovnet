"""Удаление афиш сохраняет ссылки из архивов и очереди модерации."""
import json

import pytest

from generate_pages import prune_unused_event_images


def test_cleanup_preserves_archived_and_unpublished_posters(tmp_path):
    images = tmp_path / 'images' / 'events'
    images.mkdir(parents=True)
    current, archived, queued, overridden, unused = [c * 32 + '.jpg' for c in 'abcde']
    for name in (current, archived, queued, overridden, unused, 'manual-poster.jpg'):
        (images / name).write_bytes(b'image')
    (tmp_path / 'events.json').write_text(json.dumps([{'image': '/images/events/' + current}]))
    (tmp_path / 'moderation.json').write_text(json.dumps([{'image': '/images/events/' + queued}]))
    (tmp_path / 'settings.json').write_text(json.dumps({'images': {'event': '/images/events/' + overridden}}))
    (tmp_path / 'event').mkdir()
    (tmp_path / 'event' / 'old-event').write_text(f'<img src="/images/events/{archived}">')

    assert prune_unused_event_images(tmp_path) == 1
    assert not (images / unused).exists()
    assert sorted(p.name for p in images.iterdir()) == sorted(
        [current, archived, queued, overridden, 'manual-poster.jpg'])
    assert prune_unused_event_images(tmp_path) == 0


def test_cleanup_aborts_before_deleting_if_input_cannot_be_read(tmp_path):
    images = tmp_path / 'images' / 'events'
    images.mkdir(parents=True)
    poster = images / ('a' * 32 + '.jpg')
    poster.write_bytes(b'image')
    (tmp_path / 'events.json').write_text('broken json')
    with pytest.raises(json.JSONDecodeError):
        prune_unused_event_images(tmp_path)
    assert poster.exists()
