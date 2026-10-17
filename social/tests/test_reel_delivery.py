import copy
import json
import sqlite3
from datetime import datetime

import pytest
from social import reel_delivery as d, reel_module as m


@pytest.fixture
def delivery(tmp_path):
    b=tmp_path/'reel';b.mkdir()
    event=dict(id='test',artist='Концерт',date='2026-10-20',time='20:00',source_city='Ялта',
               venue='Клуб',source_url='https://example.org/event',needs_review=False)
    post=dict(event_id='test',title='Концерт',date='2026-10-20',time='20:00',city='Ялта',venue='Клуб',cover={})
    names=['source.png','spec.json','reel.mp4','cover.jpg','preview.jpg','text-layout.json','composition.json','ui-preview.jpg']
    for name in names:(b/name).write_bytes(b'isolated unit fixture, not a publishable video')
    report=dict(identity='unit',event_id='test',status='ready_for_review',event=post,
                facts_sha256=m.fingerprint(post),issues=[],technical={'full_decode_passed':True},
                artifacts={name:m.sha(b/name) for name in names})
    report['integrity']=m.fingerprint(report);m.write_json(b/'report.json',report)
    now='2026-10-17T12:00:00+03:00'
    verification=dict(facts_sha256=m.fingerprint(event),source_url=event['source_url'],
       checked_at='2026-10-17T11:00:00+03:00',source_success=True,copy_matches_source=True,
       live_music_confirmed=True,editorial_copy_sha256=m.fingerprint({}))
    policy=dict(reviewers=['unit-reviewer'],allow_important_region_resolution=False)
    review=d.record_review(b,dict(reviewer='unit-reviewer',decision='pass',reviewed_at=now,
       binding=d.review_binding(b,report),watched_full_video=True,checks={k:True for k in d.CHECKS}),
       policy,tmp_path/'review.json')
    return dict(bundle=b,event=event,verification=verification,history={'imported':True,'records':[]},
                review=review,policy=policy,now=now)


def test_positive_handoff_is_idempotent_and_self_contained(tmp_path,delivery):
    path,receipt=d.enqueue(**delivery,queue=tmp_path/'queue')
    assert receipt['status']=='queued' and receipt['publication_performed'] is False
    d.intact(path)
    again,_=d.enqueue(**delivery,queue=tmp_path/'queue')
    assert again==path
    assert len(list((tmp_path/'queue/jobs').iterdir()))==1


@pytest.mark.parametrize('change,reason',[
    ({'cancelled':True},'not_eligible'),({'hidden':True},'not_eligible'),
    ({'needs_review':True},'not_eligible'),({'moderation_status':'rejected'},'not_eligible'),
    ({'date':'2020-01-01'},'facts_changed'),({'venue':'Другой зал'},'facts_changed')])
def test_event_change_and_moderation_blocks_handoff(delivery,change,reason):
    delivery['event'].update(change)
    with pytest.raises(ValueError,match=reason):d.evaluate(**delivery)


def test_stale_source_is_blocked(delivery):
    delivery['verification']['checked_at']='2026-10-15T12:00:00+03:00'
    with pytest.raises(ValueError,match='stale'):d.evaluate(**delivery)


def test_repeat_before_72_hours_blocked(delivery):
    delivery['history']['records']=[dict(event_id='test',state='published',format='post',
        platform_receipt='test-platform-id',published_at='2026-10-16T12:00:00+03:00')]
    with pytest.raises(ValueError,match='72h'):d.evaluate(**delivery)


def test_unknown_send_requires_reconciliation(delivery):
    delivery['history']['records']=[dict(event_id='test',state='unknown')]
    with pytest.raises(ValueError,match='unknown'):d.evaluate(**delivery)


def test_history_must_be_imported(delivery):
    delivery['history']['imported']=False
    with pytest.raises(ValueError,match='not_imported'):d.evaluate(**delivery)


def test_review_never_inherits_from_post_or_template(delivery):
    delivery['review']={}
    with pytest.raises(ValueError,match='review_changed'):d.evaluate(**delivery)


def test_changed_video_invalidates_review(delivery):
    (delivery['bundle']/'reel.mp4').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed_or_incomplete'):d.evaluate(**delivery)


def test_people_overlap_cannot_be_waived(delivery):
    b=delivery['bundle'];report=json.loads((b/'report.json').read_text())
    report['issues']=['protected_faces_overlap'];report.pop('integrity');report['integrity']=m.fingerprint(report)
    m.write_json(b/'report.json',report)
    with pytest.raises(ValueError,match='blocking_composition'):d.evaluate(**delivery)


def test_consumer_unknown_state_does_not_resend(tmp_path,delivery):
    queue=tmp_path/'queue';d.enqueue(**delivery,queue=queue)
    with sqlite3.connect(queue/'queue.sqlite') as db:db.execute("UPDATE jobs SET state='unknown'")
    with pytest.raises(ValueError,match='reconcile_queue'):d.enqueue(**delivery,queue=queue)


def test_review_requires_actual_complete_playback(tmp_path,delivery):
    b,r=d.intact(delivery['bundle'])
    result=dict(reviewer='unit-reviewer',decision='pass',reviewed_at=delivery['now'],
                binding=d.review_binding(b,r),checks={k:True for k in d.CHECKS},watched_full_video=False)
    with pytest.raises(ValueError,match='full_video'):d.record_review(b,result,delivery['policy'],tmp_path/'bad-review.json')


def test_archive_result_never_enters_queue(delivery):
    b=delivery['bundle'];report=json.loads((b/'report.json').read_text())
    report['archive_test']=True;report.pop('integrity');report['integrity']=m.fingerprint(report)
    m.write_json(b/'report.json',report)
    with pytest.raises(ValueError,match='archive_test_not_deliverable'):d.evaluate(**delivery)
