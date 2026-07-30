"""在一个服务中监督相互隔离的评分与维护 Worker。"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from types import FrameType

CELERY_APPLICATION = "app.workers.celery_app:celery_app"
GRADING_QUEUE = "paper_grading.grading"
MAINTENANCE_QUEUE = "paper_grading.maintenance"


def worker_commands(python_executable: str = sys.executable) -> tuple[tuple[str, ...], ...]:
    """返回两个互不共享执行槽的 Worker 命令。"""

    common = (
        python_executable,
        "-m",
        "celery",
        "-A",
        CELERY_APPLICATION,
        "worker",
        "--loglevel=INFO",
        "--concurrency=1",
    )
    grading = common + (
        f"--queues={GRADING_QUEUE}",
        "--hostname=grading@%h",
    )
    maintenance = common + (
        f"--queues={MAINTENANCE_QUEUE}",
        "--hostname=maintenance@%h",
        "--beat",
    )
    return grading, maintenance


def main() -> int:
    """启动两个 Worker；任一退出时停止另一进程并让服务失败。"""

    requested_signal: int | None = None
    children: list[subprocess.Popen[bytes]] = []

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        nonlocal requested_signal
        requested_signal = requested_signal or signum

    previous_sigint = signal.signal(signal.SIGINT, request_shutdown)
    previous_sigterm = signal.signal(signal.SIGTERM, request_shutdown)
    exit_code = 1
    try:
        children = [subprocess.Popen(command) for command in worker_commands()]
        while requested_signal is None:
            for child in children:
                child_exit_code = child.poll()
                if child_exit_code is not None:
                    exit_code = child_exit_code or 1
                    requested_signal = signal.SIGTERM
                    break
            if requested_signal is None:
                time.sleep(0.25)
        if requested_signal in (signal.SIGINT, signal.SIGTERM):
            exit_code = 128 + requested_signal
    finally:
        shutdown_signal = requested_signal or signal.SIGTERM
        for child in children:
            if child.poll() is None:
                child.send_signal(shutdown_signal)
        for child in children:
            child.wait()
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
