"""Sandboxed Python execution loop for free-form chart queries.

The query worker lets the Hermes trading profile answer arbitrary statistical
questions by writing Python that runs against the registered bar CSV. Numbers
must come from executed code, never from model arithmetic. The sandbox is a
separate ``python -I`` process confined by an audit hook (reads limited to the
work directory, the interpreter prefix, and /usr/share; writes limited to the
work directory; network, subprocess, and destructive os calls blocked) plus
self-imposed hard rlimits and a wall-clock timeout. Kept Python 3.11
compatible because it runs inside the Hermes venv.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

MAX_CODE_ROUNDS: Final = 4
EXEC_TIMEOUT_SECONDS: Final = 20.0
USER_CODE_FILENAME: Final = "_user_code.py"
CODE_CAP_CHARS: Final = 4_000
STDOUT_CAP_CHARS: Final = 6_000
STDERR_CAP_CHARS: Final = 1_500
_CAPTURE_READ_BYTES: Final = 65_536
_TRUNCATION_MARK: Final = "\n…[truncated]"

_PYTHON_FENCE: Final = re.compile(r"```python\n(?P<body>.*?)```", re.DOTALL)
_ANY_FENCE: Final = re.compile(r"```.*?```", re.DOTALL)

CONTINUE_SUFFIX: Final = (
    "\n\nUsing the execution results above, either reply with the final "
    "Korean answer (no code fences) or run one more ```python block if a "
    "further computation is required."
)
FINAL_ONLY_SUFFIX: Final = (
    "\n\nThe code execution limit is reached. Reply with the final Korean "
    "answer now using only the results above. Do not include any code fence."
)

# Runs inside the sandbox process before the model's code. Hard rlimits are
# self-imposed (hard == soft, so the user code cannot raise them back) and the
# audit hook cannot be bypassed from Python-level code.
_SANDBOX_RUNNER: Final = """
import os, resource, sys

for _limit, _value in (
    (resource.RLIMIT_CPU, 10),
    (resource.RLIMIT_AS, 1_073_741_824),
    (resource.RLIMIT_FSIZE, 8_388_608),
    (resource.RLIMIT_NOFILE, 128),
    (resource.RLIMIT_CORE, 0),
):
    resource.setrlimit(_limit, (_value, _value))

_WORKDIR = os.path.realpath(os.getcwd())
_ALLOWED_READ = tuple(
    os.path.realpath(p)
    for p in (
        _WORKDIR,
        sys.prefix,
        sys.base_prefix,
        sys.exec_prefix,
        sys.base_exec_prefix,
        "/usr/share",
    )
)
_DEVNULL = os.path.realpath(os.devnull)
_BLOCKED = (
    "socket.", "subprocess.", "ctypes.", "webbrowser.", "pty.", "shutil.",
    "ftplib.", "smtplib.", "poplib.", "imaplib.",
    "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork",
    "os.startfile", "os.remove", "os.unlink", "os.rmdir", "os.rename",
    "os.link", "os.symlink", "os.chmod", "os.chown", "os.kill",
    "os.truncate", "os.putenv",
)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _real(raw):
    try:
        return os.path.realpath(os.fspath(raw))
    except (TypeError, ValueError):
        return None


def _within(path, roots):
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _audit(event, args):
    for prefix in _BLOCKED:
        if event.startswith(prefix):
            raise RuntimeError("sandbox: blocked " + event)
    if event == "open":
        raw, mode, flags = args
        if raw is None or isinstance(raw, int):
            return
        path = _real(raw)
        if path is None or path == _DEVNULL:
            return
        if isinstance(mode, str):
            writing = any(c in mode for c in "wax+")
        else:
            writing = bool(flags & _WRITE_FLAGS)
        if writing and not _within(path, (_WORKDIR,)):
            raise RuntimeError("sandbox: write outside workdir: " + path)
        if not _within(path, _ALLOWED_READ):
            raise RuntimeError("sandbox: read outside workdir: " + path)
    elif event in ("os.scandir", "os.listdir"):
        raw = args[0] if args else None
        if raw is None or isinstance(raw, int):
            return
        path = _real(raw)
        if path is not None and not _within(path, _ALLOWED_READ):
            raise RuntimeError("sandbox: listing outside workdir: " + path)


sys.addaudithook(_audit)

with open("_user_code.py", encoding="utf-8") as _handle:
    _source = _handle.read()
exec(compile(_source, "_user_code.py", "exec"), {"__name__": "__main__"})
"""


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


@dataclass(frozen=True, slots=True)
class ComputationRound:
    code: str
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool


def extract_python_code(text: str) -> str | None:
    match = _PYTHON_FENCE.search(text)
    if match is None:
        return None
    body = match.group("body").strip()
    return body or None


def strip_code_fences(text: str) -> str:
    return _ANY_FENCE.sub("", text).strip()


def _truncate(value: str, cap: int) -> str:
    if len(value) <= cap:
        return value
    return value[:cap] + _TRUNCATION_MARK


def _read_capture(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(_CAPTURE_READ_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        _ = process.poll()
    try:
        _ = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return


def run_sandboxed(
    code: str,
    *,
    workdir: Path,
    python_path: Path,
    timeout_seconds: float = EXEC_TIMEOUT_SECONDS,
) -> SandboxResult:
    _ = (workdir / USER_CODE_FILENAME).write_text(code, encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workdir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    with tempfile.TemporaryDirectory(prefix="fjq-capture-") as capture_dir:
        stdout_path = Path(capture_dir) / "stdout"
        stderr_path = Path(capture_dir) / "stderr"
        with (
            stdout_path.open("wb") as stdout_handle,
            stderr_path.open("wb") as stderr_handle,
        ):
            process = subprocess.Popen(  # noqa: S603
                (str(python_path), "-I", "-c", _SANDBOX_RUNNER),
                cwd=workdir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                shell=False,
                start_new_session=True,
            )
            timed_out = False
            try:
                exit_code: int | None = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                _kill_group(process)
                exit_code = None
                timed_out = True
        return SandboxResult(
            exit_code=exit_code,
            stdout=_read_capture(stdout_path),
            stderr=_read_capture(stderr_path),
            timed_out=timed_out,
        )


def _render_round(index: int, code: str, result: SandboxResult) -> str:
    return (
        f"\n\n[EXECUTION ROUND {index}]\n"
        f"```python\n{code}\n```\n"
        f"[RESULT exit_code={result.exit_code} timed_out={result.timed_out}]\n"
        f"STDOUT:\n{_truncate(result.stdout, STDOUT_CAP_CHARS)}\n"
        f"STDERR:\n{_truncate(result.stderr, STDERR_CAP_CHARS)}"
    )


def run_query_loop(  # noqa: PLR0913 -- one keyword per loop knob
    chat: Callable[[str], str],
    *,
    base_prompt: str,
    workdir: Path,
    python_path: Path,
    max_rounds: int = MAX_CODE_ROUNDS,
    timeout_seconds: float = EXEC_TIMEOUT_SECONDS,
) -> tuple[str, tuple[ComputationRound, ...]]:
    transcript = ""
    rounds: list[ComputationRound] = []
    response = chat(base_prompt)
    while True:
        code = extract_python_code(response)
        if code is None:
            return response.strip(), tuple(rounds)
        if len(rounds) >= max_rounds:
            final = chat(base_prompt + transcript + FINAL_ONLY_SUFFIX)
            return strip_code_fences(final), tuple(rounds)
        result = run_sandboxed(
            code,
            workdir=workdir,
            python_path=python_path,
            timeout_seconds=timeout_seconds,
        )
        rounds.append(
            ComputationRound(
                code=_truncate(code, CODE_CAP_CHARS),
                stdout=_truncate(result.stdout, STDOUT_CAP_CHARS),
                stderr=_truncate(result.stderr, STDERR_CAP_CHARS),
                exit_code=result.exit_code,
                timed_out=result.timed_out,
            ),
        )
        transcript += _render_round(len(rounds), code, result)
        response = chat(base_prompt + transcript + CONTINUE_SUFFIX)
