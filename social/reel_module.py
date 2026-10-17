"""Reels drafts from intact image-module bundles. No network or publishing calls."""
from __future__ import annotations
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from PIL import Image
import struct
import array

try:
    from . import reels
except ImportError:
    import reels

VERSION = 'reel-pipeline-3-reliable-output'
MONTHS = ('января февраля марта апреля мая июня июля августа сентября октября ноября декабря').split()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        temp = stream.name
    os.replace(temp, path)


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def background_plan(source, selected):
    """Check the entire protected source, including the maximum 3.5% zoom."""
    with Image.open(source) as image:
        w, h = image.size
    analysis = selected.get('analysis', {})
    regions = sum((analysis.get(key, []) for key in
                   ('faces', 'figures', 'important_regions', 'watermark_regions', 'text_regions')), [])
    scale = max(1080/w, 1920/h) * 1.035
    visible = [(w-1080/scale)/2/w, (h-1920/scale)/2/h,
               (w+1080/scale)/2/w, (h+1920/scale)/2/h]
    cut = any(r[0] < visible[0] or r[1] < visible[1] or
              r[2] > visible[2] or r[3] > visible[3] for r in regions)
    mode = 'contain' if cut else 'cover'
    if cut:
        scale = min(1080/w, 1920/h)
    # Conservative occupied areas: the actual disc and all text blocks.
    overlays = [[reels.VINYL_X, reels.VINYL_Y, reels.VINYL_X+reels.VINYL_SIZE,
                 reels.VINYL_Y+reels.VINYL_SIZE], [92, 825, 940, 1305],
                [100, 1345, 940, 1620], [100, 1670, 940, 1730]]
    ox, oy = (1080-w*scale)/2, (1920-h*scale)/2
    overlap = any(intersects([r[0]*w*scale+ox, r[1]*h*scale+oy,
                              r[2]*w*scale+ox, r[3]*h*scale+oy], area)
                  for r in regions for area in overlays)
    issues = []
    if cut:
        issues.append('source_requires_contain_layout_review')
    if overlap:
        issues.append('protected_regions_overlap_elements')
    if analysis.get('kind') in ('poster', 'collage', 'unknown'):
        issues.append('unsuitable_background_kind')
    if not analysis or analysis.get('conflicts'):
        issues.append('source_analysis_missing_or_conflicting')
    return mode, issues


def make_spec(bundle, report):
    event = report['event']
    day = date.fromisoformat(event['date'])
    date_text = f'{day.day} {MONTHS[day.month-1]}'
    if event.get('time'):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', event['time']):
            raise ValueError('invalid_event_time')
        date_text += ' · ' + event['time']
    copy = event.get('cover', {})
    title = copy.get('title', event['title'])
    if isinstance(title, list):
        title = '\n'.join(title)
    subtitle = '\n'.join(x for x in (copy.get('kicker'), copy.get('eyebrow')) if x)
    if not subtitle:
        subtitle = event.get('subtitle', '')
    source = bundle / 'selected-source.png'
    if sha(source) != report['selected']['source_sha256']:
        raise ValueError('selected_source_hash_mismatch')
    mode, issues = background_plan(source, report['selected'])
    return dict(title=title, subtitle=subtitle, date=date_text, venue=event['venue'],
                city=event['city'], image=str(source), background_mode=mode), issues


def validate_video(path, duration):
    data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
        '-show_format', '-of', 'json', str(path)], timeout=30))
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), {})
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), {})
    profile = (video.get('width'), video.get('height'), video.get('codec_name'),
               video.get('pix_fmt'), video.get('r_frame_rate'), video.get('avg_frame_rate'),
               video.get('sample_aspect_ratio'))
    if profile != (1080, 1920, 'h264', 'yuv420p', '30/1', '30/1', '1:1'):
        raise ValueError('invalid_video_format_or_sar')
    if audio.get('codec_name') != 'aac' or abs(float(data['format']['duration'])-duration) > 0.1:
        raise ValueError('invalid_video_duration_or_audio')
    atoms = []
    with Path(path).open('rb') as stream:
        end = Path(path).stat().st_size
        while stream.tell() < end:
            start = stream.tell()
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError('invalid_mp4_atoms')
            size, kind = struct.unpack('>I4s', header)
            if size == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    raise ValueError('invalid_mp4_atoms')
                size = struct.unpack('>Q', extended)[0]
            if size == 0:
                size = end-start
            if size < 8 or start+size > end:
                raise ValueError('invalid_mp4_atoms')
            atoms.append(kind.decode('ascii'))
            stream.seek(start+size)
    if 'moov' not in atoms or 'mdat' not in atoms or atoms.index('moov') > atoms.index('mdat'):
        raise ValueError('mp4_faststart_missing')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                   check=True, timeout=120, capture_output=True)
    pts = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],timeout=30))
    times = [float(f['best_effort_timestamp_time']) for f in pts['frames']]
    if len(times) != duration*30 or any(abs((b-a)-1/30)>0.000002 for a,b in zip(times,times[1:])):
        raise ValueError('nonconstant_frame_rate')
    raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a',
                                   '-f','f32le','-'],timeout=30)
    samples = array.array('f')
    samples.frombytes(raw)
    if not samples or any(value != 0 for value in samples):
        raise ValueError('unexpected_audio_in_silent_profile')
    return dict(width=1080, height=1920, fps=30, sar='1:1', duration=duration,
                codec='h264', audio='silent_aac', faststart=True, cfr_verified=True,
                audio_samples=len(samples), full_decode_passed=True)


def cache_valid(bundle, identity):
    try:
        report = json.loads((bundle/'report.json').read_text())
        return (report['identity'] == identity and report['status'] in ('ready_for_review', 'needs_review') and
                report.get('integrity') == fingerprint({k:v for k,v in report.items() if k != 'integrity'}) and
                report.get('technical', {}).get('full_decode_passed') is True and
                {'source.png', 'spec.json', 'reel.mp4', 'cover.jpg', 'preview.jpg', 'text-layout.json', 'composition.json', 'ui-preview.jpg'} <= set(report['artifacts']) and
                all(Path(name).name == name and sha(bundle/name) == value
                    for name, value in report['artifacts'].items()))
    except (ValueError, KeyError, OSError):
        return False


def load_image_bundle(image_output, event_id):
    try:
        from .post_phase1 import get_phase1_current
    except ImportError:
        from post_phase1 import get_phase1_current
    return get_phase1_current(Path(image_output), event_id, approved_only=False)


def _prepare_from_images(image_output, event_id, output, duration=10):
    if not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', event_id):
        raise ValueError('invalid_event_id')
    if type(duration) is not int or not 10 <= duration <= 15:
        raise ValueError('invalid_phase_one_duration_10_to_15')
    bundle, images = load_image_bundle(image_output, event_id)
    if images['status'] not in ('ready_for_review', 'approved') or not images.get('selected'):
        raise ValueError('image_bundle_not_ready')
    spec, issues = make_spec(bundle, images)
    fonts = reels.typography()
    vinyl = reels.ROOT/'assets/vinyl.png'
    identity = fingerprint(dict(engine=VERSION, renderer=sha(Path(reels.__file__)),
        pipeline=sha(Path(__file__)), composition_engine=sha(Path(__file__).with_name('reel_composition.py')), input_report=sha(bundle/'report.json'), spec=spec,
        fonts=fonts, font_files={role:sha(face['path']) for role, face in fonts.items()},
        vinyl=sha(vinyl), duration=duration))
    output = Path(output).resolve()
    target = output/event_id/identity
    pointer = output/'current'/f'{event_id}.json'
    if pointer.exists():
        try:
            current = json.loads(pointer.read_text())
            candidate = (output/current['bundle']).resolve()
            if candidate.parent == target.parent and current.get('identity') == identity:
                target = candidate
        except (ValueError, KeyError, TypeError):
            pass  # An invalid pointer cannot select an unrelated or damaged cached result.
    report = None
    if cache_valid(target, identity):
        report = json.loads((target/'report.json').read_text())
    if report is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent, prefix='.render-') as work:
            work = Path(work)
            report = dict(schema=1, identity=identity, event_id=event_id, engine=VERSION,
                status='needs_review', approved=False, issues=issues,
                image_bundle=str(bundle), image_version=images['version'],
                image_status=images['status'], generated_background=images['selected'].get('generated',False),
                caption_note=images.get('caption_note'), spec=spec,
                source_sha256=sha(spec['image']), duration=duration, event=images['event'],
                facts_sha256=fingerprint(images['event']), preflight_issues=issues[:],
                archive_test=images['event'].get('production_scope')=='archive-test-only')
            # Keep the exact background that was selected for reproducibility.
            shutil.copyfile(spec['image'], work/'source.png')
            write_json(work/'spec.json', dict(spec, image='source.png'))
            stage = 'composition'
            try:
                local_spec = dict(spec, image=str(work/'source.png'))
                reels.render(local_spec, work/'reel.mp4', duration)
                stage = 'validation'
                report['technical'] = validate_video(work/'reel.mp4', duration)
                with tempfile.TemporaryDirectory() as layers:
                    reels.compose_layers(local_spec, Path(layers), fonts)
                    try:
                        from .reel_composition import measure
                    except ImportError:
                        from reel_composition import measure
                    with Image.open(vinyl) as image:
                        image.convert('RGBA').resize((reels.VINYL_SIZE,reels.VINYL_SIZE)).save(Path(layers)/'vinyl-preview.png')
                    composition = measure(Path(layers),images['selected'],
                        (reels.VINYL_X,reels.VINYL_Y,reels.VINYL_SIZE),mode=spec['background_mode'])
                    for name in ('text-layout.json','source-placement.json','composition.json','ui-preview.jpg'):
                        shutil.copyfile(Path(layers)/name, work/name)
                    report['composition'] = composition
                    report['issues'] = composition['issues']
                    report['preflight_resolution'] = 'actual_pixel_geometry; contain is the accepted full-source template'
                stage = 'cover'
                subprocess.run(['ffmpeg','-y','-v','error','-ss','3','-i',str(work/'reel.mp4'),
                    '-frames:v','1',str(work/'cover.jpg')], check=True, timeout=30)
                with Image.open(work/'cover.jpg') as cover:
                    cover.resize((405,720)).save(work/'preview.jpg')
                report['status'] = 'needs_review' if report['issues'] else 'ready_for_review'
            except ValueError as exc:
                report['issues'].append(str(exc))
                report['reason'] = 'composition_requires_editor' if stage == 'composition' else 'invalid_video_or_artifact'
                if stage != 'composition':
                    report['status'] = 'failed'
                report['stage'] = stage
            except Exception as exc:
                report['status'] = 'failed'
                report['reason'] = 'render_or_validation_failed'
                report['error_type'] = type(exc).__name__
                report['stage'] = stage
                report['message'] = str(exc)
            report['artifacts'] = {p.name:sha(p) for p in work.iterdir() if p.is_file()}
            # Cached drafts never inherit an approval from the post or template.
            report['integrity'] = fingerprint(report)
            write_json(work/'report.json', report)
            if target.exists():
                # Preserve altered/failed output; publish a separate recovery version.
                target = target.with_name(identity+'-'+str(time.time_ns()))
            os.replace(work, target)
    if report['status'] in ('needs_review', 'ready_for_review') and report.get('technical', {}).get('full_decode_passed'):
        write_json(output/'current'/f'{event_id}.json',
                   dict(event_id=event_id, bundle=str(target.relative_to(output)), identity=identity,
                        status=report['status']))
    else:
        write_json(output/'attempts'/f'{event_id}.json',
                   dict(event_id=event_id, bundle=str(target.relative_to(output)), identity=identity,
                        status=report['status'], reason=report.get('reason')))
    return target, report


def failure_report(exc, stage='preflight'):
    if isinstance(exc, FileNotFoundError):
        code = 'missing_file'
    elif isinstance(exc, (ValueError, KeyError, TypeError)):
        code = 'invalid_input_or_configuration'
    elif isinstance(exc, OSError):
        code = 'filesystem_error'
    else:
        code = 'technical_error'
    return dict(schema=1, status='failed', approved=False, stage=stage,
                reason=code, error_type=type(exc).__name__, message=str(exc), issues=[code])


def prepare_from_images(image_output, event_id, output, duration=10):
    """Phase-one boundary: always returns (bundle or None, structured report)."""
    try:
        return _prepare_from_images(image_output, event_id, output, duration)
    except Exception as exc:
        report = failure_report(exc)
        report['event_id'] = event_id if isinstance(event_id, str) else None
        try:
            path = Path(output)/'errors'/(str(time.time_ns())+'.json')
            write_json(path, report)
            report['error_report'] = str(path.resolve())
        except (OSError, ValueError, TypeError) as save_error:
            report['persistence_error'] = type(save_error).__name__
        return None, report


def main():
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)
    return cli(Parser)


def cli(parser_type=argparse.ArgumentParser):
    parser = parser_type(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--event', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=int, default=10)
    try:
        args = parser.parse_args()
        path, report = prepare_from_images(args.images, args.event, args.output, args.duration)
    except Exception as exc:
        path, report = None, failure_report(exc, stage='arguments')
    print(json.dumps(dict(bundle=str(path) if path else None, **report), ensure_ascii=False))
    return 1 if report['status']=='failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
