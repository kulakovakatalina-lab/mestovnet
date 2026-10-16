"""Проверяем авторизацию реальной точки входа Worker без запросов к Telegram."""
import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_webhook_requires_configured_secret_and_matching_header():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js нужен для исполнения Cloudflare Worker')
    source = (Path(__file__).resolve().parents[1] / 'bot-cloudflare' / 'worker.js').read_bytes()
    module_url = 'data:text/javascript;base64,' + base64.b64encode(source).decode()
    script = f'''
import worker from {json.dumps(module_url)};
import assert from 'node:assert/strict';
const accepted = [];
const ctx = {{ waitUntil(promise) {{ accepted.push(promise); }} }};
for (const [env, header] of [[{{}}, null], [{{WEBHOOK_SECRET: 'expected'}}, null],
                           [{{WEBHOOK_SECRET: 'expected'}}, 'wrong']]) {{
  const headers = header ? {{'X-Telegram-Bot-Api-Secret-Token': header}} : {{}};
  const response = await worker.fetch(new Request('https://worker.example/',
    {{method: 'POST', headers, body: '{{}}'}}), env, ctx);
  assert.equal(response.status, 403);
}}
assert.equal(accepted.length, 0);
const response = await worker.fetch(new Request('https://worker.example/',
  {{method: 'POST', headers: {{'X-Telegram-Bot-Api-Secret-Token': 'expected'}}, body: '{{}}'}}),
  {{WEBHOOK_SECRET: 'expected'}}, ctx);
assert.equal(response.status, 200);
assert.equal(accepted.length, 1);
await Promise.all(accepted);
'''
    subprocess.run([node, '--input-type=module', '-e', script], check=True,
                   capture_output=True, text=True, timeout=15)
