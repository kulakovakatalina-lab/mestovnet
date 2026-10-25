"""Generate a synthetic archive-only job on the runner. No photo is uploaded."""
import argparse
from pathlib import Path
import tempfile
from PIL import Image,ImageDraw
try:
    from .reel_job import create_job
    from .reel_module import sha,fingerprint,write_json
except ImportError:
    from reel_job import create_job
    from reel_module import sha,fingerprint,write_json


def build(output,group=False):
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp)
        width,height=(1600,760) if group else (1080,1920)
        image=Image.new('RGB',(width,height));draw=ImageDraw.Draw(image)
        for y in range(height):
            draw.line((0,y,width,y),fill=(15+y//80,35+y//160,45+y//120))
        boxes=[]
        if group:
            for i in range(5):
                box=[.02+i*.2,.15,.18+i*.2,.95];boxes.append(box)
                draw.rectangle([round(box[0]*width),round(box[1]*height),round(box[2]*width),round(box[3]*height)],fill=(80+i*25,100,160))
        image.save(temp/'selected-source.png')
        event=dict(event_id='technical-fixture',title='Группа' if group else 'Тест\nрендера',
            date='2026-10-20',time='20:00',city='Тест',venue='Проверка рендера',
            source_url='https://example.invalid/archive-test',production_scope='archive-test-only')
        report=dict(event=event,version='synthetic-cloud-fixture-v2',
            selected=dict(source_sha256=sha(temp/'selected-source.png'),generated=False,
                analysis=dict(kind='group_photo' if group else 'illustration',faces=boxes,figures=boxes,important_regions=[],
                              watermark_regions=[],text_regions=[],conflicts=[])),
            caption_note='Synthetic programmatic gradient; no source photo, people, model calls or publishing.')
        report['identity']=fingerprint(report);write_json(temp/'report.json',report)
        return create_job(temp,report,output,archive=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--group',action='store_true');args=parser.parse_args()
    print(build(args.output,args.group))
