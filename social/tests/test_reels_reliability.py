import json
import subprocess
import sys
from pathlib import Path

from PIL import Image
import pytest
from social import reels, reel_module as m


@pytest.fixture
def input_bundle(tmp_path, monkeypatch):
    bundle=tmp_path/'a2';bundle.mkdir()
    source=bundle/'selected-source.png';Image.new('RGB',(1080,1920)).save(source)
    report=dict(status='ready_for_review',version='a2-fixture',event=dict(
        event_id='test',title='Концерт',date='2026-10-20',time='20:00',city='Ялта',venue='Клуб'),
        selected=dict(source_sha256=m.sha(source),generated=False,analysis={'kind':'photo','faces':[],'important_regions':[]}))
    m.write_json(bundle/'report.json',report)
    monkeypatch.setattr(m,'load_image_bundle',lambda *args:(bundle,report))
    return bundle,report


@pytest.mark.parametrize('kind',['interrupted','disk_full','bad_decode'])
def test_failed_new_version_preserves_previous_current(tmp_path,monkeypatch,input_bundle,kind):
    output=tmp_path/'out';pointer=output/'current/test.json'
    m.write_json(pointer,{'bundle':'test/previous-good','status':'ready_for_review'})
    prior=pointer.read_bytes()
    def fail(spec,path,duration):
        if kind=='bad_decode':
            Path(path).write_bytes(b'broken mp4')
            return Path(path)
        if kind=='disk_full':raise OSError(28,'No space left')
        raise subprocess.CalledProcessError(-9,['ffmpeg'])
    monkeypatch.setattr(reels,'render',fail)
    bundle,report=m.prepare_from_images('unused','test',output,11)
    assert report['status']=='failed'
    assert pointer.read_bytes()==prior
    assert json.loads((output/'attempts/test.json').read_text())['status']=='failed'
    assert bundle.exists()


@pytest.mark.parametrize('duration',[4,9,16,30,True])
def test_phase_one_duration_returns_structured_failure(tmp_path,duration):
    bundle,report=m.prepare_from_images('unused','test',tmp_path/'out',duration)
    assert bundle is None and report['status']=='failed'
    assert '10_to_15' in report['message']
    assert not (tmp_path/'out/current').exists()


def test_missing_font_is_json_failure_and_keeps_current(tmp_path,monkeypatch,input_bundle):
    out=tmp_path/'out';pointer=out/'current/test.json';m.write_json(pointer,{'bundle':'good'})
    before=pointer.read_bytes();monkeypatch.setenv('REELS_FONT',str(tmp_path/'missing.ttc'))
    bundle,report=m.prepare_from_images('unused','test',out)
    assert bundle is None and report['status']=='failed'
    assert report['stage']=='preflight' and report['error_type']=='ValueError'
    assert pointer.read_bytes()==before
    assert Path(report['error_report']).is_file()


def test_missing_video_track_is_clear_validation_error(tmp_path,monkeypatch):
    monkeypatch.setattr(m.subprocess,'check_output',lambda *a,**k:json.dumps({'streams':[]}).encode())
    with pytest.raises(ValueError,match='format_or_sar'):
        m.validate_video(tmp_path/'bad.mp4',10)


def test_incomplete_bundle_never_counts_as_good_cache(tmp_path):
    (tmp_path/'source.png').write_bytes(b'fixture')
    report=dict(identity='x',status='needs_review',artifacts={'source.png':m.sha(tmp_path/'source.png')})
    report['integrity']=m.fingerprint(report);m.write_json(tmp_path/'report.json',report)
    assert not m.cache_valid(tmp_path,'x')


@pytest.mark.parametrize('module',['social.reel_module','social.reels'])
def test_cli_missing_arguments_produces_json_without_traceback(module):
    result=subprocess.run([sys.executable,'-m',module],capture_output=True,text=True)
    data=json.loads(result.stdout)
    assert result.returncode==1 and data['status']=='failed'
    assert 'Traceback' not in result.stderr


def test_atomic_direct_video_destination(tmp_path,monkeypatch):
    source=tmp_path/'source.png';Image.new('RGB',(1080,1920)).save(source)
    spec=dict(title='Концерт',date='20 октября',venue='Клуб',image=str(source))
    output=tmp_path/'existing.mp4';output.write_bytes(b'previous-good')
    monkeypatch.setattr(reels.subprocess,'run',lambda command,**kwargs:Path(command[-1]).write_bytes(b'new-video'))
    monkeypatch.setattr(reels.shutil,'copyfile',lambda *a,**k:(_ for _ in ()).throw(OSError(28,'full')))
    with pytest.raises(OSError):reels.render(spec,output)
    assert output.read_bytes()==b'previous-good'
