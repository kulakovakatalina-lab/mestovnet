import json
from PIL import Image
import pytest
from social import reels,reel_module as m
from social.reel_composition import measure


def group(tmp_path,title='Helvegen'):
    source=tmp_path/'selected-source.png';Image.new('RGB',(1600,760),'white').save(source)
    regions=[[.01,.01,.19,.99],[.21,.01,.39,.99],[.41,.01,.59,.99],[.61,.01,.79,.99],[.81,.01,.99,.99]]
    selected=dict(source_sha256=m.sha(source),analysis=dict(kind='group_photo',faces=regions,figures=regions))
    event=dict(title=title,subtitle='Фолк-метал',date='2026-10-20',time='20:00',venue='Депо',city='Симферополь')
    return dict(event=event,selected=selected)


def test_approved_group_layout_preserves_all_people_and_font_sizes(tmp_path):
    report=group(tmp_path);spec,_=m.make_spec(tmp_path,report)
    assert spec['layout']==reels.GROUP_LAYOUT and spec['background_mode']=='contain'
    reels.compose_layers(spec,tmp_path,reels.typography())
    with Image.open(reels.ROOT/'assets/vinyl.png') as image:
        image.convert('RGBA').resize((510,510)).save(tmp_path/'vinyl-preview.png')
    result=measure(tmp_path,report['selected'],(255,200,510),mode='contain')
    assert not result['issues']
    assert len(result['protected'])==10
    assert all(740<=r['box'][1]<r['box'][3]<=1253 for r in result['protected'])
    layout=json.loads((tmp_path/'text-layout.json').read_text())
    assert next(r for r in layout if r['text']=='Helvegen')['size']==150
    assert min(r['box'][1] for r in layout)>=1285


def test_two_line_group_title_does_not_silently_shrink(tmp_path):
    report=group(tmp_path,'Вечер\nромансов');spec,_=m.make_spec(tmp_path,report)
    assert spec.get('layout')!=reels.GROUP_LAYOUT
    spec.update(layout=reels.GROUP_LAYOUT,background_mode='contain')
    with pytest.raises(ValueError,match='Too many text lines'):
        reels.compose_layers(spec,tmp_path,reels.typography())


def test_unknown_layout_and_group_zoom_are_rejected(tmp_path):
    report=group(tmp_path);spec,_=m.make_spec(tmp_path,report)
    spec['layout']='not-approved'
    with pytest.raises(ValueError,match='unapproved'):
        reels.compose_layers(spec,tmp_path,reels.typography())
    spec.update(layout=reels.GROUP_LAYOUT,background_mode='cover')
    with pytest.raises(ValueError,match='without_zoom'):
        reels.compose_layers(spec,tmp_path,reels.typography())
