import json
from pathlib import Path
import pytest
from PIL import Image
from social import reel_job as job,reel_module as m


@pytest.fixture
def package(tmp_path):
    b=tmp_path/'image';b.mkdir();source=b/'selected-source.png';Image.new('RGB',(1080,1920)).save(source)
    images=dict(event=dict(event_id='test',title='Концерт',date='2026-10-20',time='20:00',city='Ялта',venue='Клуб'),
        version='fixture',identity='fixture',selected=dict(source_sha256=m.sha(source),analysis={'kind':'photo'}))
    m.write_json(b/'report.json',images)
    return job.create_job(b,images,tmp_path/'job',archive=True)


def test_job_contains_no_local_input_paths_or_fonts(package):
    manifest=json.loads((package/'job.json').read_text())
    assert manifest['scope']=='archive-test-only'
    assert manifest['spec']['image']=='source.png'
    assert manifest['spec']['vinyl']=='vinyl.png'
    assert set(p.name for p in package.iterdir())=={'job.json','source.png','vinyl.png','design.json'}
    assert all(v['path']=='runtime-provided-font' for v in json.loads((package/'design.json').read_text())['fonts'].values())


def test_changed_job_asset_is_refused(package,tmp_path):
    (package/'source.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='asset_changed'):job.render_job(package,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_job_cannot_reference_file_outside_package(package,tmp_path):
    manifest=json.loads((package/'job.json').read_text());manifest['spec']['image']='../../somewhere'
    manifest.pop('integrity');manifest['integrity']=m.fingerprint(manifest);m.write_json(package/'job.json',manifest)
    with pytest.raises(ValueError,match='asset_reference'):job.render_job(package,tmp_path/'output')


def test_job_requires_all_code_bindings(package,tmp_path):
    manifest=json.loads((package/'job.json').read_text());manifest['code']={}
    manifest.pop('integrity');manifest['integrity']=m.fingerprint(manifest);m.write_json(package/'job.json',manifest)
    with pytest.raises(ValueError,match='code_binding'):job.render_job(package,tmp_path/'output')


def test_synthetic_cloud_fixture_text_fits_approved_sizes(tmp_path):
    from social.build_cloud_fixture import build
    from social import reels
    package=build(tmp_path/'synthetic')
    manifest=json.loads((package/'job.json').read_text())
    spec=dict(manifest['spec'],image=str(package/'source.png'))
    layers=tmp_path/'layers';layers.mkdir()
    text=reels.compose_layers(spec,layers,reels.typography())
    assert len([item for item in text if item['size']==150])==2
