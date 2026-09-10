# Supervisor Agents

An OpenAI Codex plugin skill for supervisor-led, multi-agent work.

The supervisor plans the work, delegates independent tasks, assigns distinct models, preserves state outside the chat context, collects evidence-based reports, handles model failures, and verifies the final result with executable checks.

## What it does

- Keeps Codex accountable as the single supervisor.
- Routes agents by task fit, context window, capabilities, speed, and cost.
- Enforces one unique `provider/model` per agent in a run.
- Retries transient failures with bounded exponential backoff.
- Uses cooldowns and provider circuit breakers after repeated failures.
- Resumes failed agents from durable checkpoints instead of restarting blindly.
- Stores task ledgers, reports, decisions, and verification evidence outside the active chat context.
- Supports optional Obsidian, Hermes Agent, OpenCode, MCP, vector, and graph-memory integrations.
- Requires independent verification before completion claims.

## Install and use

```powershell
codex plugin marketplace add C:\path\to\supervisor-agents
codex plugin add supervisor-agents@<marketplace-name>
```

At the beginning of a Codex chat, write:

```text
Use supervisor-agents mode for this task.
```

For strict operation, add:

```text
Use separate models for every delegated agent. Inspect live model metadata before assignment. Persist reports and checkpoints, use bounded fallbacks on failure, and independently verify all material results.
```

## Fallback policy

Each agent receives a primary model and a ranked fallback set. A fallback must satisfy the task's minimum context, output, modality, and tool requirements and must not already be assigned to another active agent in the same wave. The supervisor classifies errors, retries transient failures with backoff and jitter, compacts context for overflow, cools down unhealthy models, opens provider circuit breakers, resumes from checkpoints, and records every substitution.

The supervisor never retries forever and never silently duplicates a model.

## External memory

Use Markdown/Obsidian for human-owned durable knowledge and SQLite/JSONL for operational state. A suggested layout is:

```text
AI-Memory/
  projects/<project>/overview.md
  projects/<project>/decisions/
  projects/<project>/facts/
  projects/<project>/incidents/
  projects/<project>/research/
  projects/<project>/tasks/<task-id>.md
  projects/<project>/runs/<run-id>/reports/
  projects/<project>/runs/<run-id>/artifacts/
  inbox/
  superseded/
```

## Integrations

This skill is runtime-neutral. It can delegate to native Codex workers, OpenCode CLI models, Hermes Agent profiles, or MCP/A2A tools when those are installed and authenticated. External outputs are evidence, not authority.

## Development

Validate the plugin before publishing:

```powershell
python <codex-skills>\\.system\\plugin-creator\\scripts\\validate_plugin.py .
```

Test fallback behavior with simulated rate limits, timeouts, provider outages, invalid requests, and context overflow.

## License

MIT. See [LICENSE](LICENSE).
