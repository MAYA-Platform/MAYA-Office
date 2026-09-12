#!/usr/bin/env python3
"""Fleet Metrics Exporter - sanitized daily fleet stats for the public repo.

Reads the office's efficiency snapshot and bench ledger, writes a sanitized
JSON (+ JS twin for file:// viewing) to data/fleet-metrics.json. The README
badge and docs/fleet.html render it.

Paths are configurable via environment so the script carries no machine
identifiers:

  SWARM_BENCH_DIR   bench root (LEDGER.jsonl + efficiency/efficiency-latest.json)
  SWARM_OFFICE_REPO this repository checkout

Usage:
  python scripts/fleet_metrics_export.py [--no-push]

Sanitization (public-repo hygiene rules):
  - no founder identifiers, no machine paths, no internal vocabulary in any
    exported string
  - em-dashes stripped from public copy
  - artifact titles scrub-checked; a failing title is dropped for a generic label
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(os.environ.get("SWARM_BENCH_DIR", "./bench"))
LEDGER = BENCH / "LEDGER.jsonl"
LATEST = BENCH / "efficiency" / "efficiency-latest.json"
REPO = Path(os.environ.get("SWARM_OFFICE_REPO", "."))
OUT = REPO / "data" / "fleet-metrics.json"

# Identifier / machine-path tells that must never reach the public repo
SCRUB_TELLS = (
    "joshu", "josh", "c:\\", "e:\\", "/users/", "hermes-agent", "merge gateway",
    "2ndnature", "founder files", "appdata",
)


def scrub(text):
    """Return sanitized text or None if it carries an identifier tell."""
    t = (text or "").strip()
    low = t.lower()
    for tell in SCRUB_TELLS:
        if tell in low:
            return None
    return t.replace("\u2014", "-").replace("\u2013", "-")


# Internal plumbing ids (kanban task refs etc.) never belong in public copy
TASK_ID_RE = re.compile(r"\s*\(?task\s+t_[0-9a-f]{6,}\)?", re.IGNORECASE)


def read_ledger():
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]


def top_artifact(led):
    """Most recent PASS artifact from today (or the newest overall), scrub-checked."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    todays = [a for a in led if str(a.get("ts", "")).startswith(today)]
    pool = todays or led
    for a in reversed(pool):
        if a.get("world_verdict") != "PASS":
            continue
        title = scrub(a.get("title", ""))
        if title is None:
            continue
        title = TASK_ID_RE.sub("", title).strip(" -,")
        if not title:
            continue
        return {
            "title": title[:120],
            "agent": a.get("agent", "staff"),
            "type": a.get("type", "artifact"),
            "built_on": bool(a.get("parents")),
        }
    return None


def verdict_band(score):
    if score >= 80:
        return "INVEST"
    if score >= 60:
        return "PROMISING"
    if score >= 40:
        return "MIXED"
    return "THEATER"


def export():
    if not LATEST.exists():
        print("efficiency-latest.json missing; run swarm_efficiency.py report first")
        return 1
    data = json.loads(LATEST.read_text(encoding="utf-8"))
    stats, cost, eff = data["stats"], data["cost"], data["efficiency"]
    led = read_ledger()

    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "experiment_days": stats["days"],
        "artifacts_total": stats["total"],
        "verified_pass_pct": stats["pass_pct"],
        "artifacts_per_day": stats["artifacts_per_day"],
        "autonomy_pct": stats["autonomy_pct"],
        "inheritance_pct": stats["inheritance_pct"],
        "initiatives_filed": stats["initiatives"],
        "initiatives_picked_up": stats["initiatives_picked_up"],
        "efficiency_score": eff["score"],
        "verdict_band": verdict_band(eff["score"]),
        "cost_total_usd": cost["total_usd"],
        "cost_per_artifact_usd": cost["usd_per_artifact"],
        "by_agent": stats["by_agent"],
        "top_artifact": top_artifact(led),
    }

    # Final scrub pass over every string that leaves the building
    flat = json.dumps(payload)
    low = flat.lower()
    for tell in SCRUB_TELLS:
        if tell in low:
            print(f"SCRUB FAIL: payload contains '{tell}' - aborting export")
            return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    # JS twin for file:// viewing (fetch is CORS-blocked on file://; script tags are not)
    js = REPO / "data" / "fleet-metrics.js"
    js.write_text("var FLEET_METRICS = " + json.dumps(payload, indent=1) + ";\n",
                  encoding="utf-8")
    print(f"exported: {OUT}")
    print(f"  score {payload['efficiency_score']} ({payload['verdict_band']}), "
          f"{payload['artifacts_total']} artifacts, {payload['verified_pass_pct']}% pass")
    return 0


def push():
    """Commit + push the refreshed JSON so the README badge goes live."""
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True)
    if not r.stdout.strip():
        print("repo clean, nothing to push")
        return 0
    subprocess.run(["git", "add", "data/fleet-metrics.json", "data/fleet-metrics.js"],
                   cwd=REPO, check=True)
    msg = "fleet metrics: daily sanitized export"
    subprocess.run(["git", "commit", "-m", msg], cwd=REPO, capture_output=True, text=True)
    r = subprocess.run(["git", "push", "origin", "main"], cwd=REPO,
                       capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"push: {'OK' if ok else 'FAILED'} {r.stdout.strip()[:200]} {r.stderr.strip()[:200]}")
    return 0 if ok else 1


if __name__ == "__main__":
    rc = export()
    if rc == 0 and "--no-push" not in sys.argv:
        rc = push()
    sys.exit(rc)
