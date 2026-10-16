"""Публичные потребители используют статусы событий без ручных переопределений."""
import json
import re
import shutil
import subprocess

import pytest


def test_browser_map_and_bot_respect_publication_status(project_root):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js не установлен")
    events = [
        dict(id="visible", date="2999-01-01", artist="Группа", venue="Клуб"),
        dict(id="pending", date="2999-01-01", venue="Клуб", needs_review=True),
        dict(id="rejected", date="2999-01-01", venue="Клуб", moderation_status="rejected"),
        dict(id="cancelled", date="2999-01-01", venue="Клуб", cancelled=True),
        dict(id="source_cancelled", date="2999-01-01", venue="Клуб", source_status="cancelled"),
    ]
    checks = []
    for name in ("index.html", "genre.html"):
        source = (project_root / name).read_text()
        function = re.search(r"function publishedEvents\(data\) \{.*?^\}", source, re.S | re.M).group()
        checks.append("{\n" + function + ";\n" + """
const result = publishedEvents(events);
assert.deepEqual(result.map(e => e.id), ['visible', 'cancelled', 'source_cancelled']);
assert.equal(result[2].cancelled, true);
assert.equal(result[2]._origIdx, 4);
assert.equal(events[4].cancelled, undefined);
} 
""")
    source = (project_root / "map.html").read_text()
    function = re.search(r"function countUpcomingByVenue\(.*?^\}", source, re.S | re.M).group()
    checks.append("{\nconst todayStr = () => '2026-10-16';\n" + function + "\n" + """
assert.deepEqual(countUpcomingByVenue(events, {'Клуб': 'club'}), {club: 1});
}
""")
    bot = (project_root / "bot-cloudflare/worker.js").read_text()
    script = "import assert from 'node:assert/strict';\n" + bot
    script += "\nconst events = " + json.dumps(events, ensure_ascii=False) + ";\n"
    script += """
const requests = [];
globalThis.fetch = async url => {
  requests.push(url);
  return {json: async () => events};
};
assert.deepEqual((await fetchEvents()).map(e => e.id), ['visible']);
assert.deepEqual(requests, [EVENTS_URL]);
""" + "\n".join(checks)
    subprocess.run([node, "--input-type=module"], input=script, text=True, check=True,
                   capture_output=True, timeout=10)
