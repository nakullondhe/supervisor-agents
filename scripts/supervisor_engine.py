#!/usr/bin/env python3
"""Stateful, provider-neutral orchestration engine for Supervisor Agents.

The engine keeps operational state outside the model context, routes unique
models, builds bounded context packs, and executes OpenCode workers when asked.
It intentionally uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CONTEXT_CHARS = 48_000
TRANSIENT_ERRORS = {"rate_limit", "timeout", "provider_outage", "tool_failure"}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def resolve_command(command: str) -> str:
    """Resolve executable shims consistently across Windows and POSIX."""
    resolved = shutil.which(command)
    if resolved:
        return resolved
    if os.name == "nt" and not command.lower().endswith(".cmd"):
        resolved = shutil.which(command + ".cmd")
        if resolved:
            return resolved
    return command


def atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
        fh.write(payload)
        temp = Path(fh.name)
    os.replace(temp, path)


@dataclass
class Model:
    id: str
    provider: str
    context: int = 0
    output: int = 0
    toolcall: bool = False
    reasoning: bool = False
    attachment: bool = False
    cost_input: float = 0.0
    cost_output: float = 0.0


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    status: str = "pending"
    model: str | None = None
    fallback_models: list[str] = field(default_factory=list)
    report_path: str | None = None
    checkpoint_path: str | None = None
    attempts: int = 0
    last_error: str | None = None
    verification: list[str] = field(default_factory=list)


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / "state.json"
        self.reports = root / "reports"
        self.artifacts = root / "artifacts"

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": 1, "created_at": now(), "updated_at": now(), "tasks": {},
                    "used_models": [], "unavailable_models": {}, "provider_health": {},
                    "fallbacks": [], "events": []}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = now()
        atomic_write(self.state_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    def event(self, state: dict[str, Any], kind: str, **data: Any) -> None:
        state.setdefault("events", []).append({"at": now(), "kind": kind, **data})
        self.save(state)


def _json_blocks(raw: str) -> Iterable[tuple[str, dict[str, Any]]]:
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("opencode/") or lines[i].startswith("openrouter/"):
            model_id = lines[i].strip()
            i += 1
            if i < len(lines) and lines[i].strip() == "{":
                start = i
                depth = 0
                while i < len(lines):
                    depth += lines[i].count("{") - lines[i].count("}")
                    if depth == 0:
                        break
                    i += 1
                blob = "\n".join(lines[start:i + 1])
                try:
                    yield model_id, json.loads(blob)
                except json.JSONDecodeError:
                    pass
        i += 1


def inventory(command: str = "opencode") -> list[Model]:
    command = resolve_command(command)
    proc = subprocess.run([command, "models", "--verbose"], text=True, capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"{command} models failed with {proc.returncode}")
    result = []
    for model_id, data in _json_blocks(proc.stdout):
        limit = data.get("limit", {})
        caps = data.get("capabilities", {})
        cost = data.get("cost", {})
        result.append(Model(
            id=model_id,
            provider=data.get("providerID", model_id.split("/", 1)[0]),
            context=int(limit.get("context", 0) or 0),
            output=int(limit.get("output", 0) or 0),
            toolcall=bool(caps.get("toolcall")),
            reasoning=bool(caps.get("reasoning")),
            attachment=bool(caps.get("attachment")),
            cost_input=float(cost.get("input", 0) or 0),
            cost_output=float(cost.get("output", 0) or 0),
        ))
    return result


class Router:
    def __init__(self, models: list[Model], state: dict[str, Any]):
        self.models = {m.id: m for m in models}
        self.state = state

    def choose(self, *, min_context: int = 0, needs_tools: bool = False,
               needs_reasoning: bool = False, needs_attachment: bool = False,
               preferred_provider: str | None = None) -> Model:
        used = set(self.state.get("used_models", []))
        unavailable = set(self.state.get("unavailable_models", {}).keys())
        candidates = [m for m in self.models.values() if m.id not in used and m.id not in unavailable]
        candidates = [m for m in candidates if m.context >= min_context]
        if needs_tools:
            candidates = [m for m in candidates if m.toolcall]
        if needs_reasoning:
            candidates = [m for m in candidates if m.reasoning]
        if needs_attachment:
            candidates = [m for m in candidates if m.attachment]
        if not candidates:
            raise RuntimeError("no unused compatible model remains")
        candidates.sort(key=lambda m: (
            0 if preferred_provider and m.provider == preferred_provider else 1,
            m.cost_input + m.cost_output,
            -m.context,
            -m.output,
        ))
        selected = candidates[0]
        used.add(selected.id)
        self.state["used_models"] = sorted(used)
        return selected


def classify_error(text: str) -> str:
    value = text.lower()
    if any(x in value for x in ("429", "rate limit", "too many requests", "retry-after")):
        return "rate_limit"
    if "timed out" in value or "timeout" in value:
        return "timeout"
    if any(x in value for x in ("503", "502", "504", "unavailable", "connection reset", "overloaded")):
        return "provider_outage"
    if "context" in value and any(x in value for x in ("exceed", "length", "token", "too large")):
        return "context_overflow"
    if any(x in value for x in ("401", "403", "unauthorized", "api key")):
        return "authentication"
    if "tool" in value:
        return "tool_failure"
    return "invalid_request"


def context_pack(store: StateStore, state: dict[str, Any], task_id: str, budget: int) -> str:
    task = state["tasks"][task_id]
    chunks = [f"# Task {task_id}: {task['title']}\n\n{task['prompt']}\n"]
    chunks.append("## Run state\n" + json.dumps({
        "status": task["status"], "model": task.get("model"),
        "attempts": task.get("attempts", 0), "last_error": task.get("last_error"),
    }, indent=2))
    for path in sorted(store.reports.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.append(f"\n## Report: {path.name}\n{text}")
    result = "\n".join(chunks)
    if len(result) <= budget:
        return result
    # Preserve the task and state; trim older report prose deterministically.
    marker = "\n\n[context pack truncated; consult the durable reports directory for full evidence]\n"
    if budget <= len(marker):
        return marker[:budget]
    return result[:budget - len(marker)] + marker


def run_worker(store: StateStore, state: dict[str, Any], task_id: str, model: str,
               opencode: str, max_retries: int, context_budget: int) -> int:
    task = state["tasks"][task_id]
    task["model"] = model
    task["status"] = "running"
    store.save(state)
    prompt = context_pack(store, state, task_id, context_budget)
    for attempt in range(1, max_retries + 2):
        task["attempts"] = attempt
        proc = subprocess.run([resolve_command(opencode), "run", "-m", model, prompt], text=True, capture_output=True, check=False)
        output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
        report = store.reports / f"{task_id}-attempt-{attempt}.md"
        atomic_write(report, f"# Agent report: {task_id}\n\nModel: `{model}`\nAttempt: {attempt}\n\n{output}")
        task["report_path"] = str(report)
        if proc.returncode == 0:
            task["status"] = "reported"
            store.event(state, "worker_reported", task_id=task_id, model=model, attempt=attempt)
            return 0
        error_type = classify_error(output)
        task["last_error"] = error_type
        store.event(state, "worker_failed", task_id=task_id, model=model, attempt=attempt, error_type=error_type)
        if error_type not in TRANSIENT_ERRORS or attempt > max_retries:
            task["status"] = "failed"
            store.save(state)
            return proc.returncode or 1
        delay = min(60, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
        time.sleep(delay)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stateful Supervisor Agents engine")
    parser.add_argument("--state-dir", default=".supervisor", help="durable run-state directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    inv = sub.add_parser("inventory")
    inv.add_argument("--opencode", default="opencode")
    add = sub.add_parser("add-task")
    add.add_argument("title")
    add.add_argument("prompt")
    pack = sub.add_parser("context-pack")
    pack.add_argument("task_id")
    pack.add_argument("--budget", type=int, default=DEFAULT_CONTEXT_CHARS)
    choose = sub.add_parser("choose")
    choose.add_argument("--opencode", default="opencode")
    choose.add_argument("--min-context", type=int, default=0)
    choose.add_argument("--needs-tools", action="store_true")
    choose.add_argument("--needs-reasoning", action="store_true")
    choose.add_argument("--needs-attachment", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("task_id")
    run.add_argument("model")
    run.add_argument("--opencode", default="opencode")
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--context-budget", type=int, default=DEFAULT_CONTEXT_CHARS)
    args = parser.parse_args(argv)
    store = StateStore(Path(args.state_dir).resolve())
    state = store.load()
    if args.command == "init":
        store.save(state)
        print(store.state_path)
        return 0
    if args.command == "inventory":
        print(json.dumps([asdict(m) for m in inventory(args.opencode)], indent=2))
        return 0
    if args.command == "add-task":
        task_id = "task-" + uuid.uuid4().hex[:8]
        state["tasks"][task_id] = asdict(Task(task_id, args.title, args.prompt,
                                               report_path=str(store.reports / f"{task_id}.md"),
                                               checkpoint_path=str(store.artifacts / f"{task_id}.checkpoint.json")))
        store.event(state, "task_added", task_id=task_id, title=args.title)
        print(task_id)
        return 0
    if args.command == "context-pack":
        print(context_pack(store, state, args.task_id, args.budget))
        return 0
    if args.command == "choose":
        selected = Router(inventory(args.opencode), state).choose(
            min_context=args.min_context, needs_tools=args.needs_tools,
            needs_reasoning=args.needs_reasoning, needs_attachment=args.needs_attachment)
        store.save(state)
        print(json.dumps(asdict(selected), indent=2))
        return 0
    if args.command == "run":
        return run_worker(store, state, args.task_id, args.model, args.opencode,
                          args.max_retries, args.context_budget)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
