"""Регрессии по двум опубликованным анонсам концерта в Новороссийске."""
import json
from pathlib import Path

import pytest
from parser import resolve_city, validate_events


@pytest.fixture
def published_events():
    return json.loads((Path(__file__).parent / 'fixtures/novorossiysk_duplicates.json').read_text())


def test_both_published_duplicates_are_excluded(published_events):
    accepted, rejected = validate_events(published_events)
    assert accepted == []
    assert rejected == {'excluded_source': 2}


def test_explicit_external_city_is_not_replaced_with_crimea():
    assert resolve_city({'city': 'Новороссийск'}, {'city': 'Крым'}) == 'Новороссийск'


def test_source_location_survives_missing_llm_city(published_events):
    event = published_events[0]
    city = resolve_city(event, {'city': 'Крым'},
                        'ЗАПРЕЩЕННЫЕ БАРАБАНЩИКИ (г. Москва, г. Ростов-на-Дону)\n📍 г. Новороссийск Пена Паб')
    assert city == 'Новороссийск'
    event.update(source_city=city, source_url='https://t.me/skazhitejazz/9999', venue='Другая площадка')
    assert validate_events([event])[1] == {'unknown_city': 1}


def test_crimean_concert_with_external_artist_hometown_is_kept(published_events):
    event = dict(published_events[0], city='Ялта', venue='Театр Чехова',
                 source_url='https://t.me/skazhitejazz/9999')
    event['source_city'] = resolve_city(event, {'city': 'Крым'},
                                      'Музыканты из Новороссийска\n📍 г. Ялта')
    assert event['source_city'] == 'Ялта'
    assert validate_events([event])[0] == [event]


def test_new_pena_pub_announcement_is_excluded(published_events):
    event = dict(published_events[0], venue='Пена Паб', source_url='https://t.me/skazhitejazz/9999')
    assert validate_events([event])[1] == {'excluded_venue': 1}


def test_multi_city_post_does_not_override_explicit_crimean_stop():
    assert resolve_city({'city': 'Ялта'}, {'city': 'Крым'},
                        '📍 г. Новороссийск Пена Паб\n📍 г. Ялта Театр Чехова') == 'Ялта'
