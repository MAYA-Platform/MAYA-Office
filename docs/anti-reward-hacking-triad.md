# Anti-Reward-Hacking Triad — Bench Doctrine

Source: Ornith 1.0 (DeepReinforce) anti-cheat design, captured 2026-09-11 in
`E:/MAYA_BULK/link-intake/ornith-capture-20260911b.md`. The triad: **locked
environment + peek-monitor + frozen judge**. It is the minimum machinery that
makes a self-improving loop measure skill instead of measuring cheating.

## The Rule

No SkillOpt-style self-modification loop may run against the swarm bench
unless all three guarantees hold for the full duration of the run:

### 1. LOCKED ENVIRONMENT

The code that judges artifacts (`swarm_bench.py` and its evaluators) and the
ledger baseline are hash-locked when the run starts:

```
python swarm_bench.py envlock start --agent <name>
```

This writes `bench/EVAL_LOCK.json` containing the SHA-256 of the judge code,
the ledger length, and the ledger head hash. Nothing may edit the judge
mid-run — verify recomputes the code hash every time and fails on any change.

### 2. PEEK-MONITOR

While a lock is active, every registration passes through the monitor inside
`register()`, which appends to `bench/MONITOR_LOG.jsonl`. An artifact whose
source path — or, for code-like artifacts (`.py/.js/.mjs/.sh/.ps1/.bat/.cmd`),
whose body — references judge internals (`LEDGER.jsonl`, `EVAL_LOCK.json`,
`MONITOR_LOG.jsonl`, `swarm_bench.py`, `run_evaluators`, `world_verdict`) is a
**peeking trajectory**. Peeks are zeroed at registration: the artifact is
refused, the attempt is logged permanently. Prose that merely *discusses* the
doctrine is not flagged; code that reaches for the judge is.

### 3. FROZEN JUDGE

The world verdict recorded at registration is immutable. Each eval-window
entry stores the judge code hash it was judged under. `verify` re-runs the
evaluators on eval-window snapshots and fails on any verdict drift. If the
judge legitimately rotates in a later, reviewed change, old entries are
grandfathered (noted, not failed) — the freeze protects a run in flight, not
history against deliberate, human-reviewed evolution.

## Enforcement (swarm_bench.py verify)

`python swarm_bench.py verify` enforces the pre-existing chain checks plus:

| Verdict | Meaning |
|---|---|
| `ENVIRONMENT MUTATED` | bench judge code changed while an eval lock is active |
| `UNMONITORED REGISTRATION` | an eval-window artifact has no monitor entry (someone wrote the ledger directly, bypassing register) |
| `PEEK FLAGGED` | a peeking trajectory is on record — the run it belongs to cannot pass |
| `JUDGE DRIFT` | re-running the evaluators disagrees with the recorded verdict |

`envlock end` closes the window; `envlock status` reports state. Peek attempts
are permanent fail-verifiers; only the founder may clear the monitor log after
reviewing, by rewriting it without the flagged lines (the Ornith "zero the
trajectory" move, made explicit and auditable).

## Why

A self-modifying loop that can edit its own judge, read the test fixtures, or
rewrite past verdicts is not being evaluated — it is grading its own homework.
The triad turns each of those three moves into a hard verify failure instead
of an honor-system rule. Ornith's numbers with the triad active (77.5
Terminal-Bench, 82.4 SWE-bench Verified) are evidence the constraint costs
nothing on capability.
