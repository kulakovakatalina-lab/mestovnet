from datetime import datetime,timezone
import json
from pathlib import Path
import pytest
from social import reel_pipeline as p,reel_delivery as d,reel_module as m


@pytest.fixture
def inputs(monkeypatch,tmp_path):
    now=datetime(2026,10,17,12,tzinfo=timezone.utc)
    event=dict(id='event1',artist='Концерт',date='2026-10-20',time='20:00',source_city='Ялта',
               venue='Клуб',source_url='https://example.org/event')
    prepared=dict(event_id='event1',title='Концерт',date=event['date'],time=event['time'],city='Ялта',venue='Клуб')
    receipt=dict(live_music_confirmed=True,facts_sha256=m.fingerprint(event),source_url=event['source_url'],
                 source_success=True,copy_matches_source=True,editorial_copy_sha256=m.fingerprint({}),
                 checked_at=now.isoformat())
    monkeypatch.setattr(d,'project_event',lambda *args:event)
    monkeypatch.setattr(m,'load_image_bundle',lambda *args:(tmp_path,dict(event=prepared)))
    return dict(project=tmp_path,images=tmp_path,event_id='event1',output=tmp_path/'output',
                verification=receipt,history={'imported':True,'records':[]},policy={},
                provider_factory=lambda:object(),now=now)


def test_missing_source_evidence_skips_before_render_or_model(inputs,monkeypatch):
    inputs['verification']={}
    monkeypatch.setattr(m,'prepare_from_images',lambda *a:pytest.fail('must not render without source evidence'))
    result=p.run_event(**inputs)
    assert result['status']=='skipped' and result['stage']=='preflight'
    assert result['publication_performed'] is False and not result['manual_daily_action_required']
    assert json.loads((inputs['output']/'latest/event1.json').read_text())==result


def test_real_preflight_then_render_review_and_current_check_before_queue(inputs,monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(m,'prepare_from_images',lambda *args:(calls.append('render') or tmp_path,dict(status='ready_for_review',issues=[])))
    monkeypatch.setattr(p.visual,'review',lambda *args,**kw:(calls.append('review') or tmp_path,{'decision':'pass'}))
    def enqueue(*args,**kwargs):
        calls.append('queue');assert args[6]==inputs['now']
        assert kwargs['image_output']==inputs['images']
        return tmp_path/'job',dict(status='queued')
    monkeypatch.setattr(d,'enqueue_project',enqueue)
    result=p.run_event(**inputs)
    assert calls==['render','review','queue'] and result['status']=='queued'
    assert result['publication_performed'] is False


def test_failed_visual_check_never_queues(inputs,monkeypatch,tmp_path):
    monkeypatch.setattr(m,'prepare_from_images',lambda *args:(tmp_path,dict(status='ready_for_review',issues=[])))
    monkeypatch.setattr(p.visual,'review',lambda *args,**kw:(tmp_path,{'decision':'reject'}))
    monkeypatch.setattr(d,'enqueue_project',lambda *a,**kw:pytest.fail('rejected video must not queue'))
    result=p.run_event(**inputs)
    assert result['status']=='skipped' and result['reason']=='visual_review_rejected'


def test_upstream_change_during_review_is_a_recorded_skip(inputs,monkeypatch,tmp_path):
    monkeypatch.setattr(m,'prepare_from_images',lambda *args:(tmp_path,dict(status='ready_for_review',issues=[])))
    monkeypatch.setattr(p.visual,'review',lambda *args,**kw:(tmp_path,{'decision':'pass'}))
    def changed(*args,**kwargs):raise ValueError('image_bundle_no_longer_current')
    monkeypatch.setattr(d,'enqueue_project',changed)
    result=p.run_event(**inputs)
    assert result['status']=='skipped' and result['reason']=='image_bundle_no_longer_current'


def test_batch_skips_missing_receipts_then_tries_an_alternative(tmp_path,monkeypatch):
    images=tmp_path/'images';(images/'current').mkdir(parents=True)
    for event_id in ['a','b','c','d']:(images/'current'/f'{event_id}.json').write_text('{}')
    monkeypatch.setattr(d,'project_event',lambda project,event_id:dict(id=event_id,date='2026-10-21',time='20:00'))
    seen=[]
    def run(*args,**kwargs):
        event_id=args[2];seen.append(event_id)
        return dict(event_id=event_id,status='queued' if event_id=='d' else 'skipped',stage='queue' if event_id=='d' else 'preflight')
    monkeypatch.setattr(p,'run_event',run)
    result=p.run_batch(tmp_path,images,tmp_path/'output',{}, {},{},lambda:None,
        max_candidates=1,now=datetime(2026,10,17,12,tzinfo=timezone.utc))
    assert seen==['a','b','c','d'] and result['status']=='queued'
