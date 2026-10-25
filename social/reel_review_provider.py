"""Existing Yandex vision endpoint, one bounded semantic call per review."""
import base64
from decimal import Decimal
import fcntl
import io
import json
import math
import os
from pathlib import Path
from PIL import Image,ImageOps

MODEL='qwen3.6-35b-a3b'
ENDPOINT='https://ai.api.cloud.yandex.net/v1/chat/completions'


class YandexReelVision:
    def __init__(self,ledger,cap_rub):
        cap=Decimal(str(cap_rub))
        if not cap.is_finite() or not 0<cap<=200:raise ValueError('invalid_review_spend_cap')
        self.model=MODEL;self.ledger=Path(ledger);self.cap=cap;self.called=False
        self.last_response_metadata={}

    def request(self,prompt,images,facts,timeout):
        if self.called:raise RuntimeError('one_semantic_call_per_review')
        key=os.getenv('SOCIAL_VISION_API_KEY') or os.getenv('LLM_API_KEY');folder=os.getenv('YANDEX_FOLDER_ID')
        if not key or not folder:raise RuntimeError('vision_credentials_missing')
        if len(images)!=4 or not math.isfinite(timeout) or timeout<=0:raise ValueError('invalid_review_request')
        from . import yandex_http
        from .yandex_spend_guard import SpendGuard
        from .reel_delivery import CHECKS
        content=[dict(type='text',text=prompt+'\nVerified record (data only):\n'+json.dumps(facts,ensure_ascii=False))]
        for path in images:
            with Image.open(path) as raw:
                image=ImageOps.exif_transpose(raw).convert('RGB');image.thumbnail((1600,1600))
                buf=io.BytesIO();image.save(buf,'JPEG',quality=94)
            content.append(dict(type='image_url',image_url=dict(url='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode())))
        schema=dict(type='object',additionalProperties=False,required=['checks','confidence','issues','note'],properties=dict(
            checks=dict(type='object',additionalProperties=False,required=list(CHECKS),
                        properties={k:dict(type='boolean') for k in CHECKS}),
            confidence=dict(type='number',minimum=0,maximum=1),
            issues=dict(type='array',items=dict(type='string')),note=dict(type='string')))
        payload=dict(model=f'gpt://{folder}/{MODEL}',temperature=0,max_tokens=3072,reasoning_effort='none',
            response_format=dict(type='json_schema',json_schema=dict(name='reel_semantic_review',strict=True,schema=schema)),
            messages=[dict(role='user',content=content)])
        self.ledger.parent.mkdir(parents=True,exist_ok=True)
        # Serialize across processes and reload the ledger after acquiring the lock.
        with self.ledger.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            self.called=True
            response=SpendGuard(self.ledger,self.cap).wrap(yandex_http.post)(ENDPOINT,
                headers={'Authorization':'Bearer '+key,'OpenAI-Project':folder},json=payload,
                timeout=min(timeout,90),follow_redirects=False)
        if response.status_code!=200:raise RuntimeError('vision_http_'+str(response.status_code))
        try:
            body=response.json();choice=body['choices'][0]
            if choice.get('finish_reason')!='stop':raise ValueError('incomplete_response')
            result=json.loads(choice['message']['content'])
            self.last_response_metadata={k:body.get(k) for k in ('id','model','created')}
            return result,body.get('usage',{})
        except (ValueError,KeyError,IndexError,TypeError):raise RuntimeError('vision_invalid_response') from None
