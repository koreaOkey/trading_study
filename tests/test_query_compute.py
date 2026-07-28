import sys
from pathlib import Path

from fractal_journal.query_compute import (
    ComputationRound,
    extract_python_code,
    run_query_loop,
    run_sandboxed,
    strip_code_fences,
)

_PYTHON = Path(sys.executable)


def _workdir(tmp_path: Path) -> Path:
    csv_path = tmp_path / "bars.csv"
    _ = csv_path.write_text(
        "date,open,high,low,close,volume\n"
        "2024-01-02T09:00:00,100,101,99,100,1000\n"
        "2024-01-02T13:00:00,100,103,100,102,1500\n",
        encoding="utf-8",
    )
    return tmp_path


def test_extract_python_code_finds_first_fence() -> None:
    text = "생각 중\n```python\nprint(1)\n```\n그리고\n```python\nprint(2)\n```"
    assert extract_python_code(text) == "print(1)"
    assert extract_python_code("코드 없음") is None
    assert extract_python_code("```python\n\n```") is None


def test_strip_code_fences_removes_blocks() -> None:
    text = "답변 앞\n```python\nprint(1)\n```\n답변 뒤"
    assert strip_code_fences(text) == "답변 앞\n\n답변 뒤"


def test_sandbox_reads_bars_csv(tmp_path: Path) -> None:
    workdir = _workdir(tmp_path)
    result = run_sandboxed(
        "import csv\n"
        "rows = list(csv.DictReader(open('bars.csv', encoding='utf-8')))\n"
        "print(len(rows), rows[-1]['close'])",
        workdir=workdir,
        python_path=_PYTHON,
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "2 102"
    assert not result.timed_out


def test_sandbox_blocks_reads_outside_workdir(tmp_path: Path) -> None:
    result = run_sandboxed(
        "open('/etc/passwd', encoding='utf-8').read()",
        workdir=_workdir(tmp_path),
        python_path=_PYTHON,
    )
    assert result.exit_code != 0
    assert "sandbox: read outside workdir" in result.stderr


def test_sandbox_blocks_writes_outside_workdir(tmp_path: Path) -> None:
    result = run_sandboxed(
        "open('/tmp/fjq-escape.txt', 'w', encoding='utf-8').write('x')",
        workdir=_workdir(tmp_path),
        python_path=_PYTHON,
    )
    assert result.exit_code != 0
    assert "sandbox: write outside workdir" in result.stderr


def test_sandbox_blocks_network_and_subprocess(tmp_path: Path) -> None:
    workdir = _workdir(tmp_path)
    network = run_sandboxed(
        "import socket\nsocket.getaddrinfo('example.com', 80)",
        workdir=workdir,
        python_path=_PYTHON,
    )
    assert network.exit_code != 0
    assert "sandbox: blocked socket" in network.stderr

    spawned = run_sandboxed(
        "import subprocess\nsubprocess.run(['ls'], check=False)",
        workdir=workdir,
        python_path=_PYTHON,
    )
    assert spawned.exit_code != 0
    assert "sandbox: blocked" in spawned.stderr


def test_sandbox_times_out(tmp_path: Path) -> None:
    result = run_sandboxed(
        "while True:\n    pass",
        workdir=_workdir(tmp_path),
        python_path=_PYTHON,
        timeout_seconds=2.0,
    )
    assert result.timed_out
    assert result.exit_code is None


def test_loop_executes_code_then_returns_final_answer(tmp_path: Path) -> None:
    workdir = _workdir(tmp_path)
    prompts: list[str] = []

    def chat(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return "계산합니다\n```python\nprint(40 + 2)\n```"
        return "실행 결과는 42입니다."

    answer, rounds = run_query_loop(
        chat,
        base_prompt="질문",
        workdir=workdir,
        python_path=_PYTHON,
    )
    assert answer == "실행 결과는 42입니다."
    assert len(rounds) == 1
    assert rounds[0].stdout.strip() == "42"
    assert rounds[0].exit_code == 0
    assert "STDOUT:\n42" in prompts[1]


def test_loop_returns_immediate_answer_without_execution(tmp_path: Path) -> None:
    answer, rounds = run_query_loop(
        lambda _prompt: "컨텍스트만으로 충분합니다.",
        base_prompt="질문",
        workdir=_workdir(tmp_path),
        python_path=_PYTHON,
    )
    assert answer == "컨텍스트만으로 충분합니다."
    assert rounds == ()


def test_loop_forces_final_answer_at_round_limit(tmp_path: Path) -> None:
    workdir = _workdir(tmp_path)
    prompts: list[str] = []

    def chat(prompt: str) -> str:
        prompts.append(prompt)
        if "code execution limit" in prompt:
            return "한도 도달, 최종 요약입니다.\n```python\nprint('무시')\n```"
        return "```python\nprint('again')\n```"

    answer, rounds = run_query_loop(
        chat,
        base_prompt="질문",
        workdir=workdir,
        python_path=_PYTHON,
        max_rounds=2,
    )
    assert answer == "한도 도달, 최종 요약입니다."
    assert len(rounds) == 2
    assert all(isinstance(round_, ComputationRound) for round_ in rounds)
