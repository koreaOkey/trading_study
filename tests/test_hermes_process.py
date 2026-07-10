from __future__ import annotations

import os
import signal
import sys
from dataclasses import replace
from pathlib import Path

from fractal_journal.hermes_review import (
    HermesProcessRequest,
    SubprocessHermesRunner,
)


def test_subprocess_runner_stops_child_when_output_exceeds_cap() -> None:
    # Given
    finish_script = "sys.stdout.flush(); time.sleep(10)"
    script = f"import sys,time; sys.stdout.write('x' * 100000); {finish_script}"
    request = _real_process_request(script)

    # When
    result = SubprocessHermesRunner().run(replace(request, output_max_bytes=128))

    # Then
    assert result.oversized
    assert len(result.stdout) == 128


def test_subprocess_runner_kills_child_on_timeout() -> None:
    # Given
    request = _real_process_request("import time; time.sleep(10)")

    # When
    result = SubprocessHermesRunner().run(replace(request, timeout_seconds=0.01))

    # Then
    assert result.timed_out
    assert result.exit_code is None


def test_subprocess_runner_kills_descendant_process_group_on_timeout(
    tmp_path: Path,
) -> None:
    # Given
    pid_path = tmp_path / "descendant.pid"
    child_script = "import time; time.sleep(10)"
    parent_script = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_script!r}]); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(10)"
    )
    request = replace(_real_process_request(parent_script), timeout_seconds=0.1)

    # When
    result = SubprocessHermesRunner().run(request)
    descendant_pid = int(pid_path.read_text())
    descendant_running = _process_is_running(descendant_pid)
    if descendant_running:
        os.kill(descendant_pid, signal.SIGKILL)

    # Then
    assert result.timed_out
    assert not descendant_running


def _process_is_running(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
    except FileNotFoundError:
        return False
    return state != "Z"


def _real_process_request(code: str) -> HermesProcessRequest:
    return HermesProcessRequest(
        argv=(sys.executable, "-c", code),
        stdin=b"test",
        env={},
        timeout_seconds=2,
        output_max_bytes=4096,
    )
