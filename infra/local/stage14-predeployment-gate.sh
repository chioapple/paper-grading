#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

project_root=$(stage14_project_root)
required_scripts=(
  stage14-predeployment-gate.sh
  verify-supabase-browser-config.sh
  prepare-release.sh
  validate-release.sh
  switch-release.sh
  update-production-env.sh
  run-stage14-e2e.sh
  stage14-funnel.sh
  tailscale-login.sh
  install-launch-agents.sh
  verify-runtime.sh
  watchdog.sh
)

if [[ "${1:-}" = "--self-check" ]]; then
  for name in "${required_scripts[@]}"; do
    test -x "$project_root/infra/local/$name"
  done
  stage14_self_check_ok
fi

for name in "${required_scripts[@]}"; do
  /bin/zsh -n "$project_root/infra/local/$name"
  "$project_root/infra/local/$name" --self-check >/dev/null
done

test -x "$project_root/.venv/bin/python"
test -x "$project_root/frontend/node_modules/.bin/tsc"
/usr/bin/env PYTHONPATH="$project_root/backend" "$project_root/.venv/bin/python" -c \
  'from app.config import Settings, WorkerSettings, ExportWorkerSettings'
node --check "$project_root/e2e/stage14-playwright-reporter.mjs"

# 类型检查只读执行；禁用增量缓存，避免门禁修改封存源码。
(
  cd "$project_root/frontend"
  ./node_modules/.bin/tsc -b --pretty false --incremental false >/dev/null

  export E2E_REAL_TEACHER_PASSWORD=stage14-test-only # pragma: allowlist secret
  export E2E_REAL_OTHER_TEACHER_PASSWORD=stage14-test-only # pragma: allowlist secret
  E2E_REAL=true \
  E2E_REAL_BASE_URL=https://stage14.invalid \
  STAGE14_E2E_OUTPUT_DIR="$project_root/tmp/stage14-gate-output" \
  E2E_REAL_WRITES=I_ACCEPT_STAGE14_TEST_WRITES \
  E2E_REAL_MODEL_CALLS=I_ACCEPT_ONE_COMPLETE_MODEL_FLOW \
  E2E_REAL_TEACHER_EMAIL=stage14@example.invalid \
  E2E_REAL_TEACHER_DISPLAY_NAME=stage14 \
  E2E_REAL_OTHER_TEACHER_EMAIL=stage14-other@example.invalid \
  E2E_REAL_MODEL_LABEL=stage14 \
  E2E_REAL_ASSIGNMENT_TITLE=stage14 \
  E2E_REAL_INSTRUCTIONS_PATH="$project_root/README.md" \
  E2E_REAL_RUBRIC_PATH="$project_root/README.md" \
  E2E_REAL_PAPER_PATH="$project_root/README.md" \
  E2E_REAL_TOTAL_SCORE=100 \
  E2E_REAL_SCORE_STEP=1 \
  ./node_modules/.bin/playwright test --config playwright.real.config.ts --list >/dev/null
)

print "stage14_predeployment_gate=true"
