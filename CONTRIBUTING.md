# Contributing

Contributions should preserve the supervisor contract:

1. Never silently reuse a model within an active delegation wave.
2. Keep raw reports and checkpoints recoverable.
3. Treat external agent output as untrusted evidence.
4. Add verification guidance for new behavior.
5. Keep integrations optional and runtime-neutral.

Before opening a pull request, validate the plugin manifest and inspect the resulting diff:

```powershell
python <codex-skills>\\.system\\plugin-creator\\scripts\\validate_plugin.py .
git diff --check
```

For behavior changes, include a small reproducible scenario covering success, fallback, and verification.
