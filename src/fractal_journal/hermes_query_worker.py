"""Subprocess entry answering free-form chart questions via the trading profile.

Mirrors hermes_worker.py (tool-less, single-turn, stdout-only JSON envelope)
but returns free Korean prose instead of the review selection envelope.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
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
    HermesAgentModule,
    HermesConfigModule,
    HermesRuntimeModule,
    WorkerRuntimeError,
)
from fractal_journal.hermes_worker_boundary import WorkerInputError  # noqa: E402

CHART_QUERY_SYSTEM_PROMPT: Final = (
    "You are a technical-analysis study assistant for a private trading "
    "journal. Answer the trader's question in Korean using ONLY the numbers "
    "in the supplied context JSON (full-history MA cross events with forward "
    "returns, aggregates, and recent bars). If the question needs a statistic "
    "that is not present, say exactly which computation is missing instead of "
    "estimating it. Never issue a buy, sell, entry, exit, position-size, "
    "stop-loss, or other personalized trading instruction; describe structure "
    "and statistics only and remind that the final judgment belongs to the "
    "trader when relevant. Do not use tools, request more data, or claim "
    "access to bars outside the context. Keep the answer under 450 Korean "
    "words. Plain text with optional minimal markdown lists."
)


def wrap_query_response(response: str, model: str, prompt: str) -> str:
    first_line = prompt.partition("\n")[0]
    input_hash = (
        first_line.removeprefix("INPUT_SHA256=")
        if first_line.startswith("INPUT_SHA256=")
        else sha256(prompt.encode()).hexdigest()
    )
    envelope = {
        "schema_version": "hermes_query_envelope.v1",
        "answered_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "model": model,
        "input_sha256": input_hash,
        "answer": response.strip(),
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


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


def _run_query(prompt: str) -> str:
    logging.disable(logging.CRITICAL)
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
    response = agent.chat(prompt) or ""
    return wrap_query_response(response, agent.model, prompt)


if __name__ == "__main__":
    raise SystemExit(main())
