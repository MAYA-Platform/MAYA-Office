#!/usr/bin/env python3
"""
Swarm Efficiency Rating System — tracks whether the autonomous office actually works.

the founder's investment question: does the swarm produce real value per dollar, or is it
expensive theater? This system measures it honestly, from three evidence sources:

  1. THE BENCH (./bench/LEDGER.jsonl)
     - artifacts produced, world-verified pass rate, inheritance depth (stigmergy),
       initiative pickup rate (do staff act without orders?)
  2. THE COST SIDE
     - GCP VM hours (e2-small ~$0.0416/hr actual) + GLM token spend (Merge credits)
     - cost per artifact, cost per world-verified artifact
  3. THE VALUE SIDE (ground truth, not vibes)
     - were staff outputs actually USED? (proposals Hermes applied, analyses that
       changed a decision, cleanups executed) — tracked via manual + bridge tagging

EFFICIENCY SCORE (0-100), four weighted components (the founder-style polarity-aware):
  OUTPUT VELOCITY   (25%) — verified artifacts/day vs baseline target
  AUTONOMY RATE     (25%) — % of artifacts made without founder/Hermes direct order
  QUALITY RATE      (25%) — world-verified PASS %, minus blocked walls
  INHERITANCE DEPTH (25%) — % of artifacts built on other artifacts (real stigmergy)

VERDICT BANDS:
  80+  INVEST     — proven system, put money into the cloud lane
  60-79 PROMISING — keep running, fix the weak component
  40-59 MIXED     — narrow scope to what works
  <40  THEATER    — shut it down and rethink

Output: ./bench/efficiency/efficiency-report-<date>.md + .json
Cron: daily 7am. Also included in the Monday founder-meeting email data.

CLI: python swarm_efficiency.py report | json
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path("./bench")
LEDGER = BENCH / "LEDGER.jsonl"
OUT_DIR = BENCH / "efficiency"
STATE = BENCH / "efficiency" / "state.json"

# Cost constants (documented assumptions, founder-visible)
VM_USD_PER_HOUR = 0.0416          # e2-small us-central1 on-demand
EXPERIMENT_START = "2026-09-06"   # first VM day
GLM_USD_PER_1M_TOKENS = 0.30      # ~upper bound; Merge pricing varies
GLM_TOKENS_PER_TURN_EST = 6000    # prompt+completion for a staff turn

# Baseline targets (what "working as intended" means)
TARGET_ARTIFACTS_PER_DAY = 3.0     # realistic for 10 staff on 6h cycles
TARGET_AUTONOMY_PCT = 80.0         # most work self-initiated
TARGET_PASS_PCT = 85.0             # world verifies most work
TARGET_INHERITANCE_PCT = 30.0      # ~1/3 of artifacts build on others


def _now():
    return datetime.now(timezone.utc)


def _days_since_start():
    d = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
    return max((_now().replace(tzinfo=None) - d).days, 1)


def read_ledger():
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]


def ledger_stats():
    led = read_ledger()
    total = len(led)
    passed = [a for a in led if a.get("world_verdict") == "PASS"]
    failed = [a for a in led if a.get("world_verdict") == "FAIL"]
    initiatives = [a for a in led if (a.get("title") or "").startswith("INITIATIVE:")]
    inheritors = [a for a in led if a.get("parents")]
    staff_artifacts = [a for a in led if a.get("agent") not in ("hermes", "josh", None)]
    by_agent = {}
    for a in led:
        by_agent.setdefault(a.get("agent", "?"), []).append(a)

    # initiative pickup: initiatives that have at least one child artifact
    child_parents = set()
    for a in led:
        for p in a.get("parents", []):
            child_parents.add(p)
    picked_up = [i for i in initiatives if i["artifact_id"] in child_parents]

    # autonomous share: artifacts NOT registered by hermes/josh directly
    autonomy = (len(staff_artifacts) / total * 100) if total else 0.0

    return {
        "total": total,
        "passed": len(passed),
        "failed": len(failed),
        "pass_pct": round(len(passed) / total * 100, 1) if total else 0.0,
        "initiatives": len(initiatives),
        "initiatives_picked_up": len(picked_up),
        "pickup_pct": round(len(picked_up) / len(initiatives) * 100, 1) if initiatives else 0.0,
        "inheritors": len(inheritors),
        "inheritance_pct": round(len(inheritors) / total * 100, 1) if total else 0.0,
        "staff_artifacts": len(staff_artifacts),
        "autonomy_pct": round(autonomy, 1),
        "by_agent": {k: len(v) for k, v in sorted(by_agent.items(), key=lambda kv: -len(kv[1]))},
        "days": _days_since_start(),
        "artifacts_per_day": round(total / _days_since_start(), 2),
    }


def cost_stats():
    hours_per_day = 24.0
    days = _days_since_start()
    vm_usd = VM_USD_PER_HOUR * hours_per_day * days
    # GLM estimate: staff turns logged via chat runtime receipts are hard to count
    # exactly; estimate from artifacts (each artifact ~1 turn + sweeps)
    led = read_ledger()
    est_turns = max(len(led) * 2, 10)  # ~2 model turns per artifact (work + review)
    glm_usd = est_turns * GLM_TOKENS_PER_TURN_EST / 1_000_000 * GLM_USD_PER_1M_TOKENS
    total_usd = vm_usd + glm_usd
    return {
        "days": days,
        "vm_usd": round(vm_usd, 2),
        "glm_est_usd": round(glm_usd, 4),
        "total_usd": round(total_usd, 2),
        "usd_per_artifact": round(total_usd / max(len(led), 1), 4),
        "est_turns": est_turns,
    }


def _score(value, target, higher_is_better=True):
    """0-100 component score. 100 at/above target, scales down linearly, floor 0."""
    if target <= 0:
        return 0
    ratio = value / target
    if higher_is_better:
        return round(min(ratio * 100, 100))
    return round(min((1 / max(ratio, 0.01)) * 100, 100))


def efficiency_score(stats, cost):
    velocity = _score(stats["artifacts_per_day"], TARGET_ARTIFACTS_PER_DAY)
    autonomy = _score(stats["autonomy_pct"], TARGET_AUTONOMY_PCT)
    quality = _score(stats["pass_pct"], TARGET_PASS_PCT)
    inheritance = _score(stats["inheritance_pct"], TARGET_INHERITANCE_PCT)
    score = round(velocity * 0.25 + autonomy * 0.25 + quality * 0.25 + inheritance * 0.25)
    # MATURITY DAMPENER: a fresh experiment can't score INVEST on day one.
    # Full score unlocks after 14 days of running; ramps 40%->100% over days 1-14.
    dampener = min(0.4 + 0.6 * (stats['days'] / 14), 1.0)
    score = round(score * dampener)
    if score >= 80:
        verdict = "INVEST — proven system, fund the cloud lane"
    elif score >= 60:
        verdict = "PROMISING — keep running, fix the weak component"
    elif score >= 40:
        verdict = "MIXED — narrow scope to what demonstrably works"
    else:
        verdict = "THEATER — shut down and rethink"
    return {
        "components": {"output_velocity": velocity, "autonomy_rate": autonomy,
                       "quality_rate": quality, "inheritance_depth": inheritance},
        "score": score, "verdict": verdict,
    }


def report():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = ledger_stats()
    cost = cost_stats()
    eff = efficiency_score(stats, cost)

    report_md = f"""---
artifact_type: efficiency_report
generated: {_now().isoformat(timespec='seconds')}
---

# Swarm Efficiency Report — Day {stats['days']}

## EFFICIENCY SCORE: {eff['score']}/100 — {eff['verdict']}

| Component | Weight | Score | Actual | Target |
|---|---|---|---|---|
| Output velocity | 25% | {eff['components']['output_velocity']} | {stats['artifacts_per_day']}/day | {TARGET_ARTIFACTS_PER_DAY}/day |
| Autonomy rate | 25% | {eff['components']['autonomy_rate']} | {stats['autonomy_pct']}% | {TARGET_AUTONOMY_PCT}% |
| Quality rate | 25% | {eff['components']['quality_rate']} | {stats['pass_pct']}% PASS | {TARGET_PASS_PCT}% |
| Inheritance depth | 25% | {eff['components']['inheritance_depth']} | {stats['inheritance_pct']}% built-on-others | {TARGET_INHERITANCE_PCT}% |

## Output

- **{stats['total']} artifacts** total, {stats['passed']} world-verified PASS, {stats['failed']} FAIL (blocked walls)
- **Initiatives:** {stats['initiatives']} filed, {stats['initiatives_picked_up']} picked up by staff ({stats['pickup_pct']}% pickup rate)
- **Inheritance:** {stats['inheritors']} artifacts built on other artifacts — real stigmergy signal

## Per-agent contribution

| Agent | Artifacts |
|---|---|
""" + "\n".join(f"| {a} | {n} |" for a, n in stats["by_agent"].items()) + f"""

## Cost (actuals + documented estimates)

- VM: {cost['days']} days x 24h x ${VM_USD_PER_HOUR}/hr = **${cost['vm_usd']}**
- GLM (est. {cost['est_turns']} turns x {GLM_TOKENS_PER_TURN_EST} tokens): **${cost['glm_est_usd']}**
- **Total: ${cost['total_usd']}** — ${cost['usd_per_artifact']} per artifact

## The investment question

At {stats['artifacts_per_day']}/day and ${cost['usd_per_artifact']}/artifact: the system earns
INVEST status when the score holds 80+ for two consecutive weeks AND at least
half the artifacts demonstrably changed something real (fix applied, decision
informed, cleanup executed). Track that secondary metric manually in
./bench/efficiency/value-log.md — staff or Hermes log one line
per artifact that had a real-world effect.
"""

    rp = OUT_DIR / f"efficiency-report-{_now().strftime('%Y-%m-%d')}.md"
    rp.write_text(report_md, encoding="utf-8")
    (OUT_DIR / "efficiency-latest.json").write_text(
        json.dumps({"stats": stats, "cost": cost, "efficiency": eff}, indent=1),
        encoding="utf-8")
    print(f"report: {rp}")
    print(f"SCORE: {eff['score']}/100 — {eff['verdict']}")
    print(f"  velocity {eff['components']['output_velocity']} | autonomy {eff['components']['autonomy_rate']} | "
          f"quality {eff['components']['quality_rate']} | inheritance {eff['components']['inheritance_depth']}")
    print(f"  ${cost['total_usd']} total, ${cost['usd_per_artifact']}/artifact, {stats['artifacts_per_day']}/day")
    return eff


def value_log(note, artifact_id=None):
    """Log a real-world effect: staff/Hermes record when an artifact changed something."""
    f = OUT_DIR / "value-log.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(f"- **{_now().isoformat(timespec='seconds')}** {artifact_id or '—'}: {note}\n")
    print(f"logged: {note[:80]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "report":
        report()
    elif cmd == "value":
        value_log(sys.argv[2] if len(sys.argv) > 2 else "(no note)",
                  sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print("usage: swarm_efficiency.py [report|value <note> [artifact_id]]")
