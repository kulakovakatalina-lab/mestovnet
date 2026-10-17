"""Portable, checked render jobs. A job render never queues or publishes a video."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image
try:
    from . import reels
    from . import reel_module as m
    from .reel_composition import measure
except ImportError:
    import reels
    import reel_module as m
    from reel_composition import measure


def create_job(bundle, images, output, *, archive=False):
    """Use export_job for production; archive=True is an explicitly non-deliverable test fixture."""
    output=Path(output)
    if output.exists():raise ValueError('job_destination_exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    spec,_=m.make_spec(Path(bundle),images)
    config_path=Path(os.environ.get('REELS_DESIGN',reels.ROOT/'templates/photo-led-a2.local.json'))
    config=json.loads(config_path.read_text())
    for face in config['fonts'].values():face['path']='runtime-provided-font'
    with tempfile.TemporaryDirectory(dir=output.parent) as work:
        work=Path(work)
        shutil.copyfile(spec['image'],work/'source.png')
        shutil.copyfile(reels.ROOT/'assets/vinyl.png',work/'vinyl.png')
        m.write_json(work/'design.json',config)
        spec.update(image='source.png',vinyl='vinyl.png')
        job=dict(schema=1,scope='archive-test-only' if archive else 'phase1',duration=10,
            event=images['event'],image_version=images['version'],image_identity=images['identity'],
            selected=images['selected'],spec=spec,input_report_sha256=m.sha(Path(bundle)/'report.json'),
            caption_note=images.get('caption_note'),
            code={name:m.sha(Path(__file__).with_name(name)) for name in
                  ('reels.py','reel_module.py','reel_composition.py','reel_job.py')},
            artifacts={name:m.sha(work/name) for name in ('source.png','vinyl.png','design.json')})
        job['integrity']=m.fingerprint(job);m.write_json(work/'job.json',job)
        work.rename(output)
    return output


def export_job(images,event_id,output):
    bundle,report=m.load_image_bundle(images,event_id)
    return create_job(bundle,report,output)


@contextmanager
def font_config(path):
    # CLI jobs use separate processes. This context is not for concurrent Python threads.
    before=os.environ.get('REELS_DESIGN');os.environ['REELS_DESIGN']=str(path)
    try:yield
    finally:
        if before is None:os.environ.pop('REELS_DESIGN',None)
        else:os.environ['REELS_DESIGN']=before


def render_job(job_dir,output):
    job_dir=Path(job_dir).resolve();output=Path(output).resolve()
    job=json.loads((job_dir/'job.json').read_text())
    if job.get('schema')!=1 or job.get('scope') not in ('phase1','archive-test-only'):
        raise ValueError('unsupported_job_scope')
    if job.get('integrity')!=m.fingerprint({k:v for k,v in job.items() if k!='integrity'}):
        raise ValueError('job_metadata_changed')
    for name,checksum in job['artifacts'].items():
        if Path(name).name!=name or m.sha(job_dir/name)!=checksum:raise ValueError('job_asset_changed')
    if set(job['artifacts'])!={'source.png','vinyl.png','design.json'}:raise ValueError('incomplete_job_assets')
    if set(job['code'])!={'reels.py','reel_module.py','reel_composition.py','reel_job.py'}:
        raise ValueError('incomplete_job_code_binding')
    if job['scope']=='phase1' and job['artifacts']['source.png']!=job['selected']['source_sha256']:
        raise ValueError('job_selected_source_mismatch')
    for name,checksum in job['code'].items():
        if name not in ('reels.py','reel_module.py','reel_composition.py','reel_job.py') or m.sha(Path(__file__).with_name(name))!=checksum:
            raise ValueError('job_code_changed_reexport_required')
    if type(job['duration']) is not int or not 10<=job['duration']<=15:raise ValueError('invalid_phase_one_duration')
    if job['spec'].get('image')!='source.png' or job['spec'].get('vinyl')!='vinyl.png':
        raise ValueError('invalid_job_asset_reference')
    if output.exists():raise ValueError('render_destination_exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as work:
        work=Path(work);spec=dict(job['spec'],image=str(job_dir/'source.png'),vinyl=str(job_dir/'vinyl.png'))
        with font_config(job_dir/'design.json'):
            fonts=reels.typography()
            reels.render(spec,work/'reel.mp4',job['duration'])
            technical=m.validate_video(work/'reel.mp4',job['duration'])
            with tempfile.TemporaryDirectory() as layers:
                layers=Path(layers);reels.compose_layers(spec,layers,fonts)
                with Image.open(job_dir/'vinyl.png') as image:image.convert('RGBA').resize((510,510)).save(layers/'vinyl-preview.png')
                composition=measure(layers,job['selected'],(255,200,510),mode=spec['background_mode'])
                for name in ('text-layout.json','composition.json','ui-preview.jpg','source-placement.json'):
                    shutil.copyfile(layers/name,work/name)
        subprocess.run(['ffmpeg','-y','-v','error','-ss','3','-i',str(work/'reel.mp4'),
                        '-frames:v','1',str(work/'cover.jpg')],check=True,timeout=30)
        with Image.open(work/'cover.jpg') as image:image.resize((405,720)).save(work/'preview.jpg')
        shutil.copyfile(job_dir/'source.png',work/'source.png');m.write_json(work/'spec.json',job['spec'])
        report=dict(schema=1,status='needs_review' if composition['issues'] else 'ready_for_review',
            approved=False,archive_test=job['scope']=='archive-test-only',event_id=job['event']['event_id'],
            event=job['event'],facts_sha256=m.fingerprint(job['event']),technical=technical,
            issues=composition['issues'],composition=composition,job_integrity=job['integrity'],
            image_version=job['image_version'],caption_note=job.get('caption_note'),
            spec=job['spec'],duration=job['duration'],identity=m.fingerprint(job))
        report['artifacts']={p.name:m.sha(p) for p in work.iterdir() if p.is_file()}
        report['integrity']=m.fingerprint(report);m.write_json(work/'report.json',report)
        work.rename(output)
    return output,report


def main():
    class Parser(argparse.ArgumentParser):
        def error(self,message):raise ValueError(message)
    try:
        parser=Parser();sub=parser.add_subparsers(dest='command',required=True)
        export=sub.add_parser('export');export.add_argument('--images',required=True,type=Path)
        export.add_argument('--event',required=True);export.add_argument('--output',required=True,type=Path)
        run=sub.add_parser('render');run.add_argument('--job',required=True,type=Path);run.add_argument('--output',required=True,type=Path)
        args=parser.parse_args()
        if args.command=='export':
            path=export_job(args.images,args.event,args.output);result=dict(status='job_exported',job=str(path))
        else:
            path,report=render_job(args.job,args.output);result=dict(bundle=str(path),**report)
        print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps(m.failure_report(exc),ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
