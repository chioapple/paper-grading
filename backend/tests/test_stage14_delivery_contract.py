import json
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert "alembic downgrade base" not in workflow
    assert "alembic downgrade 20260722_0017" in workflow
    assert "grep -qx '20260722_0017'" in workflow
    assert workflow.count("20260728_0019") >= 3
    assert "grep -q '^20260726_0018 '" not in workflow
    assert "grep -qx '20260726_0018'" in workflow
    assert workflow.count("grep -Eq '^20260728_0019( \\(head\\))?$'") == 2
    migration_setup = workflow.split(
        "Prepare Supabase-owned schemas in the disposable database", 1
    )[1].split("Replay empty database to 0018, 0019, 0017, and 0019", 1)[0]
    for role in ("anon", "authenticated", "service_role"):
        assert f"create role {role} nologin;" in migration_setup.lower()
    assert "--baseline .secrets.baseline" in workflow
    assert "--disable-plugin KeywordDetector" not in workflow
    assert "backend/migrations" in workflow
    baseline = json.loads((PROJECT_ROOT / ".secrets.baseline").read_text(encoding="utf-8"))
    assert baseline["results"] == {}


def test_sites_and_local_deployment_keep_public_and_secret_boundaries_separate() -> None:
    hosting = json.loads(
        (PROJECT_ROOT / "frontend/.openai/hosting.json").read_text(encoding="utf-8")
    )
    sites_worker = (PROJECT_ROOT / "frontend/sites/worker.js").read_text(encoding="utf-8")
    component_runner = (PROJECT_ROOT / "infra/local/run-component.sh").read_text(encoding="utf-8")
    launch_installer = (PROJECT_ROOT / "infra/local/install-launch-agents.sh").read_text(
        encoding="utf-8"
    )
    production_template = (PROJECT_ROOT / "infra/local/production.env.example").read_text(
        encoding="utf-8"
    )

    assert hosting["project_id"]
    assert hosting["d1"] is None
    assert hosting["r2"] is None
    for header in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        assert header in sites_worker
    assert 'new URL("/index.html", request.url)' in sites_worker
    assert "--host 127.0.0.1" in component_runner
    assert "app.workers.supervisor" in component_runner
    assert "--queues=paper_grading.exports" in component_runner
    api_section = component_runner.split("  api)", 1)[1].split("  ;;", 1)[0]
    grading_section = component_runner.split("  grading)", 1)[1].split("  ;;", 1)[0]
    export_section = component_runner.split("  export)", 1)[1].split("  ;;", 1)[0]
    assert "unset EXPORT_DATABASE_URL" in api_section
    assert "unset EXPORT_DATABASE_URL" in grading_section
    assert "unset AUTH_INVITE_REDIRECT_URL" in grading_section
    assert "unset PROVIDER_MASTER_KEY" in export_section
    assert "unset DATABASE_URL" in export_section
    watchdog = (PROJECT_ROOT / "infra/local/watchdog.sh").read_text(encoding="utf-8")
    assert "unset PROVIDER_MASTER_KEY" in watchdog
    assert '.venv/bin/celery" -b "$REDIS_URL"' in watchdog
    assert "-A app.workers.celery_app:celery_app" not in watchdog
    assert 'local label="com.paper-grading.$component"' in launch_installer
    for component in ("api", "grading", "export"):
        assert f"write_component_plist {component}" in launch_installer
    for component in ("tailscale", "watchdog"):
        assert f"write_single_program_plist {component}" in launch_installer
    assert "redis://127.0.0.1:6379/0" in production_template
    assert not (PROJECT_ROOT / "infra/render.yaml").exists()


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
    assert "applySitesBypassHeader" in real_flow
    assert "setViewportSize({ width: 390, height: 844 })" in real_flow
    assert "stage14-playwright-reporter" in real_config
    assert "outputDir:" in real_config
    assert "STAGE14_E2E_OUTPUT_DIR" in real_config
    assert "timeout: 1_800_000" in real_config
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
    assert "Codex Sites" in deployment
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


def test_local_deployment_scripts_reference_shared_runtime_boundaries() -> None:
    installer = (PROJECT_ROOT / "infra/local/install-launch-agents.sh").read_text(encoding="utf-8")
    runtime = (PROJECT_ROOT / "infra/local/verify-runtime.sh").read_text(encoding="utf-8")
    watchdog = (PROJECT_ROOT / "infra/local/watchdog.sh").read_text(encoding="utf-8")
    component_runner = (PROJECT_ROOT / "infra/local/run-component.sh").read_text(encoding="utf-8")
    predeployment_gate = (PROJECT_ROOT / "infra/local/stage14-predeployment-gate.sh").read_text(
        encoding="utf-8"
    )
    release_preparer = (PROJECT_ROOT / "infra/local/prepare-release.sh").read_text(encoding="utf-8")
    env_updater = (PROJECT_ROOT / "infra/local/update-production-env.sh").read_text(
        encoding="utf-8"
    )
    funnel = (PROJECT_ROOT / "infra/local/stage14-funnel.sh").read_text(encoding="utf-8")
    tailscale = (PROJECT_ROOT / "infra/local/tailscale-login.sh").read_text(encoding="utf-8")
    e2e_runner = (PROJECT_ROOT / "infra/local/run-stage14-e2e.sh").read_text(encoding="utf-8")
    runtime_common = (PROJECT_ROOT / "infra/local/stage14-runtime-common.sh").read_text(
        encoding="utf-8"
    )

    assert "Library/Application Support/Paper Grading" in runtime_common
    assert "stage14_env_dir" in installer
    assert "stage14_logs_dir" in installer
    assert "CURRENT_ROOT/infra/local/run-component.sh" in installer
    assert "--rollback-first-install" in installer
    assert "stage14_first_install_rollback=true" in installer
    assert "stage14_local_runtime_verified=true" in runtime
    assert "stage14_state_dir" in runtime
    assert "funnel status --json" in runtime
    assert "curl --config" in watchdog
    assert "heartbeat.uptimerobot.com" in watchdog
    assert "shared/env/production.env" in component_runner
    assert "CELERYBEAT_SCHEDULE_FILENAME" in component_runner
    assert "stage14_predeployment_gate=true" in predeployment_gate
    assert "--self-check" in predeployment_gate
    assert "releases/$sha" in release_preparer
    assert ".release-manifest.json" in runtime_common
    assert "SEALED" in runtime_common
    assert "shared_bin/switch-release.sh" in release_preparer
    assert "--env-dir" in env_updater
    assert "production.env" in env_updater
    assert "grading-worker.env" in env_updater
    assert "serve get-config" in funnel
    assert "serve set-config" in funnel
    assert "funnel status --json" in funnel
    assert 'payload.get("BackendState") != "Running"' in tailscale
    assert "tailscaled.pid" in runtime_common
    assert "--start" in e2e_runner
    assert "--resume" in e2e_runner
    assert "--postcondition" in e2e_runner
    assert "O_EXCL" in e2e_runner
    assert "STAGE14_E2E_OUTPUT_DIR" in e2e_runner
    assert "stage14_e2e_started=true" in e2e_runner


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="阶段 14 本机部署门禁只在 macOS 目标机执行",
)
def test_stage14_predeployment_gate_contract_scripts_exist_and_pass() -> None:
    required_executables = [
        "infra/local/stage14-predeployment-gate.sh",
        "infra/local/prepare-release.sh",
        "infra/local/validate-release.sh",
        "infra/local/switch-release.sh",
        "infra/local/update-production-env.sh",
        "infra/local/run-stage14-e2e.sh",
        "infra/local/stage14-funnel.sh",
        "infra/local/tailscale-login.sh",
        "infra/local/install-launch-agents.sh",
        "infra/local/verify-runtime.sh",
        "infra/local/watchdog.sh",
    ]

    for relative_path in required_executables:
        path = PROJECT_ROOT / relative_path
        assert path.exists(), f"缺少阶段 14 部署门禁脚本：{relative_path}"
        assert path.stat().st_mode & 0o111, f"脚本不可执行：{relative_path}"

    completed = subprocess.run(
        [str(PROJECT_ROOT / "infra/local/stage14-predeployment-gate.sh")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "stage14_predeployment_gate=true"
