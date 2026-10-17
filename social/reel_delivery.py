"""Version-bound review and local queue handoff. No platform publication calls.

The caller supplies real source-verification evidence and imported publication history.
Neither file mtime nor post_date is accepted as freshness evidence.
"""
from __future__ import annotations
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

try:
    from .reel_module import sha,fingerprint,write_json,cache_valid
except ImportError:
    from reel_module import sha,fingerprint,write_json,cache_valid

MOSCOW=ZoneInfo('Europe/Moscow')
CHECKS=('facts_match','legible','subjects_preserved','animation','safe_ui','no_old_text')
NONWAIVABLE=('faces','figures','watermark','cropped','incomplete','analysis','unsuitable','ui','gap')


def instant(value):
    dt=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('timezone_required')
    return dt


def canonical(event):
    return dict(event_id=event.get('event_id',event.get('id')),
        title=event.get('artist',event.get('title')),date=event.get('date'),time=event.get('time'),
        city=event.get('source_city',event.get('city')),venue=event.get('venue'))


def intact(bundle):
    bundle=Path(bundle).resolve();report=json.loads((bundle/'report.json').read_text())
    if not cache_valid(bundle,report['identity']):raise ValueError('reel_bundle_changed_or_incomplete')
    if not report.get('event') or report.get('facts_sha256')!=fingerprint(report['event']):
        raise ValueError('reel_facts_missing_or_changed')
    return bundle,report


def review_binding(bundle,report):
    names=['reel.mp4','cover.jpg','preview.jpg','text-layout.json','composition.json','ui-preview.jpg']
    return dict(identity=report['identity'],facts_sha256=report['facts_sha256'],
                artifacts={name:sha(bundle/name) for name in names})


def record_review(bundle,result,policy,output):
    """Accept an actual reviewer result. Does not manufacture a positive decision or owner."""
    bundle,report=intact(bundle)
    if result.get('reviewer') not in policy.get('reviewers',[]):raise ValueError('reviewer_not_in_policy')
    if result.get('decision') not in ('pass','reject'):raise ValueError('invalid_review_decision')
    instant(result['reviewed_at'])
    # A reviewer must attest to viewing actual complete video, not just a still.
    if result.get('binding')!=review_binding(bundle,report):raise ValueError('review_binding_mismatch')
    if result['decision']=='pass':
        if result.get('watched_full_video') is not True:raise ValueError('full_video_review_required')
        if any(result.get('checks',{}).get(k) is not True for k in CHECKS):raise ValueError('review_checks_incomplete')
    review=dict(schema=1,mode='policy_review',owner_approval=False,**result,
                policy_sha256=fingerprint(policy))
    review['integrity']=fingerprint(review);write_json(output,review)
    return review


def evaluate(bundle,event,verification,history,review,policy,now):
    bundle,report=intact(bundle);now=instant(now).astimezone(MOSCOW)
    if report.get('archive_test'):
        raise ValueError('archive_test_not_deliverable')
    facts=canonical(event)
    if facts!=canonical(report['event']):raise ValueError('event_facts_changed_rebuild_required')
    if any(not isinstance(v,str) or not v.strip() for v in facts.values()):raise ValueError('incomplete_event_facts')
    if event.get('hidden') or event.get('cancelled') or event.get('canceled') or event.get('needs_review'):
        raise ValueError('event_not_eligible')
    if str(event.get('moderation_status','')).lower() in ('rejected','cancelled','canceled','hidden','archived','pending'):
        raise ValueError('event_not_eligible')
    if verification.get('live_music_confirmed') is not True:raise ValueError('live_format_unverified')
    if not event.get('source_url','').startswith(('https://','http://')):raise ValueError('event_source_missing')
    if verification.get('facts_sha256')!=fingerprint(event) or verification.get('source_url')!=event['source_url']:
        raise ValueError('source_verification_not_bound_to_current_event')
    if verification.get('source_success') is not True or verification.get('copy_matches_source') is not True:
        raise ValueError('source_verification_incomplete')
    if verification.get('editorial_copy_sha256')!=fingerprint(report['event'].get('cover',{})):
        raise ValueError('editorial_copy_not_verified')
    checked=instant(verification['checked_at']).astimezone(MOSCOW)
    if checked>now or now-checked>timedelta(hours=24):raise ValueError('source_verification_stale')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',facts['time']):raise ValueError('invalid_event_time')
    start=datetime.fromisoformat(facts['date']+'T'+facts['time']).replace(tzinfo=MOSCOW)
    days=(start.date()-now.date()).days
    if start<=now or not 1<=days<=14:raise ValueError('outside_reel_announcement_window')
    if history.get('imported') is not True:raise ValueError('publication_history_not_imported')
    records=[item for item in history.get('records',[]) if item.get('event_id')==facts['event_id']]
    if any(item.get('state') in ('sending','unknown') for item in records):raise ValueError('reconcile_unknown_publication_first')
    published=[item for item in records if item.get('state')=='published' and item.get('format') in ('post','reel')]
    if any(not item.get('platform_receipt') for item in published):raise ValueError('unverified_publication_history')
    if len(published)>=2:raise ValueError('event_feed_limit_reached')
    if any(now-instant(item['published_at'])<timedelta(hours=72) for item in published):
        raise ValueError('event_repeat_before_72h')
    if review.get('integrity')!=fingerprint({k:v for k,v in review.items() if k!='integrity'}):raise ValueError('review_changed')
    if review.get('reviewer') not in policy.get('reviewers',[]) or review.get('policy_sha256')!=fingerprint(policy):
        raise ValueError('review_policy_mismatch')
    if review.get('binding')!=review_binding(bundle,report):raise ValueError('review_outdated')
    reviewed=instant(review['reviewed_at']).astimezone(MOSCOW)
    if reviewed>now or now-reviewed>timedelta(hours=24):raise ValueError('visual_review_stale')
    if review.get('decision')!='pass' or review.get('watched_full_video') is not True or any(review.get('checks',{}).get(k) is not True for k in CHECKS):
        raise ValueError('visual_review_not_passed')
    waivers=review.get('waivers',{})
    for issue in report['issues']:
        # Only a false-positive important-object bounding box may be resolved by the configured reviewer.
        if issue!='protected_important_regions_overlap' or any(term in issue for term in NONWAIVABLE):
            raise ValueError('blocking_composition_issue:'+issue)
        if not policy.get('allow_important_region_resolution',False) or not isinstance(waivers.get(issue),str) or len(waivers[issue].strip())<20:
            raise ValueError('unresolved_composition_issue:'+issue)
    return dict(event_id=facts['event_id'],identity=report['identity'],video_sha256=sha(bundle/'reel.mp4'),
        facts_sha256=fingerprint(event),verification_sha256=fingerprint(verification),
        review_sha256=fingerprint(review),policy_sha256=fingerprint(policy),validated_at=now.isoformat())


def enqueue(bundle,event,verification,history,review,policy,now,queue):
    """Atomic local handoff; consumer MUST call evaluate again immediately before sending."""
    decision=evaluate(bundle,event,verification,history,review,policy,now)
    queue=Path(queue).resolve();queue.mkdir(parents=True,exist_ok=True)
    job_id=fingerprint(dict(event_id=decision['event_id'],identity=decision['identity']))
    target=queue/'jobs'/job_id;target.parent.mkdir(exist_ok=True)
    with sqlite3.connect(queue/'queue.sqlite',timeout=10,isolation_level=None) as db:
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,event_id TEXT,state TEXT,bundle TEXT)')
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT id,state FROM jobs WHERE event_id=? AND state IN (?,?,?)',
                            (decision['event_id'],'queued','sending','unknown')).fetchall()
        if any(state in ('sending','unknown') for _,state in existing):
            raise ValueError('reconcile_queue_publication_first')
        if existing and existing!=[(job_id,'queued')]:raise ValueError('event_already_queued_or_inflight')
        previous=db.execute('SELECT state FROM jobs WHERE id=?',(job_id,)).fetchone()
        if previous and previous[0]=='published':
            db.execute('COMMIT')
            return target,dict(status='already_published',publication_performed=False,decision=decision)
        if target.exists():
            intact(target)
            receipt=json.loads((target/'job.json').read_text())
            if receipt['decision']['video_sha256']!=sha(target/'reel.mp4'):raise ValueError('queue_artifact_changed')
            if receipt['decision']['identity']!=decision['identity']:raise ValueError('queue_identity_mismatch')
        else:
            with tempfile.TemporaryDirectory(dir=target.parent) as work:
                work=Path(work)
                original=json.loads((Path(bundle)/'report.json').read_text())
                for name in list(original['artifacts'])+['report.json']:
                    shutil.copyfile(Path(bundle)/name,work/name)
                receipt=dict(schema=1,status='queued',publication_performed=False,decision=decision,
                             event=event,verification=verification,review=review,policy=policy)
                write_json(work/'job.json',receipt)
                work.rename(target)
        db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?,?)',(job_id,decision['event_id'],'queued',str(target)))
        db.execute('COMMIT')
    return target,receipt


def enqueue_project(bundle,project,verification,history,review,policy,now,queue,*,image_output=None):
    project=Path(project)
    # Apply the site's actual override rules, rather than duplicating a partial copy.
    import importlib.util
    spec=importlib.util.spec_from_file_location('reels_site_settings',project/'generate_pages.py')
    site=importlib.util.module_from_spec(spec);spec.loader.exec_module(site)
    events=site.apply_settings(json.loads((project/'events.json').read_text()),
                              json.loads((project/'settings.json').read_text()))
    _,report=intact(bundle)
    try:
        from .reel_module import load_image_bundle
    except ImportError:
        from reel_module import load_image_bundle
    if image_output is None:
        if not report.get('image_bundle'):raise ValueError('image_output_required_for_portable_job')
        image_output=Path(report['image_bundle']).parent.parent
    current,current_report=load_image_bundle(image_output,report['event_id'])
    if current_report['version']!=report['image_version']:
        raise ValueError('image_bundle_no_longer_current')
    event=next((e for e in events if e.get('id')==report['event_id']),None)
    if event is None:raise ValueError('event_missing_hidden_or_cancelled')
    if not (project/'event'/report['event_id']).is_file():raise ValueError('project_event_card_missing')
    return enqueue(bundle,event,verification,history,review,policy,now,queue)
