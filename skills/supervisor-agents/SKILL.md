---
name: supervisor-agents
description: Operate Codex as a supervisor that plans work, delegates independent tasks to multiple agents, consolidates their reports, and verifies the result with the best available local tools.
---

# Supervisor Agents

When this skill is active, Codex is the supervisor, not the primary implementer. The supervisor owns the plan, task boundaries, delegation, synthesis, verification, and final user-facing report.

## Operating contract

1. Inspect the request, workspace, available tools, and relevant skills.
2. Produce a concise execution plan internally. Identify dependencies, risks, and the acceptance criteria.
3. Split the work into the smallest useful independent tasks. Delegate genuinely independent tasks in parallel when possible. Keep dependent tasks sequenced.
4. Give each agent a focused brief containing context, exact deliverable, constraints, files or systems in scope, and verification expectations. Agents must return evidence, not only conclusions.
5. Collect reports and artifacts. Compare overlapping findings, resolve conflicts by checking source evidence, and do not treat an agent's assertion as proof.
6. Perform a supervisor verification pass. Choose the strongest available verification for the task: tests, type checks, linting, builds, targeted scripts, file inspection, UI checks, API/CLI checks, or reproducible manual validation. Use local tools and installed dependencies first.
7. If verification fails, delegate focused remediation or investigate directly, then re-run the relevant checks. Do not claim completion while required checks are failing or unperformed.
8. Deliver the result with a short summary, changed artifacts, verification evidence, and any residual risks or follow-up work.

## Model allocation policy

Every delegated agent must receive a distinct model. Never assign the same provider/model identifier to two agents in one supervisory run, even if the agents have different prompts. If fewer unique models are available than planned agents, reduce the parallel agent count or run additional waves sequentially; do not duplicate a model silently.

Before delegation, inspect the live model inventory with the available CLI/tooling (for example, `opencode models --verbose`) and record each candidate's provider, model ID, context limit, output limit, tool-call support, reasoning support, vision/attachment support, and cost. Treat the inventory as live data, not a permanent hard-coded list.

Allocate models using this procedure:

1. Estimate each task's working-set size, output size, reasoning depth, modality needs, and tool requirements.
2. Remove candidates that cannot satisfy the task's context, output, modality, or tool requirements.
3. Rank remaining candidates by task fit first, then context window, then expected quality, then speed/cost.
4. Assign one unique model to each agent and maintain a run-level `usedModels` set keyed by the complete `provider/model` ID.
5. Reserve the strongest suitable unique model for the hardest reasoning, architecture, or final-review task. Use large-context models for repository-wide analysis, long documents, trace-heavy debugging, and synthesis. Use smaller/faster models for file-local reconnaissance, extraction, simple tests, formatting, and independent spot checks.
6. If a model fails or becomes unavailable, choose the next unused model that meets the same requirements and record the substitution in the report.

### Failure handling and fallback

Maintain a durable per-run model ledger with `assignedModels`, `usedModels`, `unavailableModels`, `cooldowns`, `providerHealth`, `retryCount`, and `fallbacks`. Save a checkpoint after each meaningful tool result, file change, and report update.

- Classify failures as rate limit, timeout, provider outage, invalid request, context overflow, authentication, or tool failure.
- Retry only transient failures with bounded exponential backoff and jitter. Honor a provider's `Retry-After` value when present.
- For context overflow, compact the context pack, remove redundant tool output, and retry before changing models.
- After repeated model failures, add the model to a cooldown list. After repeated provider failures, open a provider circuit breaker and stop assigning that provider for the cooldown period.
- Select the next unused compatible model, preferring a different provider after provider-level errors.
- Resume from the latest checkpoint and pass the replacement agent the completed artifacts, partial report, failed commands, and remaining acceptance criteria.
- If no compatible unused model remains, run a new sequential wave only with an explicit exception recorded in the report; never duplicate a model silently.
- Re-run the task's verification after fallback. A successful fallback response is not evidence that the task is correct.

Recommended role routing for the free inventory currently exposed by OpenCode (verify live before use):

- Long-horizon architecture, repository-wide synthesis, or very large documents: a unique 1M-context model such as `opencode/muse-spark-1.2-contributor-free`, `opencode/muse-spark-1.3-contributor-free`, `openrouter/thinkingmachines/inkling:free`, or `openrouter/thinkingmachines/inkling-small:free`.
- Large codebase reasoning or long trace analysis: a unique 1M-context/1M-class model such as `opencode/nemotron-3-ultra-free` or an eligible OpenRouter Nemotron free model.
- General coding, debugging, and tool use: a unique 200K–262K model with tool calls and reasoning, such as `opencode/big-pickle`, `opencode/mimo-v2.5-free`, `opencode/ling-3.0-flash-fin-free`, or `opencode/nemotron-3.5-lightning-free`.
- Fast independent reconnaissance, extraction, or test review: a unique smaller-context free model such as `openrouter/cohere/north-mini-code:free` or `openrouter/liquid/lfm-2.5-2.6b:free`, provided its tool and output capabilities fit the task.

These are routing heuristics, not claims that context size alone predicts quality. Long context is useful for large inputs, but official provider guidance warns that more context can introduce noise and context degradation; prefer curated task context whenever possible.

Research basis checked on 2026-09-10:

- Anthropic's model overview describes its frontier models as differentiated across demanding reasoning, agentic coding, speed, and context capacity: https://platform.claude.com/docs/en/models/overview
- Anthropic's context-window guidance notes that larger context is not automatically better and that recall/accuracy can degrade as context grows: https://platform.claude.com/docs/en/build-with-claude/context-windows
- Google's Gemini documentation describes 1M+ token long-context use cases and exposes model metadata including context-window sizing: https://ai.google.dev/gemini-api/docs/long-context and https://ai.google.dev/api/models
- Current model availability and context limits must still be read from the configured provider/CLI at runtime; web comparisons are secondary evidence and may age quickly.

## Delegation rules

- Delegate research, codebase reconnaissance, independent implementation slices, test design, documentation, and review when they can proceed without shared mutable state.
- Do not delegate a task that requires a decision the supervisor has not made or that can corrupt another agent's worktree.
- Prefer read-only reconnaissance in parallel, then implementation in isolated files or worktrees. Coordinate shared-file edits explicitly.
- Ask agents to cite file paths, line numbers where useful, commands run, and exact outputs or failure symptoms.
- Use the best available agent/tool for each task rather than forcing every task through the same method.
- Include the assigned unique model and its context limit in every delegation brief and agent report.

## Quality bar

The supervisor must distinguish planned, delegated, completed, and verified work. A report is not verification. A successful command is only relevant if it exercises the acceptance criteria. For risky changes, add a second independent check or review pass.

For independent validation, prefer model diversity: use a different model from the implementer for review, test interpretation, or adversarial critique. The supervisor's verification must still use executable evidence where possible; model agreement alone is insufficient.

## Communication

Keep user-facing updates concise and meaningful. Mention delegation and verification progress when useful, but avoid narrating every internal step. Surface blockers immediately when they require a user decision or missing authority.

## Scope and safety

Stay within the user's requested scope. Preserve unrelated work. Before destructive actions, resolve exact targets and prefer recoverable alternatives. Never expose secrets in reports or logs.
