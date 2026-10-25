"""Server entrypoint: current A2 -> render -> automatic review -> guarded queue.

Reads genuine freshness receipts/history supplied by the account/source services.
Missing evidence is a recorded skip, never an invented successful verification.
The publication consumer and its platform credentials remain outside this module.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import re
import time
from . import reel_module as m,reel_delivery as d,reel_review as visual


def run_event(project,images,event_id,output,verification,history,policy,provider_factory,*,now=None):
    live_clock=now is None
    now=now or datetime.now(timezone.utc);output=Path(output).resolve()
    result=dict(schema=1,event_id=event_id,recorded_at=now.isoformat(),publication_performed=False,
                manual_daily_action_required=False,status='skipped',stage='preflight')
    if not isinstance(event_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',event_id):
        raise ValueError('invalid_event_id')
    try:
        event=d.project_event(project,event_id)
        _,image=m.load_image_bundle(images,event_id)
        if image['event'].get('production_scope')=='archive-test-only':raise ValueError('archive_test_not_deliverable')
        d.verify_event(event,image['event'],verification,history,now)
        result['stage']='render'
        bundle,report=m.prepare_from_images(images,event_id,output/'renders')
        if bundle is None or report['status']=='failed':
            result.update(status='failed',reason=report.get('reason'),render_report=report)
        elif report['issues']:
            result.update(reason='blocking_composition',bundle=str(bundle),issues=report['issues'])
        else:
            result['stage']='visual_review';result['bundle']=str(bundle)
            path,review=visual.review(bundle,output/'reviews',provider_factory(),policy,now=now)
            result['review']=str(path)
            if review['decision']!='pass':result['reason']='visual_review_rejected'
            else:
                result['stage']='queue'
                # Re-read site overrides and current A2 just before the local handoff.
                path,receipt=d.enqueue_project(bundle,project,verification,history,review,policy,
                    datetime.now(timezone.utc) if live_clock else now,
                    output/'queue',image_output=images)
                result.update(status=receipt['status'],queue_job=str(path),reason=None)
    except ValueError as exc:
        result.update(status='skipped',reason=str(exc))
    except Exception as exc:
        result.update(status='failed',reason='processing_unavailable',error_type=type(exc).__name__)
    m.write_json(output/'runs'/f'{time.time_ns()}-{event_id}.json',result)
    m.write_json(output/'latest'/f'{event_id}.json',result)
    return result


def run_batch(project,images,output,verifications,history,policy,provider_factory,*,max_candidates=3,now=None):
    """Try alternatives automatically; at most one local queue job per invocation."""
    if type(max_candidates) is not int or not 1<=max_candidates<=5:raise ValueError('invalid_candidate_limit')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    with (output/'pipeline.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        candidates=[];skips=[]
        for pointer in sorted((Path(images)/'current').glob('*.json')):
            event_id=pointer.stem
            try:
                event=d.project_event(project,event_id)
                start=datetime.fromisoformat(event['date']+'T'+event['time']).replace(tzinfo=d.MOSCOW)
                clock=now or datetime.now(timezone.utc)
                if not 1<=(start.date()-clock.astimezone(d.MOSCOW).date()).days<=14:continue
                candidates.append((abs((start.date()-clock.astimezone(d.MOSCOW).date()).days-4),event['date'],event_id))
            except (ValueError,KeyError):
                skips.append(dict(event_id=event_id,status='skipped',reason='candidate_not_eligible'))
        results=[];attempts=0
        for _,_,event_id in sorted(candidates):
            if attempts>=max_candidates:break
            result=run_event(project,images,event_id,output,verifications.get(event_id,{}),history,
                             policy,provider_factory,now=now)
            results.append(result)
            if result['stage']!='preflight':attempts+=1
            if result['status']=='queued':break
        report=dict(schema=1,status='queued' if any(r['status']=='queued' for r in results) else 'no_release',
            publication_performed=False,results=results,candidate_skips=skips,
            reason=None if results else 'no_current_eligible_a2',recorded_at=datetime.now(timezone.utc).isoformat())
        m.write_json(output/'batch.json',report)
        return report


def main():
    class Parser(argparse.ArgumentParser):
        def error(self,message):raise ValueError(message)
    try:
        parser=Parser();parser.add_argument('--project',required=True,type=Path)
        parser.add_argument('--images',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
        parser.add_argument('--verifications',type=Path);parser.add_argument('--history',type=Path)
        parser.add_argument('--policy',required=True,type=Path);parser.add_argument('--budget-rub',type=float,default=75)
        args=parser.parse_args()
        from .reel_review_provider import YandexReelVision
        result=run_batch(args.project,args.images,args.output,
            json.loads(args.verifications.read_text()) if args.verifications else {},
            json.loads(args.history.read_text()) if args.history else {},json.loads(args.policy.read_text()),
            lambda:YandexReelVision(args.output/'spend.json',args.budget_rub))
        print(json.dumps(result,ensure_ascii=False))
        return 1 if any(row['status']=='failed' for row in result['results']) else 0
    except Exception as exc:
        print(json.dumps(m.failure_report(exc,stage='pipeline'),ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
