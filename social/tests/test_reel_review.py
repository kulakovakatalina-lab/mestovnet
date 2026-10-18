import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime,timezone
from PIL import Image
import pytest
from social import reel_delivery as d,reel_module as m,reel_review as r


def video(path,changed=False):
    source=path.parent/path.stem;source.mkdir()
    for i in range(6):
        Image.new('RGB',(32,32),(255 if i%2 else 0,0,0) if not (changed and i==3) else (0,255,0)).save(source/f'{i:02d}.png')
    subprocess.run(['ffmpeg','-y','-v','error','-framerate','30','-i',str(source/'%02d.png'),
                    '-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_continuous_audit_catches_a_single_bad_middle_frame(tmp_path):
    a=tmp_path/'a.mp4';b=tmp_path/'b.mp4';video(a);video(b,changed=True)
    with pytest.raises(ValueError,match='frame_reference_mismatch:3'):
        r.compare_video_frames(a,b,6,tmp_path/'audit',size=(32,32))


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_identical_streams_are_fully_checked_and_extra_frames_fail(tmp_path):
    a=tmp_path/'a.mp4';video(a)
    result=r.compare_video_frames(a,a,6,tmp_path/'audit',size=(32,32))
    assert result['full_coverage'] and result['checked_frames']==6 and result['max_pixel_delta']==0
    with pytest.raises(ValueError,match='extra_frames'):
        r.compare_video_frames(a,a,5,tmp_path/'short',size=(32,32))


@pytest.mark.parametrize('confidence',[True,float('nan'),float('inf'),-.1,1.01])
def test_semantic_uncertainty_is_not_a_pass(confidence):
    with pytest.raises(ValueError,match='confidence'):
        r.validate_semantics(dict(checks={k:True for k in d.CHECKS},confidence=confidence,issues=[]))


def test_semantic_checks_need_booleans():
    result=dict(checks={k:True for k in d.CHECKS},confidence=.95,issues=[])
    result['checks']['subjects_preserved']='yes'
    with pytest.raises(ValueError,match='boolean'):r.validate_semantics(result)


def test_server_positive_still_receipt_never_counts_as_full_review():
    report=dict(duration=10,artifacts={'reel.mp4':'video-hash'})
    result=dict(reviewer='server-vision',decision='pass',watched_full_video=True)
    with pytest.raises(ValueError,match='full_frame_evidence'):
        d.validate_automatic_review(result,report)
    result.update(review_method=r.VERSION,continuous_audit=dict(method='all_frames_against_approved_reference',
        full_coverage=True,checked_frames=299,frame_count=300,video_sha256='video-hash'))
    with pytest.raises(ValueError,match='full_frame_evidence'):
        d.validate_automatic_review(result,report)


def test_geometry_rejection_makes_no_model_call(tmp_path,monkeypatch):
    bundle=tmp_path/'bundle';bundle.mkdir()
    event=dict(event_id='test',title='Концерт')
    names=['source.png','spec.json','reel.mp4','cover.jpg','preview.jpg','text-layout.json','composition.json','ui-preview.jpg']
    for name in names:(bundle/name).write_bytes(b'not a video; must never reach decoding or model')
    report=dict(identity='test',status='needs_review',event=event,facts_sha256=m.fingerprint(event),
        issues=['protected_faces_overlap'],technical={'full_decode_passed':True},
        artifacts={name:m.sha(bundle/name) for name in names},render_signature={'test':'signature'})
    report['integrity']=m.fingerprint(report);m.write_json(bundle/'report.json',report)
    monkeypatch.setattr(r.reels,'render_signature',lambda:{'test':'signature'})
    class NoCalls:
        model='test-no-model'
        def request(self,*args):raise AssertionError('must not call model for rejected geometry')
    policy=dict(reviewers=['server-vision'])
    out,receipt=r.review(bundle,tmp_path/'reviews',NoCalls(),policy)
    assert receipt['decision']=='reject' and not receipt['watched_full_video']
    assert json.loads((out/'evidence.json').read_text())['frame_audit'] is None
    again,cached=r.review(bundle,tmp_path/'reviews',NoCalls(),policy)
    assert again==out and cached==receipt
