#!/usr/bin/env python3
"""
Swarm Bench — Initiative Scanner (the organic-work engine).

Staff find their own work. This module scans the founder's real environment
(repos, MAYA backend/frontend, notes, duplicates) for house-cleaning opportunities,
assigns each to the staff member whose soul fits it, and files an INITIATIVE
into the bench ledger as a 'proposal' artifact. Staff then do the ANALYSIS and
PREP the work — but nothing destructive executes without the founder's approval via
the existing approval seam / Founder Review Queue.

The SwarmWorld loop this closes:
  1. Scanner finds candidate work in the environment (the world's signals).
  2. Initiative registered on the bench (persistent, lineage-linked).
  3. Assigned staff pick it up on next sweep (observation-first).
  4. Staff produce analysis/prep artifacts (children of the initiative).
  5. Approval-gated execution: only the founder flips proposals into actions.

Safe by construction: the scanner is READ-ONLY. It never moves, edits, or
deletes anything — it only FINDS and FILES. All execution stays behind approval.

CLI:
  python swarm_initiatives.py scan                  # find new opportunities
  python swarm_initiatives.py list                  # show open initiatives
  python swarm_initiatives.py assign                # (re)assign to fitting staff
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

BENCH = "./bench"
LEDGER = os.path.join(BENCH, "LEDGER.jsonl")
BENCH_PY = r"./scripts/swarm_bench.py"
STATE = os.path.join(BENCH, "initiative_state.json")

SCAN_TARGETS = [
    # (label, root, what to look for, assigned-staff, initiative-type)
    ("MAYA backend", "./2ndnatureai-maya-beta", "code", "forge", "cleanup"),
    ("MAYA frontend", "./2ndnatureai-maya-beta/maya-agent", "code", "nova", "cleanup"),
    ("Hermes scripts", "./scripts", "code", "plumb", "cleanup"),
    ("Memory Lane repo", "./memory-lane", "code", "forge", "cleanup"),
    ("Founder notes", "./founder-files", "notes", "scribe", "organize"),
    ("Repo shelves", "./repo-shelves", "repo", "flint", "organize"),
]

STAFF_BRIEF = {
    "forge": "implementation and code cleanup",
    "nova": "frontend polish and UI consistency",
    "plumb": "maintenance, dead code, hygiene",
    "scribe": "notes organization, dedup, linking",
    "flint": "repo triage and discovery",
}

MAX_FINDS_PER_SCAN = 6
MAX_ITEM_KB = 512


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"seen": {}, "initiatives": {}}


def save_state(state):
    os.makedirs(BENCH, exist_ok=True)
    json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)


def bench_register(agent, itype, title, text, parents=None, notes=""):
    # bench only accepts these types; map initiative types onto them
    type_map = {"cleanup": "fix", "organize": "report", "analysis": "analysis"}
    bench_type = type_map.get(itype, "analysis")
    r = subprocess.run([sys.executable, BENCH_PY, "register",
                        "--agent", agent, "--type", bench_type, "--title", title,
                        "--text", text[:4000], "--notes", notes],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout or ""
    m = re.search(r"art_(\d{6})", out)
    return (m.group(0) if m else None), out


# ---------------------------------------------------------------------------
# READ-ONLY scanners: each returns a list of {id, title, body, staff, type}
# ---------------------------------------------------------------------------

def scan_dead_code(root, state):
    """TODO/FIXME/HACK markers = known incomplete work (read-only)."""
    finds = []
    if not os.path.isdir(root):
        return finds
    try:
        r = subprocess.run(["git", "-C", root, "grep", "-l", "-E",
                            "TODO|FIXME|HACK", "--", "*.js", "*.py"],
                           capture_output=True, text=True, timeout=30)
        files = [f for f in (r.stdout or "").splitlines() if f.strip()]
    except Exception:
        files = []
    for f in files[:3]:
        rel = os.path.relpath(f, root) if os.path.isabs(f) else f
        fid = f"todo:{rel}"
        if state["seen"].get(fid):
            continue
        finds.append({
            "id": fid,
            "title": f"Incomplete-work markers in {rel}",
            "body": f"File {rel} contains TODO/FIXME/HACK markers — known unfinished work. "
                    f"Analyze each marker, classify (real gap vs stale note), and prep a "
                    f"cleanup proposal. You may implement safe fixes autonomously (comment removal, doc updates, dead-flag cleanup). Deletion of files or mass changes routes to the Team Review Board; true founder-required scope per board policy (delete/destructive/secrets/financial) only.",
            "staff": "forge", "type": "cleanup",
        })
    return finds


def scan_duplicate_notes(root, state):
    """Same-name notes in the vault = organization targets (read-only)."""
    finds = []
    names = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "archive", "_Archived")]
        for fn in filenames:
            if fn.endswith(".md") and not fn.startswith("_"):
                names.setdefault(fn, []).append(os.path.join(dirpath, fn))
        if len(names) > 3000:
            break
    dups = {n: paths for n, paths in names.items() if len(paths) > 1}
    if dups:
        fid = "dupnotes:" + str(hash(tuple(sorted(dups))) & 0xFFFF)
        if not state["seen"].get(fid):
            sample = list(dups.items())[:5]
            body = "Duplicate note names found across the vault:\n" + "\n".join(
                f"- {n} x{len(ps)}: " + ", ".join(os.path.relpath(p, root) for p in ps[:3])
                for n, ps in sample)
            finds.append({
                "id": fid,
                "title": f"{len(dups)} duplicate note names need organizing",
                "body": body + "\n\nAnalyze: which copies are canonical, which are stale? "
                              "Autonomous: merge/rename/archive-to-E: with manifests (reversible operations are within your lane). Actual DELETION of any note routes to the Team Review Board founder-required lane.",
                "staff": "scribe", "type": "organize",
            })
    return finds


def scan_oversized_files(root, state):
    """Files that don't belong in a lean repo (read-only)."""
    finds = []
    if not os.path.isdir(root):
        return finds
    heavy = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", ".next", "__pycache__")]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > 5 * 1024 * 1024:
                    heavy.append((p, os.path.getsize(p)))
            except OSError:
                pass
        if len(heavy) > 20:
            break
    heavy = heavy[:10]
    if heavy:
        fid = "heavy:" + str(hash(tuple(h[0] for h in heavy)) & 0xFFFF)
        if not state["seen"].get(fid):
            body = "Large files in the repo (5MB+):\n" + "\n".join(
                f"- {os.path.relpath(p, root)}: {sz // (1024*1024)}MB" for p, sz in heavy)
            finds.append({
                "id": fid,
                "title": f"{len(heavy)} oversized files worth archiving",
                "body": body + "\n\nAnalyze each: needed at runtime, or archive-to-E: candidate? "
                              "Autonomous: archive to E:/MAYA_BULK with manifests (reversible). Deletion routes to the Team Review Board founder-required lane.",
                "staff": "plumb", "type": "cleanup",
            })
    return finds


def scan_reports_freshness(root, state):
    """Scout reports gone stale = discovery work (read-only)."""
    finds = []
    rep_dir = os.path.join(root, "docs", "source-freshness")
    if not os.path.isdir(rep_dir):
        return finds
    import time
    now = time.time()
    stale = []
    for fn in os.listdir(rep_dir):
        p = os.path.join(rep_dir, fn)
        if fn.endswith(".md") and now - os.path.getmtime(p) > 7 * 86400:
            stale.append(fn)
    if stale:
        fid = "stale:" + str(hash(tuple(stale)) & 0xFFFF)
        if not state["seen"].get(fid):
            finds.append({
                "id": fid,
                "title": f"{len(stale)} scout reports older than 7 days",
                "body": "Stale reports: " + ", ".join(stale[:5]) +
                        "\n\nRun fresh scans and produce updated reports. This is read-only "
                        "research work — write new reports, change nothing existing.",
                "staff": "flint", "type": "analysis",
            })
    return finds


# ---------------------------------------------------------------------------
# Main scan: find, dedupe, register initiatives on the bench
# ---------------------------------------------------------------------------

def scan():
    state = load_state()
    registered = 0
    all_finds = []
    for label, root, kind, staff, itype in SCAN_TARGETS:
        if kind == "code":
            all_finds += scan_dead_code(root, state)
            all_finds += scan_oversized_files(root, state)
        elif kind == "notes":
            all_finds += scan_duplicate_notes(root, state)
        elif kind == "repo":
            all_finds += scan_reports_freshness(root, state)

    for find in all_finds[:MAX_FINDS_PER_SCAN]:
        state["seen"][find["id"]] = now_iso()
        art_id, out = bench_register(
            find["staff"], find["type"],
            f"INITIATIVE: {find['title']}",
            find["body"],
            notes=f"organic find by scanner, assigned {find['staff']} ({STAFF_BRIEF.get(find['staff'], 'work')}) — autonomous per Team Review Board policy: reversible work advances freely, delete/mass-change/destructive escalates")
        if art_id:
            state["initiatives"][art_id] = {"find_id": find["id"], "assigned": find["staff"], "ts": now_iso()}
            registered += 1
            print(f"  initiative {art_id} -> {find['staff']}: {find['title']}")
    save_state(state)
    print(f"scan complete: {registered} new initiative(s), {len(all_finds)} total finds")
    return registered


def list_initiatives():
    ledger = read_ledger()
    inits = [a for a in ledger if a["title"].startswith("INITIATIVE:")]
    if not inits:
        print("No open initiatives. Run: python swarm_initiatives.py scan")
        return
    print(f"OPEN INITIATIVES ({len(inits)}):\n")
    for a in inits:
        status = {"PASS": "[ok]", "FAIL": "[XX]", "UNVERIFIABLE": "[??]"}[a["world_verdict"]]
        print(f"  {status} {a['artifact_id']}  {a['agent']:<10} {a['title'][12:60]}")
    # children (staff responses to initiatives)
    kids = [a for a in ledger if a.get("parents")]
    child_map = {}
    for k in kids:
        for p in k["parents"]:
            child_map.setdefault(p, []).append(k)
    print("\nSTAFF RESPONSES:")
    for a in inits:
        resp = child_map.get(a["artifact_id"], [])
        if resp:
            for r in resp:
                print(f"  {a['artifact_id']} -> {r['artifact_id']} by {r['agent']}: {r['title'][:50]}")
        else:
            print(f"  {a['artifact_id']} -> (awaiting staff pickup)")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        scan()
    elif cmd == "list":
        list_initiatives()
    else:
        print("usage: swarm_initiatives.py [scan|list]")


if __name__ == "__main__":
    main()
