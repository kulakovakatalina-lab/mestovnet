"""Контракт мгновенной публикации решений модератора.

Это не делает сетевых запросов: проверяет, что Worker и GitHub Actions
остаются состыкованными. Реальная проверка после деплоя — /publish_test
в Telegram: она запускает тот же workflow без изменения афиши.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKER = (ROOT / "bot-cloudflare" / "worker.js").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "publish-moderation.yml").read_text(encoding="utf-8")


def test_worker_dispatches_the_immediate_publish_workflow():
    assert 'const MODERATION_PUBLISH_WORKFLOW = "publish-moderation.yml"' in WORKER
    assert "env.GITHUB_MODERATION_TOKEN" in WORKER
    assert "/actions/workflows/${MODERATION_PUBLISH_WORKFLOW}/dispatches" in WORKER
    assert "await triggerModerationPublish(env)" in WORKER


def test_admin_smoke_test_uses_the_same_publish_path():
    assert 'cmd === "publish_test"' in WORKER
    assert "const started = await triggerModerationPublish(env)" in WORKER
    assert "userId !== Number(env.ADMIN_ID)" in WORKER


def test_immediate_workflow_syncs_decisions_and_generates_the_site():
    assert "workflow_dispatch:" in WORKFLOW
    assert "group: site-publication" in WORKFLOW
    assert "MODERATION_WORKER_URL: ${{ secrets.MODERATION_WORKER_URL }}" in WORKFLOW
    assert "MODERATION_SYNC_TOKEN: ${{ secrets.MODERATION_SYNC_TOKEN }}" in WORKFLOW
    assert "python moderation_queue.py" in WORKFLOW
    assert "python generate_pages.py" in WORKFLOW
    assert 'git push origin HEAD:main' in WORKFLOW
