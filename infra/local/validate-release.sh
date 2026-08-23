#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && /bin/pwd -P)
source "$SCRIPT_DIR/stage14-runtime-common.sh"

if [[ "${1:-}" = "--self-check" ]]; then
  project_root=$(stage14_project_root)
  test -x "$project_root/.venv/bin/python"
  PYTHONPATH="$project_root/backend" "$project_root/.venv/bin/python" -c \
    'from app.config import Settings, WorkerSettings, ExportWorkerSettings'
  stage14_self_check_ok
fi

usage() {
  print -u2 "用法：validate-release.sh <完整 SHA> [--env-dir <path>]"
}

if [[ "${1:-}" = "--help" ]]; then
  usage
  exit 0
fi

if (( $# != 1 && $# != 3 )); then
  usage
  exit 2
fi

sha=$1
env_dir=""
if (( $# == 3 )); then
  test "$2" = "--env-dir"
  env_dir=$3
fi

stage14_assert_full_sha "$sha"

release=$(stage14_release_path "$sha")
manifest=$(stage14_release_manifest "$sha")
sealed_flag=$(stage14_release_sealed_flag "$sha")
python_bin="$release/.venv/bin/python"

test -d "$release"
test -f "$sealed_flag"
test -f "$manifest"
test -x "$python_bin"
test -f "$release/frontend/dist/server/index.js"
test -f "$release/frontend/.openai/hosting.json"

if [[ -n "$env_dir" ]]; then
  test -d "$env_dir"
  production_env="$env_dir/production.env"
  grading_env="$env_dir/grading-worker.env"
  stage14_require_regular_file "$production_env"
  stage14_require_regular_file "$grading_env"
fi

STAGE14_RELEASE="$release" \
STAGE14_MANIFEST="$manifest" \
STAGE14_ENV_DIR="$env_dir" \
PYTHONPATH="$release/backend" \
"$python_bin" - <<'PY'
import hashlib
import json
import os
from pathlib import Path

from app.config import ExportWorkerSettings, Settings, WorkerSettings

release = Path(os.environ["STAGE14_RELEASE"])
manifest = json.loads(Path(os.environ["STAGE14_MANIFEST"]).read_text(encoding="utf-8"))
assert manifest["sha"] == release.name
assert manifest["vite_api_base_url"].startswith("https://")
assert manifest["vite_supabase_url"].startswith("https://")
assert len(manifest["vite_supabase_publishable_key_sha256"]) == 64

env_dir = os.environ["STAGE14_ENV_DIR"]
if not env_dir:
    raise SystemExit(0)

production_lines = {}
for raw_line in (Path(env_dir) / "production.env").read_text(encoding="utf-8").splitlines():
    if raw_line and not raw_line.startswith("#"):
        key, value = raw_line.split("=", 1)
        production_lines[key] = value
grading_lines = {}
for raw_line in (Path(env_dir) / "grading-worker.env").read_text(encoding="utf-8").splitlines():
    if raw_line and not raw_line.startswith("#"):
        key, value = raw_line.split("=", 1)
        grading_lines[key] = value

assert production_lines["VITE_API_BASE_URL"] == manifest["vite_api_base_url"]
assert production_lines["VITE_SUPABASE_URL"] == manifest["vite_supabase_url"]
assert (
    hashlib.sha256(
        production_lines["VITE_SUPABASE_PUBLISHABLE_KEY"].encode("utf-8")
    ).hexdigest()
    == manifest["vite_supabase_publishable_key_sha256"]
)

common_env = dict(production_lines)
Settings.model_validate(common_env)
ExportWorkerSettings.model_validate(common_env)
worker_env = dict(common_env)
worker_env.update(grading_lines)
WorkerSettings.model_validate(worker_env)
PY

print "stage14_release_validated=true"
