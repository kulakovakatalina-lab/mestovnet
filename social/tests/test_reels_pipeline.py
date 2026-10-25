import json
from pathlib import Path
import tempfile

from PIL import Image
import pytest

from social import reels
from social.reel_module import background_plan, cache_valid, make_spec, sha, write_json, fingerprint


def test_wide_group_is_contained_instead_of_cropping_people(tmp_path):
    source=tmp_path/'source.png'
    Image.new('RGB',(1600,760),'white').save(source)
    mode,issues=background_plan(source,{'analysis':{'kind':'group_photo',
        'faces':[[.02,.2,.15,.5],[.8,.2,.96,.5]]}})
    assert mode=='contain'
    assert 'source_requires_contain_layout_review' in issues


def test_adapter_uses_verified_editorial_copy_and_dates(tmp_path):
    source=tmp_path/'selected-source.png'
    Image.new('RGB',(1080,1920)).save(source)
    report={'event':{'title':'Long original headline','date':'2026-10-18','time':'19:00',
        'venue':'Venue','city':'City','cover':{'title':['Вечер','романсов'],'kicker':'Два исполнителя'}},
        'selected':{'source_sha256':sha(source),'analysis':{'kind':'illustration'}}}
    spec,issues=make_spec(tmp_path,report)
    assert spec['title']=='Вечер\nромансов'
    assert spec['date']=='18 октября · 19:00'
    assert spec['subtitle']=='Два исполнителя'
    Image.new('RGB',(1080,1920),'white').save(source)
    with pytest.raises(ValueError,match='hash_mismatch'):
        make_spec(tmp_path,report)


def test_approved_text_sizes_never_shrink_for_long_title(tmp_path):
    source=tmp_path/'source.png';Image.new('RGB',(1080,1920)).save(source)
    spec=dict(title='Очень длинное название ' * 12,date='18 октября · 19:00',
              venue='Площадка',city='Симферополь',image=str(source))
    with pytest.raises(ValueError,match='Too many text lines'):
        reels.compose_layers(spec,tmp_path,reels.typography())


def test_two_line_subtitle_and_long_city_fit(tmp_path):
    source=tmp_path/'source.png';Image.new('RGB',(1080,1920)).save(source)
    spec=dict(title='Вечер\nромансов', subtitle='Кристина Кушнир · Сергей Аниканов',
              date='18 октября · 19:00',venue='Арт-кафе «Снежинка»',
              city='Симферополь',image=str(source))
    reels.compose_layers(spec,tmp_path,reels.typography())
    for name in ('title.png','facts.png','brand.png'):
        with Image.open(tmp_path/name) as layer:
            box=layer.getbbox()
            assert box[2] <= 941 and box[3] <= 1750
    with Image.open(tmp_path/'title.png') as layer:
        assert layer.crop((0,0,1080,970)).getbbox()[3] < 970


def test_cache_detects_artifact_and_metadata_changes(tmp_path):
    source=tmp_path/'source.png';source.write_bytes(b'original')
    artifacts={'source.png':sha(source)}
    for name in ('spec.json','reel.mp4','cover.jpg','preview.jpg','text-layout.json','composition.json','ui-preview.jpg'):
        (tmp_path/name).write_bytes(b'fixture')
        artifacts[name]=sha(tmp_path/name)
    report=dict(identity='one',status='ready_for_review',technical={'full_decode_passed':True},artifacts=artifacts)
    report['integrity']=fingerprint(report)
    write_json(tmp_path/'report.json',report)
    assert cache_valid(tmp_path,'one')
    report['status']='approved'
    write_json(tmp_path/'report.json',report)
    assert not cache_valid(tmp_path,'one')
    report['status']='ready_for_review';write_json(tmp_path/'report.json',report)
    source.write_bytes(b'changed')
    assert not cache_valid(tmp_path,'one')


def test_raised_vinyl_leaves_gap_above_two_line_subtitle(tmp_path):
    source=tmp_path/'source.png';Image.new('RGB',(1080,1920)).save(source)
    spec=dict(title='Вечер\nромансов',subtitle='Кристина Кушнир · Сергей Аниканов',
              date='18 октября · 19:00',venue='Площадка',city='Севастополь',image=str(source))
    reels.compose_layers(spec,tmp_path,reels.typography())
    with Image.open(tmp_path/'title.png') as layer:
        first_text_y=layer.getbbox()[1]
    assert first_text_y-(reels.VINYL_Y+reels.VINYL_SIZE) >= 100
