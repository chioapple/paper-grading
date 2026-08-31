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
