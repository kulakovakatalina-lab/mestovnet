"""Инварианты деплоя, не дающие выдать устаревший CDN-ответ за релиз."""


def _workflow(project_root):
    return (project_root / ".github" / "workflows" / "deploy-yandex.yml").read_text(encoding="utf-8")


def test_dynamic_content_is_revalidated_at_origin(project_root):
    workflow = _workflow(project_root)

    # Картинки имеют content-addressed имена и могут кэшироваться долго;
    # HTML/JSON/XML/TXT отражают текущую афишу и обязаны перепроверяться.
    assert '"public, max-age=2592000"' in workflow
    assert workflow.count('"no-cache, max-age=0, must-revalidate"') == 5


def test_deploy_writes_and_checks_an_exact_release_marker(project_root):
    workflow = _workflow(project_root)

    assert "deployment.json" in workflow
    assert 'EXPECTED_RELEASE="$(git rev-parse HEAD)"' in workflow
    assert "CDN отдаёт текущий релиз" in workflow
    assert 'actual == expected' in workflow
    assert "?v=${{ github.run_id }}" not in workflow


def test_cdn_purge_is_automatic_when_minimal_credentials_are_configured(project_root):
    workflow = _workflow(project_root)

    assert "YC_CDN_RESOURCE_ID" in workflow
    assert "YC_SA_JSON_CREDENTIALS" in workflow
    assert "yc-actions/yc-iam-token@v1" in workflow
    assert '"paths":[]' in workflow, "Нужна полная очистка: перечень страниц динамический"
    assert "cdn.api.cloud.yandex.net/cdn/v1/cache/" in workflow
    assert "operation.api.cloud.yandex.net/operations/" in workflow
    assert "Cloud CDN очищен" in workflow
