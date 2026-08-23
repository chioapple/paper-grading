#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  project_root=$(stage14_project_root)
  test -x "$project_root/frontend/node_modules/.bin/playwright"
  node --check "$project_root/e2e/stage14-playwright-reporter.mjs"
  stage14_self_check_ok
fi

action="${1:-}"
case "$action" in
  --start|--resume|--postcondition) ;;
  *)
    print -u2 '用法：run-stage14-e2e.sh --start|--resume|--postcondition'
    exit 2
    ;;
esac

current_root_link=$(stage14_current_root)
current_root=$(stage14_resolve_symlink_target "$current_root_link")
stage14_load_env_file "$(stage14_env_dir)/production.env"
stage14_install_secure_dir "$(stage14_acceptance_dir)" 700

if [[ "$action" != "--start" ]]; then
  print -u2 "stage14_e2e_${action#--}=not_implemented"
  exit 1
fi

required_names=(
  STAGE14_SITES_BYPASS_TOKEN
  E2E_REAL_BASE_URL
  E2E_REAL_TEACHER_EMAIL
  E2E_REAL_TEACHER_PASSWORD
  E2E_REAL_TEACHER_DISPLAY_NAME
  E2E_REAL_OTHER_TEACHER_EMAIL
  E2E_REAL_OTHER_TEACHER_PASSWORD
  E2E_REAL_MODEL_LABEL
  E2E_REAL_ASSIGNMENT_TITLE
  E2E_REAL_INSTRUCTIONS_PATH
  E2E_REAL_RUBRIC_PATH
  E2E_REAL_PAPER_PATH
  E2E_REAL_TOTAL_SCORE
  E2E_REAL_SCORE_STEP
)
for name in "${required_names[@]}"; do
  test -n "${(P)name:-}"
done
test "${E2E_REAL_BASE_URL%/}" = "${FRONTEND_ORIGIN%/}"

E2E_INSTRUCTIONS_PATH="$E2E_REAL_INSTRUCTIONS_PATH" \
E2E_RUBRIC_PATH="$E2E_REAL_RUBRIC_PATH" \
E2E_PAPER_PATH="$E2E_REAL_PAPER_PATH" \
"$current_root/.venv/bin/python" - <<'PY'
import os
from pathlib import Path

for env_name in ("E2E_INSTRUCTIONS_PATH", "E2E_RUBRIC_PATH"):
    path = Path(os.environ[env_name])
    if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
        raise SystemExit("stage14_e2e_text_input_invalid")
    data = path.read_bytes()
    if not data or len(data) > 100 * 1024:
        raise SystemExit("stage14_e2e_text_input_invalid")
    data.decode("utf-8")

paper = Path(os.environ["E2E_PAPER_PATH"])
if not paper.is_file() or paper.suffix.lower() not in {".pdf", ".docx"}:
    raise SystemExit("stage14_e2e_paper_input_invalid")
if paper.stat().st_size <= 0 or paper.stat().st_size > 20 * 1024 * 1024:
    raise SystemExit("stage14_e2e_paper_input_invalid")
PY

title="${E2E_REAL_ASSIGNMENT_TITLE:-stage14-real-e2e}"
safe_title="${title//[^A-Za-z0-9._-]/_}"
run_dir="$(stage14_acceptance_dir)/${safe_title}"
marker="$run_dir/started.marker"
export STAGE14_E2E_OUTPUT_DIR="$run_dir/output"

mkdir -p "$run_dir" "$STAGE14_E2E_OUTPUT_DIR"
chmod 700 "$run_dir" "$STAGE14_E2E_OUTPUT_DIR"

python_bin="$current_root/.venv/bin/python"
MARKER_PATH="$marker" "$python_bin" - <<'PY'
import os

flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
fd = os.open(os.environ["MARKER_PATH"], flags, 0o600)
os.close(fd)
PY
print "stage14_e2e_started=true"

export E2E_REAL_WRITES=I_ACCEPT_STAGE14_TEST_WRITES
export E2E_REAL_MODEL_CALLS=I_ACCEPT_ONE_COMPLETE_MODEL_FLOW
(
  cd "$current_root"
  npm --prefix frontend run e2e:real
)
unset STAGE14_SITES_BYPASS_TOKEN
