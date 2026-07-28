"""Subprocess entry answering free-form chart questions via the trading profile.

Mirrors hermes_worker.py (single-turn LLM calls, stdout-only JSON envelope)
but drives a sandboxed code-execution loop: the model may answer arbitrary
statistical questions by writing Python that runs against the registered bars
CSV in an audited subprocess (see query_compute). Every number in the final
Korean answer must come from executed output or the supplied context JSON —
the model never does bar arithmetic itself.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

PROJECT_SRC: Final = Path(__file__).resolve().parent.parent
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from fractal_journal.hermes_worker import (  # noqa: E402
    HERMES_REPOSITORY,
    MAX_PROMPT_BYTES,
    HermesAgent,
    HermesAgentModule,
    HermesConfigModule,
    HermesRuntimeModule,
    WorkerRuntimeError,
)
from fractal_journal.hermes_worker_boundary import WorkerInputError  # noqa: E402
from fractal_journal.query_compute import (  # noqa: E402
    ComputationRound,
    run_query_loop,
)

CHART_QUERY_SYSTEM_PROMPT: Final = (
    "You are a technical-analysis study assistant for a private trading "
    "journal. Answer the trader's question in Korean. The context JSON "
    "supplies precomputed statistics; for anything beyond them you MUST "
    "compute the numbers yourself by replying with exactly one fenced "
    "```python code block (and nothing else in that reply). The block runs "
    "in a sandbox whose working directory contains the file named in "
    "bars_csv (columns date,open,high,low,close,volume, oldest first). "
    "Standard library only; no network, no subprocess, no file writes "
    "outside the working directory; 20-second limit; print() every result "
    "you need. After each execution you receive the stdout/stderr and then "
    "either run one more block or give the final Korean answer with no code "
    "fence. Every number in the final answer must come from executed output "
    "or the context JSON — never estimate or compute in your head. If a "
    "computation keeps failing, say so instead of guessing. Never issue a "
    "buy, sell, entry, exit, position-size, stop-loss, or other "
    "personalized trading instruction; describe structure and statistics "
    "only and remind that the final judgment belongs to the trader when "
    "relevant. Keep the final answer under 450 Korean words. Plain text "
    "with optional minimal markdown lists."
)

MAX_WORKER_COMPUTATIONS: Final = 4


def wrap_query_response(
    response: str,
    model: str,
    prompt: str,
    computations: tuple[ComputationRound, ...] = (),
) -> str:
    first_line = prompt.partition("\n")[0]
    input_hash = (
        first_line.removeprefix("INPUT_SHA256=")
        if first_line.startswith("INPUT_SHA256=")
        else sha256(prompt.encode()).hexdigest()
    )
    envelope = {
        "schema_version": "hermes_query_envelope.v2",
        "answered_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "model": model,
        "input_sha256": input_hash,
        "answer": response.strip(),
        "computations": [asdict(round_) for round_ in computations],
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def extract_workdir(prompt: str) -> Path | None:
    payload_line = prompt.rsplit("\n", 1)[-1]
    try:
        payload = json.loads(payload_line)
    except ValueError:
        return None
    workdir = payload.get("workdir") if isinstance(payload, dict) else None
    if not isinstance(workdir, str):
        return None
    path = Path(workdir)
    return path if path.is_dir() else None


def main() -> int:
    prompt = sys.stdin.buffer.read(MAX_PROMPT_BYTES + 1)
    if not prompt or len(prompt) > MAX_PROMPT_BYTES:
        raise WorkerInputError

    real_stdout = sys.stdout
    with (
        Path(os.devnull).open("w", encoding="utf-8") as devnull,
        redirect_stdout(devnull),
        redirect_stderr(devnull),
    ):
        response = _run_query(prompt.decode("utf-8"))
    _ = real_stdout.write(response)
    if not response.endswith("\n"):
        _ = real_stdout.write("\n")
    _ = real_stdout.flush()
    return 0


def _build_agent() -> HermesAgent:
    sys.path.insert(0, str(HERMES_REPOSITORY))

    config_module = importlib.import_module("hermes_cli.config")
    runtime_module = importlib.import_module("hermes_cli.runtime_provider")
    agent_module = importlib.import_module("run_agent")
    if not (
        isinstance(config_module, HermesConfigModule)
        and isinstance(runtime_module, HermesRuntimeModule)
        and isinstance(agent_module, HermesAgentModule)
    ):
        raise WorkerRuntimeError

    config = config_module.load_config()
    model_config = config.get("model") or {}
    if isinstance(model_config, str):
        model = model_config.strip()
        provider = None
    else:
        model = str(
            model_config.get("default") or model_config.get("model") or "",
        ).strip()
        configured_provider = str(model_config.get("provider") or "").strip()
        provider = configured_provider or None

    runtime = runtime_module.resolve_runtime_provider(
        requested=provider,
        target_model=model or None,
    )
    agent = agent_module.AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=model,
        enabled_toolsets=[],
        skip_memory=True,
        persist_session=False,
        quiet_mode=True,
        max_iterations=1,
        save_trajectories=False,
        ephemeral_system_prompt=CHART_QUERY_SYSTEM_PROMPT,
        platform="journal-query",
    )
    agent.suppress_status_output = True
    agent.stream_delta_callback = None
    agent.tool_gen_callback = None
    return agent


def _run_query(prompt: str) -> str:
    logging.disable(logging.CRITICAL)
    agent = _build_agent()

    def chat(message: str) -> str:
        return agent.chat(message) or ""

    workdir = extract_workdir(prompt)
    if workdir is None:
        return wrap_query_response(chat(prompt), agent.model, prompt)

    answer, computations = run_query_loop(
        chat,
        base_prompt=prompt,
        workdir=workdir,
        python_path=Path(sys.executable),
        max_rounds=MAX_WORKER_COMPUTATIONS,
    )
    return wrap_query_response(answer, agent.model, prompt, computations)


if __name__ == "__main__":
    raise SystemExit(main())
