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


def build(output):
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp)
        image=Image.new('RGB',(1080,1920));draw=ImageDraw.Draw(image)
        for y in range(1920):
            draw.line((0,y,1080,y),fill=(15+y//80,35+y//160,45+y//120))
        image.save(temp/'selected-source.png')
        event=dict(event_id='technical-fixture',title='Тест\nрендера',
            date='2026-10-20',time='20:00',city='Тест',venue='Проверка рендера',
            source_url='https://example.invalid/archive-test',production_scope='archive-test-only')
        report=dict(event=event,version='synthetic-cloud-fixture-v2',
            selected=dict(source_sha256=sha(temp/'selected-source.png'),generated=False,
                analysis=dict(kind='illustration',faces=[],figures=[],important_regions=[],
                              watermark_regions=[],text_regions=[],conflicts=[])),
            caption_note='Synthetic programmatic gradient; no source photo, people, model calls or publishing.')
        report['identity']=fingerprint(report);write_json(temp/'report.json',report)
        return create_job(temp,report,output,archive=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    print(build(parser.parse_args().output))
