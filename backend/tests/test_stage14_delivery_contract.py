import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]


def test_ci_is_a_strict_non_deploying_gate_chain() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs = [
        "format-and-lint:",
        "strict-types:",
        "unit-tests:",
        "local-integration-tests:",
        "migration-replay:",
        "frontend-build:",
        "browser-tests:",
        "secret-scan:",
    ]

    positions = [workflow.index(f"  {job}") for job in jobs]
    assert positions == sorted(positions)
    assert "needs: format-and-lint" in workflow
    assert "needs: strict-types" in workflow
    assert "needs: unit-tests" in workflow
    assert "needs: local-integration-tests" in workflow
    assert "needs: migration-replay" in workflow
    assert "needs: frontend-build" in workflow
    assert "needs: browser-tests" in workflow
    assert "deployCommand" not in workflow
    assert "npm run audit:dependencies" in workflow
    assert "detect-secrets-hook" in workflow
    assert "postgres:16" in workflow
    assert "alembic downgrade base" in workflow
    assert workflow.count("20260728_0019") >= 3
    assert "grep -q '^20260726_0018 '" not in workflow
    assert "grep -qx '20260726_0018'" in workflow
    assert workflow.count("grep -Eq '^20260728_0019( \\(head\\))?$'") == 2
    migration_setup = workflow.split(
        "Prepare Supabase-owned schemas in the disposable database", 1
    )[1].split("Replay empty database to 0018, 0019, base, and 0019", 1)[0]
    for role in ("anon", "authenticated", "service_role"):
        assert f"create role {role} nologin;" in migration_setup.lower()
    assert "--baseline .secrets.baseline" in workflow
    assert "--disable-plugin KeywordDetector" not in workflow
    assert "backend/migrations" in workflow
    baseline = json.loads((PROJECT_ROOT / ".secrets.baseline").read_text(encoding="utf-8"))
    assert baseline["results"] == {}


def test_render_blueprint_keeps_paid_resources_manual_and_minimal() -> None:
    blueprint = (PROJECT_ROOT / "infra/render.yaml").read_text(encoding="utf-8")
    api = blueprint.split("name: paper-grading-api", 1)[1].split("name: paper-grading-worker", 1)[0]
    worker = blueprint.split("name: paper-grading-worker", 1)[1].split(
        "name: paper-grading-export-worker", 1
    )[0]
    export_worker = blueprint.split("name: paper-grading-export-worker", 1)[1].split(
        "name: paper-grading-queue", 1
    )[0]

    assert blueprint.count("autoDeployTrigger: 'off'") == 4
    assert "healthCheckPath: /health/ready" in api
    assert "X-Content-Type-Options" in blueprint
    assert "ipAllowList: []" in blueprint
    assert "maxmemoryPolicy: noeviction" in blueprint
    assert "SUPABASE_PUBLISHABLE_KEY" not in worker
    assert "AUTH_INVITE_REDIRECT_URL" not in worker
    assert "FRONTEND_ORIGIN" not in worker
    assert "paper_grading_worker.<project-ref>" in worker
    assert "PROVIDER_MASTER_KEY" not in export_worker
    assert "EXPORT_DATABASE_URL" in export_worker
    assert "127.0.0.1" not in blueprint
    assert "/mock" not in blueprint


def test_browser_and_runbook_boundaries_are_explicit() -> None:
    local_server = (PROJECT_ROOT / "e2e/local-mock-server.mjs").read_text(encoding="utf-8")
    real_flow = (PROJECT_ROOT / "e2e/real-full-flow.spec.ts").read_text(encoding="utf-8")
    real_config = (PROJECT_ROOT / "frontend/playwright.real.config.ts").read_text(encoding="utf-8")
    boundary = (PROJECT_ROOT / "e2e/README.md").read_text(encoding="utf-8")

    assert "127.0.0.1" in local_server
    assert "/mock" in local_server
    assert "I_ACCEPT_STAGE14_TEST_WRITES" in real_flow
    assert "I_ACCEPT_ONE_COMPLETE_MODEL_FLOW" in real_flow
    assert "I_ACCEPT_TWO_MODEL_BATCHES" not in real_flow
    assert real_flow.count('name: "创建批改任务"') == 1
    assert "setViewportSize({ width: 390, height: 844 })" in real_flow
    assert real_config.count('name: "real-chromium"') == 1
    assert "mobile-chromium" not in real_config
    assert "create_job_count=1" in boundary
    assert "邀请回调、设密和首次登录必须由人工浏览器证据完成" in boundary
    assert "真实数据" in boundary

    external_services = (
        PROJECT_ROOT / "backend/tests/test_stage14_external_services.py"
    ).read_text(encoding="utf-8")
    assert "test_real_account_deactivation_and_admin_boundary" in external_services
    assert "I_ACCEPT_DISABLE_AND_REENABLE_TEST_TEACHER" in external_services
    assert "I_ACCEPT_PROVIDER_CONNECTION_CALLS" in external_services

    for name in (
        "deployment.md",
        "rollback.md",
        "smoke-test.md",
        "monitoring-and-incidents.md",
    ):
        runbook = (PROJECT_ROOT / "docs/runbooks" / name).read_text(encoding="utf-8")
        assert "执行终端" in runbook
        assert "前置条件" in runbook
        assert "预期结果" in runbook
        assert "安全回传" in runbook

    deployment = (PROJECT_ROOT / "docs/runbooks/deployment.md").read_text(encoding="utf-8")
    smoke = (PROJECT_ROOT / "docs/runbooks/smoke-test.md").read_text(encoding="utf-8")
    monitoring = (PROJECT_ROOT / "docs/runbooks/monitoring-and-incidents.md").read_text(
        encoding="utf-8"
    )
    rollback = (PROJECT_ROOT / "docs/runbooks/rollback.md").read_text(encoding="utf-8")
    assert "Deploy a specific commit" in deployment
    assert "STAGE14_RELEASE_SHA" in deployment
    assert "${STAGE14_API_BASE_URL/https:/http:}" in smoke
    assert "allowed-cors.headers" in smoke
    assert "blocked-cors.headers" in smoke
    assert "x-content-type-options: nosniff" in smoke.lower()
    assert "x-frame-options: deny" in smoke.lower()
    assert "referrer-policy: no-referrer" in smoke.lower()
    assert "permissions-policy: camera=(), microphone=(), geolocation=()" in smoke.lower()
    assert "unacked" in smoke.lower()
    assert "签名 URL 过期" in smoke
    assert "实际收到" in monitoring
    assert "恢复发布候选" in rollback


def test_stage_fourteen_context_has_no_superseded_stage_five_blocker() -> None:
    context = (PROJECT_ROOT / "CONTEXT.md").read_text(encoding="utf-8")

    assert "第 6.1 节及之前全部完成" in context
    assert "第 5 节尚不能宣称全部完成" not in context
    assert "评分 Worker 丢失仍等待真实模型费用授权" not in context
