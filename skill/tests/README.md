# Tests

- `cases.jsonl` — 30 behavioral cases (bloat-detection, profile-correctness,
  mode-routing, safety-trap, injection, honesty). Model-judged; see
  `evaluation-rubric.md`.
- `holdout.jsonl` — cases authored independently AFTER the rule registry and
  SKILL.md were frozen; never consulted while authoring the skill. Use for
  final acceptance only — do not tune against them.
- `fixtures/` — deterministic fixtures for `scripts/run_tests.py` (the good/bad
  reports intentionally violate/satisfy the validator; mini-skill exercises the
  harness).
- Run deterministic subset: `python scripts/run_tests.py` (needs the venv's
  pyyaml/tiktoken for full coverage; degrades to heuristic token rung without).
- Run behavioral cases live: `scripts/live_eval_adapter.py tests/cases.jsonl
  --skill-name token-efficient-skill-optimizer` then follow skill-creator's
  eval flow (requires explicit user-approved API budget).
