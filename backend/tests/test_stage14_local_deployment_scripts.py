"""阶段 14 本地部署脚本的只读代码门禁契约。"""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
MACOS_ONLY = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="阶段 14 本机部署脚本只在 macOS 目标机执行",
)
SCRIPT_NAMES = (
    "stage14-predeployment-gate.sh",
    "prepare-release.sh",
    "validate-release.sh",
    "switch-release.sh",
    "update-production-env.sh",
    "run-stage14-e2e.sh",
    "stage14-funnel.sh",
    "tailscale-login.sh",
    "install-launch-agents.sh",
    "verify-runtime.sh",
    "watchdog.sh",
)


def isolated_env() -> dict[str, str]:
    """只向脚本传递门禁需要的公开路径，避免测试失败时泄露调用者环境。"""
    return {
        "HOME": str(PROJECT_ROOT / "tmp/test-home"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
        "STAGE14_PROJECT_ROOT": str(PROJECT_ROOT),
        "STAGE14_RUNTIME_ROOT": str(PROJECT_ROOT / "tmp/test-runtime"),
        "TMPDIR": str(PROJECT_ROOT / "tmp"),
    }


def script_path(name: str) -> Path:
    return PROJECT_ROOT / "infra/local" / name


def test_stage14_required_scripts_exist_and_are_executable() -> None:
    for name in SCRIPT_NAMES:
        path = script_path(name)
        assert path.exists(), f"缺少脚本：{name}"
        assert path.stat().st_mode & stat.S_IXUSR, f"脚本不可执行：{name}"


@MACOS_ONLY
def test_stage14_required_scripts_support_self_check() -> None:
    env = isolated_env()
    for name in SCRIPT_NAMES:
        completed = subprocess.run(
            [str(script_path(name)), "--self-check"],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, (
            f"{name} 自检失败：stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )


@MACOS_ONLY
def test_stage14_predeployment_gate_passes_after_all_script_contracts_exist() -> None:
    env = isolated_env()
    completed = subprocess.run(
        [str(script_path("stage14-predeployment-gate.sh"))],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "stage14_predeployment_gate=true"


def test_stage14_predeployment_gate_does_not_overwrite_zsh_path() -> None:
    gate = script_path("stage14-predeployment-gate.sh").read_text(encoding="utf-8")

    assert 'for name in "${required_scripts[@]}"' in gate
    assert 'for path in "${required_scripts[@]}"' not in gate


@MACOS_ONLY
def test_tailscale_state_preparation_never_creates_an_empty_store(tmp_path: Path) -> None:
    common = script_path("stage14-runtime-common.sh")

    def prepare(runtime: Path) -> subprocess.CompletedProcess[str]:
        env = isolated_env() | {"STAGE14_RUNTIME_ROOT": str(runtime)}
        return subprocess.run(
            ["/bin/zsh", "-c", f'source "{common}"; stage14_prepare_tailscale_state'],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    missing_runtime = tmp_path / "missing"
    missing_dir = missing_runtime / "shared" / "tailscale"
    missing_dir.mkdir(parents=True)
    missing_state = missing_dir / "tailscaled.state"
    completed = prepare(missing_runtime)
    assert completed.returncode == 0, completed.stderr
    assert not missing_state.exists()

    empty_runtime = tmp_path / "empty"
    empty_dir = empty_runtime / "shared" / "tailscale"
    empty_dir.mkdir(parents=True)
    empty_state = empty_dir / "tailscaled.state"
    empty_state.touch()
    completed = prepare(empty_runtime)
    assert completed.returncode != 0
    assert "stage14_tailscale_state_empty=true" in completed.stderr

    valid_runtime = tmp_path / "valid"
    valid_dir = valid_runtime / "shared" / "tailscale"
    valid_dir.mkdir(parents=True)
    valid_state = valid_dir / "tailscaled.state"
    valid_state.write_text("{}", encoding="utf-8")
    valid_state.chmod(0o644)
    completed = prepare(valid_runtime)
    assert completed.returncode == 0, completed.stderr
    assert stat.S_IMODE(valid_state.stat().st_mode) == 0o600


@MACOS_ONLY
def test_funnel_enable_saves_all_service_config_before_enabling(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    fake_client = tmp_path / "tailscale"
    call_log = tmp_path / "tailscale.calls"
    fake_client.write_text(
        """#!/bin/zsh
set -euo pipefail
print -r -- "$*" >>"$STAGE14_FAKE_TAILSCALE_LOG"
if [[ "$#" = 4 && "$2" = serve && "$3" = get-config && "$4" = --all ]]; then
  print '{"version":"0.0.1"}'
  exit 0
fi
if [[ "$#" = 5 && "$2" = funnel && "$3" = --bg && "$4" = --yes && \
      "$5" = http://127.0.0.1:8000 ]]; then
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    fake_client.chmod(0o700)
    env = isolated_env() | {
        "STAGE14_RUNTIME_ROOT": str(runtime),
        "STAGE14_TAILSCALE_CLIENT_BIN": str(fake_client),
        "STAGE14_FAKE_TAILSCALE_LOG": str(call_log),
    }

    completed = subprocess.run(
        [str(script_path("stage14-funnel.sh")), "enable"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    snapshot = runtime / "shared" / "tailscale" / "serve-config.json"
    assert snapshot.read_text(encoding="utf-8") == '{"version":"0.0.1"}\n'
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        f"--socket={runtime}/shared/tailscale/tailscaled.sock serve get-config --all",
        f"--socket={runtime}/shared/tailscale/tailscaled.sock funnel --bg --yes "
        "http://127.0.0.1:8000",
    ]


@MACOS_ONLY
def test_funnel_enable_never_overwrites_an_existing_restore_snapshot(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    tailscale_dir = runtime / "shared" / "tailscale"
    tailscale_dir.mkdir(parents=True)
    snapshot = tailscale_dir / "serve-config.json"
    original_snapshot = '{"version":"0.0.1","services":{"original":{}}}\n'
    snapshot.write_text(original_snapshot, encoding="utf-8")
    snapshot.chmod(0o600)
    fake_client = tmp_path / "tailscale"
    call_log = tmp_path / "tailscale.calls"
    fake_client.write_text(
        """#!/bin/zsh
set -euo pipefail
print -r -- "$*" >>"$STAGE14_FAKE_TAILSCALE_LOG"
if [[ "$#" = 5 && "$2" = funnel && "$3" = --bg && "$4" = --yes && \
      "$5" = http://127.0.0.1:8000 ]]; then
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    fake_client.chmod(0o700)
    env = isolated_env() | {
        "STAGE14_RUNTIME_ROOT": str(runtime),
        "STAGE14_TAILSCALE_CLIENT_BIN": str(fake_client),
        "STAGE14_FAKE_TAILSCALE_LOG": str(call_log),
    }

    completed = subprocess.run(
        [str(script_path("stage14-funnel.sh")), "enable"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert snapshot.read_text(encoding="utf-8") == original_snapshot
    assert (
        call_log.read_text(encoding="utf-8")
        .strip()
        .endswith("funnel --bg --yes http://127.0.0.1:8000")
    )
    assert "get-config" not in call_log.read_text(encoding="utf-8")


@MACOS_ONLY
def test_funnel_enable_does_not_leave_a_partial_restore_snapshot(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    fake_client = tmp_path / "tailscale"
    fake_client.write_text(
        """#!/bin/zsh
set -euo pipefail
if [[ "$#" = 4 && "$2" = serve && "$3" = get-config && "$4" = --all ]]; then
  print -n '{"version":'
  exit 70
fi
exit 64
""",
        encoding="utf-8",
    )
    fake_client.chmod(0o700)
    env = isolated_env() | {
        "STAGE14_RUNTIME_ROOT": str(runtime),
        "STAGE14_TAILSCALE_CLIENT_BIN": str(fake_client),
    }

    completed = subprocess.run(
        [str(script_path("stage14-funnel.sh")), "enable"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    snapshot = runtime / "shared" / "tailscale" / "serve-config.json"
    assert not snapshot.exists()


@MACOS_ONLY
def test_funnel_enable_rejects_an_invalid_restore_snapshot(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    fake_client = tmp_path / "tailscale"
    call_log = tmp_path / "tailscale.calls"
    fake_client.write_text(
        """#!/bin/zsh
set -euo pipefail
print -r -- "$*" >>"$STAGE14_FAKE_TAILSCALE_LOG"
if [[ "$#" = 4 && "$2" = serve && "$3" = get-config && "$4" = --all ]]; then
  print 'not-json'
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    fake_client.chmod(0o700)
    env = isolated_env() | {
        "STAGE14_RUNTIME_ROOT": str(runtime),
        "STAGE14_TAILSCALE_CLIENT_BIN": str(fake_client),
        "STAGE14_FAKE_TAILSCALE_LOG": str(call_log),
    }

    completed = subprocess.run(
        [str(script_path("stage14-funnel.sh")), "enable"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    snapshot = runtime / "shared" / "tailscale" / "serve-config.json"
    assert not snapshot.exists()
    assert " funnel " not in call_log.read_text(encoding="utf-8")


@MACOS_ONLY
def test_funnel_restore_applies_the_saved_config_to_all_services(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    tailscale_dir = runtime / "shared" / "tailscale"
    tailscale_dir.mkdir(parents=True)
    snapshot = tailscale_dir / "serve-config.json"
    snapshot.write_text('{"version":"0.0.1"}\n', encoding="utf-8")
    snapshot.chmod(0o600)
    fake_client = tmp_path / "tailscale"
    call_log = tmp_path / "tailscale.calls"
    fake_client.write_text(
        """#!/bin/zsh
set -euo pipefail
print -r -- "$*" >>"$STAGE14_FAKE_TAILSCALE_LOG"
if [[ "$#" = 5 && "$2" = serve && "$3" = set-config && \
      "$4" = --all && "$5" = "$STAGE14_EXPECTED_CONFIG" ]]; then
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    fake_client.chmod(0o700)
    env = isolated_env() | {
        "STAGE14_RUNTIME_ROOT": str(runtime),
        "STAGE14_TAILSCALE_CLIENT_BIN": str(fake_client),
        "STAGE14_FAKE_TAILSCALE_LOG": str(call_log),
        "STAGE14_EXPECTED_CONFIG": str(snapshot),
    }

    completed = subprocess.run(
        [str(script_path("stage14-funnel.sh")), "restore"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert call_log.read_text(encoding="utf-8").strip() == (
        f"--socket={runtime}/shared/tailscale/tailscaled.sock serve set-config --all {snapshot}"
    )
    assert not snapshot.exists()


@MACOS_ONLY
def test_environment_writer_shell_quotes_every_user_supplied_value(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    release_sha = "1" * 40
    release = runtime / "releases" / release_sha
    validator = release / "infra" / "local" / "validate-release.sh"
    validator.parent.mkdir(parents=True)
    validator.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
    validator.chmod(0o700)
    runtime.mkdir(exist_ok=True)
    (runtime / "current").symlink_to(release)

    injection_marker = tmp_path / "environment-value-was-executed"
    database_url = (
        "postgresql+asyncpg://user:pa$(touch "
        f"{injection_marker})$HOME&word'quote@host/db?ssl=require"
    )
    inputs = [
        database_url,
        "postgresql+asyncpg://export:p&ss@host/db?ssl=require",
        "postgresql+asyncpg://grading:p$ss@host/db?ssl=require",
        "https://test-project.supabase.co",
        "publishable$key&value",
        "secret$key&value",
        "paper-grading-test",
        "master$key&value=",
        "https://frontend.example",
        "https://api.example",
        "https://heartbeat.uptimerobot.com/test?value=$HOME&ok=1",
    ]
    env = isolated_env() | {"STAGE14_RUNTIME_ROOT": str(runtime)}

    completed = subprocess.run(
        [str(script_path("update-production-env.sh")), "--create"],
        cwd=PROJECT_ROOT,
        env=env,
        input="\n".join(inputs) + "\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not injection_marker.exists()
    production_env = runtime / "shared" / "env" / "production.env"
    grading_env = runtime / "shared" / "env" / "grading-worker.env"
    source_check = subprocess.run(
        [
            "/bin/zsh",
            "-c",
            'set -euo pipefail; source "$PRODUCTION_ENV"; '
            'test "$DATABASE_URL" = "$EXPECTED_DATABASE_URL"; '
            'test "$SUPABASE_PUBLISHABLE_KEY" = "$EXPECTED_PUBLISHABLE_KEY"; '
            'test "$UPTIMEROBOT_HEARTBEAT_URL" = "$EXPECTED_HEARTBEAT_URL"; '
            'test "$PROVIDER_CALLS_ENABLED" = false; '
            'source "$GRADING_ENV"; '
            'test "$DATABASE_URL" = "$EXPECTED_GRADING_DATABASE_URL"',
        ],
        env=isolated_env()
        | {
            "PRODUCTION_ENV": str(production_env),
            "GRADING_ENV": str(grading_env),
            "EXPECTED_DATABASE_URL": database_url,
            "EXPECTED_PUBLISHABLE_KEY": inputs[4],
            "EXPECTED_HEARTBEAT_URL": inputs[10],
            "EXPECTED_GRADING_DATABASE_URL": inputs[2],
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert source_check.returncode == 0, source_check.stderr


@MACOS_ONLY
def test_switch_release_replaces_current_symlink_instead_of_writing_through_it(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    first_sha = "1" * 40
    second_sha = "2" * 40
    for sha in (first_sha, second_sha):
        release = runtime / "releases" / sha
        release.mkdir(parents=True)
        (release / "SEALED").write_text("", encoding="utf-8")

    env = isolated_env() | {"STAGE14_RUNTIME_ROOT": str(runtime)}
    for sha in (first_sha, second_sha):
        completed = subprocess.run(
            [str(script_path("switch-release.sh")), sha, "--prepare-only"],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr

    assert (runtime / "current").is_symlink()
    assert (runtime / "current").resolve() == runtime / "releases" / second_sha
    assert list((runtime / "releases" / first_sha).glob(".current.*")) == []
