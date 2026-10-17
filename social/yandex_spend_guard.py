"""Persistent RUB ceiling for an explicitly authorized, single-process API run.

Prices: https://aistudio.yandex.ru/ru/docs/ai-studio/pricing
Qwen context bound: https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/generation/models
Reserve the entire 256k context (rounded UP to 262144) plus output before
sending; uncertain charges remain reserved, including after interruption.
"""
import json
import threading
import httpx
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


class SpendGuard:
    def __init__(self, path, cap=200):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            'cap_rub': str(cap), 'tariff_date': '2026-10-17', 'requests': [],
            'pricing_url': 'https://aistudio.yandex.ru/ru/docs/ai-studio/pricing'}
        if Decimal(self.data['cap_rub']) != Decimal(str(cap)):
            raise ValueError('spend_cap_changed')
        self.case_id = None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        tmp.replace(self.path)

    def committed(self):
        return sum((Decimal(r['accounted_rub']) for r in self.data['requests']), Decimal(0))

    def reserve(self, kind, amount):
        with self.lock:
            if self.committed() + amount > Decimal(self.data['cap_rub']):
                raise RuntimeError('rub_budget_limit')
            row = {'id': len(self.data['requests']) + 1, 'case_id': self.case_id,
                   'kind': kind, 'state': 'uncertain_reserved',
                   'time': datetime.now(timezone.utc).isoformat(),
                   'reserved_rub': str(amount), 'accounted_rub': str(amount)}
            self.data['requests'].append(row)
            self.save()
            return row

    def wrap(self, transport):
        def post(url, **kwargs):
            body = kwargs.get('json', {})
            if url == 'https://ai.api.cloud.yandex.net/v1/chat/completions':
                if body.get('model', '').split('/')[-1] != 'qwen3.6-35b-a3b':
                    raise RuntimeError('unpriced_vision_model')
                limit = body.get('max_tokens')
                if type(limit) is not int or not 0 < limit <= 16384:
                    raise RuntimeError('unpriced_output_limit')
                kind = 'vision'
                amount = Decimal(262144) * Decimal('.0002') + Decimal(limit) * Decimal('.0003')
            elif url == 'https://ai.api.cloud.yandex.net/v1/images/generations':
                if body.get('model', '').split('/')[-1] != 'aliceai-image-art-3.0' or body.get('n') != 1:
                    raise RuntimeError('unpriced_generation_model')
                kind, amount = 'generation', Decimal('2.23')
            else:
                raise RuntimeError('unpriced_endpoint')
            row = self.reserve(kind, amount)
            # Transport or JSON errors retain the complete reservation.
            try:
                response = transport(url, **kwargs)
            except httpx.ConnectError:
                # TCP/TLS connection failed before the HTTP request could be sent.
                with self.lock:
                    row.update(state='connection_failed_before_send', accounted_rub='0',
                               error_type='ConnectError')
                    self.save()
                raise
            except BaseException as exc:
                with self.lock:
                    row['error_type'] = type(exc).__name__
                    self.save()
                raise
            with self.lock:
                row['http_status'] = response.status_code
                if kind == 'generation':
                    row.update(state='generation_request_accounted', accounted_rub='2.23')
                else:
                    result = response.json()
                    usage = result.get('usage', {})
                    row['usage'] = usage
                    row['response_id'] = result.get('id')
                    prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
                    if type(prompt) is int and type(completion) is int and 0 <= prompt <= 262144 and 0 <= completion <= limit:
                        # Charge all input at the uncached rate, a conservative upper estimate.
                        cost = Decimal(prompt) * Decimal('.0002') + Decimal(completion) * Decimal('.0003')
                        row.update(state='usage_accounted', accounted_rub=str(cost))
                self.save()
            return response
        return post
