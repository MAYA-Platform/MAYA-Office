#!/usr/bin/env python3
"""
Swarm Bench — the persistent shared world for MAYA staff agents.
Pattern: MIT SwarmWorld (arXiv 2608.26081) — stigmergic technological evolution.

The four SwarmWorld mechanics, made real:
1. PERSISTENT WORLD: every staff work product registers as an artifact on a
   SHA-256 chain (same integrity pattern as Memory Lane). Artifacts persist
   in ./bench/ and are discovered by later agents.
2. WORLD DECIDES, AGENTS PROPOSE: registration runs deterministic evaluators
   (compile check, secret scan, file sanity). The stamp of PASS/FAIL comes
   from the world, never from the agent's claim. Cognition / consequence split.
3. STIGMERGY / EXECUTABLE INHERITANCE: artifacts carry parent artifact IDs.
   Later agents observe the ledger (observe/agent) and fork/build-on prior
   work through parent links. Most reuse should start through observation.
4. EMERGENCE TALLY: every action is logged per-agent; over time the ledger
   shows what each agent actually does vs their assigned role.

CLI:
  python swarm_bench.py register --agent forge --type script --title "X" --path P [--parents id1,id2] [--notes "n"]
  python swarm_bench.py register --agent nova --type doctrine --title "Y" --text "inline body"
  python swarm_bench.py observe --agent shadow            # what an agent sees of the world
  python swarm_bench.py status                            # founder ecology view
  python swarm_bench.py tally                             # emergence tally (agent behavior vs role)
  python swarm_bench.py verify                            # recompute chain integrity

State: ./bench/
  LEDGER.jsonl   append-only artifact ledger (chain-linked)
  artifacts/     copied artifact bodies (safe snapshot)
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

BENCH_ROOT = "./bench"
LEDGER_PATH = os.path.join(BENCH_ROOT, "LEDGER.jsonl")
ARTIFACT_DIR = os.path.join(BENCH_ROOT, "artifacts")

# Roles from the staff roster (assigned role = what the soul says).
# Emergence tally compares observed artifact behavior against these.
ASSIGNED_ROLES = {
    "shadow": "strategy", "chief": "operations", "nova": "design",
    "herald": "messaging", "sagan": "research", "echo": "research",
    "raven": "market", "flint": "discovery", "darwin": "discovery",
    "rust": "maintenance", "plumb": "maintenance", "argus": "watch",
    "vantage": "watch", "scribe": "memory", "quill": "memory",
    "alembic": "memory", "forge": "building", "anchor": "building",
    "dewey": "building", "sage": "security", "shepherd": "delivery",
    "prism": "delivery", "cipher": "infrastructure", "gatekeeper": "security",
    "kai": "gaming", "zen": "gaming", "specter": "security",
    "hermes": "orchestration", "josh": "founder",
}

MAX_BODY_BYTES = 512 * 1024  # 512KB artifact snapshot cap


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tail_entry():
    """Last ledger entry or None."""
    if not os.path.exists(LEDGER_PATH):
        return None
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def read_ledger():
    if not os.path.exists(LEDGER_PATH):
        return []
    out = []
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# THE WORLD DECIDES: deterministic evaluators. No LLM. No agent claims.
# ---------------------------------------------------------------------------

def eval_python(path):
    """Compile check. Returns (verdict, detail)."""
    try:
        r = subprocess.run([sys.executable, "-m", "py_compile", path],
                           capture_output=True, timeout=30)
        return ("PASS" if r.returncode == 0 else "FAIL",
                "py_compile ok" if r.returncode == 0 else r.stderr.decode()[-300:])
    except Exception as e:
        return ("UNVERIFIABLE", str(e)[:200])


def eval_node(path):
    r = subprocess.run(["node", "--check", path], capture_output=True, timeout=30)
    return ("PASS" if r.returncode == 0 else "FAIL",
            "node --check ok" if r.returncode == 0 else r.stderr.decode()[-300:])


def eval_secret_scan(path):
    """Cheap secret tell scan (part of the world's physics, not a full audit)."""
    tells = re.compile(
        r"(sk-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}"
        r"|mg_[A-Za-z0-9]{10,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"|(api[_-]?key|password|secret)\s*[:=]\s*['\"][^'\"]{12,})", re.I)
    try:
        body = open(path, encoding="utf-8", errors="replace").read()
        m = tells.search(body)
        if m:
            return ("FAIL", f"secret-like token detected (pattern: {m.group(0)[:12]}...)")
        return ("PASS", "no secret tells")
    except Exception as e:
        return ("UNVERIFIABLE", str(e)[:200])


def eval_text(path):
    try:
        body = open(path, encoding="utf-8", errors="replace").read()
        if len(body.strip()) < 20:
            return ("FAIL", "artifact body under 20 chars")
        return ("PASS", f"{len(body)} chars")
    except Exception as e:
        return ("UNVERIFIABLE", str(e)[:200])


EVALUATORS = {
    (".py",): [eval_python, eval_secret_scan],
    (".js", ".mjs"): [eval_node, eval_secret_scan],
    (".md", ".txt", ".json", ".yaml", ".yml", ".html"): [eval_secret_scan, eval_text],
}


def run_evaluators(path):
    """The simulator. Verdicts come from here, nowhere else."""
    ext = os.path.splitext(path)[1].lower()
    results = []
    matched = False
    for exts, evals in EVALUATORS.items():
        if ext in exts:
            matched = True
            for fn in evals:
                verdict, detail = fn(path)
                results.append({"eval": fn.__name__, "verdict": verdict, "detail": detail})
    if not matched:
        verdict, detail = eval_text(path)
        results.append({"eval": "eval_text", "verdict": verdict, "detail": detail})
    worst = "PASS"
    for r in results:
        if r["verdict"] == "FAIL":
            worst = "FAIL"
            break
        if r["verdict"] == "UNVERIFIABLE":
            worst = "UNVERIFIABLE"
    return worst, results


# ---------------------------------------------------------------------------
# Register: put an artifact into the world
# ---------------------------------------------------------------------------

def register(agent, atype, title, path=None, text=None, parents=None, notes=""):
    agent = agent.lower().strip()
    parents = parents or []
    ledger = read_ledger()
    known_ids = {a["artifact_id"] for a in ledger}
    for p in parents:
        if p not in known_ids:
            print(f"WORLD SAYS NO: parent artifact {p} does not exist in the ledger.")
            sys.exit(2)

    # Snapshot the body into the world (persistence beyond the original path)
    if path:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            print(f"WORLD SAYS NO: artifact path {path} does not exist.")
            sys.exit(2)
        if os.path.getsize(path) > MAX_BODY_BYTES:
            print(f"WORLD SAYS NO: artifact over {MAX_BODY_BYTES // 1024}KB cap.")
            sys.exit(2)
        body_bytes = open(path, "rb").read()
        ext = os.path.splitext(path)[1] or ".bin"
    elif text is not None:
        body_bytes = text.encode("utf-8")
        ext = ".md"
    else:
        print("Provide --path or --text.")
        sys.exit(2)

    # Allocate id + chain link
    art_id = f"art_{len(ledger) + 1:06d}"
    prev = tail_entry()
    ts = now_iso()

    # Run the world's evaluators BEFORE the artifact exists in the ledger.
    tmp_path = path if path else os.path.join(ARTIFACT_DIR, f"_tmp_{art_id}{ext}")
    if not path:
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(body_bytes)
    verdict, evals = run_evaluators(tmp_path)
    if not path:
        os.remove(tmp_path)

    # Store snapshot
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    snap_name = f"{art_id}_{re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:40]}{ext}"
    snap_path = os.path.join(ARTIFACT_DIR, snap_name)
    with open(snap_path, "wb") as f:
        f.write(body_bytes)

    body_text = body_bytes.decode("utf-8", errors="replace")
    entry = {
        "artifact_id": art_id,
        "title": title,
        "agent": agent,
        "type": atype,
        "ts": ts,
        "source_path": path or None,
        "snapshot": snap_name,
        # Hash the RAW BYTES on disk (not decoded text) so verification matches
        # the snapshot byte-for-byte regardless of file encoding.
        "sha256": hashlib.sha256(body_bytes).hexdigest(),
        "parents": parents,
        "notes": notes[:500],
        "world_verdict": verdict,
        "evals": evals,
        "prev_sha256": prev["sha256"] if prev else None,
    }

    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    icon = {"PASS": "OK", "FAIL": "XX", "UNVERIFIABLE": "??"}[verdict]
    print(f"[{icon}] {art_id} registered by {agent}: {title}")
    print(f"    verdict: {verdict} ({', '.join(e['eval'] + '=' + e['verdict'] for e in evals)})")
    if parents:
        print(f"    inherits: {', '.join(parents)}")
    print(f"    snapshot: {snap_path}")
    return entry


# ---------------------------------------------------------------------------
# Observe: what an agent sees of the shared world (stigmergy read path)
# ---------------------------------------------------------------------------

def observe(agent):
    agent = agent.lower().strip()
    ledger = read_ledger()
    if not ledger:
        print("The world is empty. Nothing has been built yet.")
        return
    passed = [a for a in ledger if a["world_verdict"] == "PASS"]
    print(f"WORLD STATE as seen by {agent} ({len(ledger)} artifacts, {len(passed)} world-verified)\n")
    for a in ledger[-15:]:
        marker = {"PASS": "[ok]", "FAIL": "[XX]", "UNVERIFIABLE": "[??]"}[a["world_verdict"]]
        lineage = f" <- {','.join(a['parents'])}" if a["parents"] else ""
        print(f"  {marker} {a['artifact_id']}  {a['type']:<9} {a['agent']:<10} {a['title'][:44]}{lineage}")
    print("\nReuse rules: fork/build-on PASS artifacts via --parents. FAIL artifacts are walls, not doors.")


# ---------------------------------------------------------------------------
# Tally: emergence measurement — observed behavior vs assigned role
# ---------------------------------------------------------------------------

def tally():
    ledger = read_ledger()
    if not ledger:
        print("No behavior to tally yet.")
        return
    by_agent = {}
    for a in ledger:
        by_agent.setdefault(a["agent"], {"types": {}, "builds": 0, "forks": 0, "fails": 0})
        d = by_agent[a["agent"]]
        d["types"][a["type"]] = d["types"].get(a["type"], 0) + 1
        d["builds"] += 1
        d["forks"] += len(a["parents"])
        if a["world_verdict"] == "FAIL":
            d["fails"] += 1

    print(f"EMERGENCE TALLY — {len(ledger)} artifacts by {len(by_agent)} agents\n")
    print(f"{'agent':<12} {'assigned':<15} {'builds':>6} {'forks':>6} {'fails':>6}  artifact types")
    drift = []
    for agent, d in sorted(by_agent.items(), key=lambda kv: -kv[1]["builds"]):
        assigned = ASSIGNED_ROLES.get(agent, "unknown")
        top_type = max(d["types"], key=d["types"].get)
        drift.append((agent, assigned, top_type))
        print(f"{agent:<12} {assigned:<15} {d['builds']:>6} {d['forks']:>6} {d['fails']:>6}  {dict(d['types'])}")
    print("\nROLE DRIFT (assigned vs observed top artifact type):")
    for agent, assigned, top in drift:
        marker = "  (aligned)" if assigned in (top, "orchestration", "founder", "unknown") else "  <-- DRIFT"
        print(f"  {agent:<12} {assigned} vs {top}{marker}")


# ---------------------------------------------------------------------------
# Verify: recompute the chain — the world checks itself
# ---------------------------------------------------------------------------

def verify():
    ledger = read_ledger()
    prev_sha = None
    ok = True
    for a in ledger:
        # chain link
        if a.get("prev_sha256") != prev_sha:
            print(f"CHAIN BREAK at {a['artifact_id']}: prev_sha mismatch")
            ok = False
        # snapshot integrity (raw bytes — matches registration hashing)
        snap = os.path.join(ARTIFACT_DIR, a["snapshot"])
        if os.path.exists(snap):
            raw = open(snap, "rb").read()
            if hashlib.sha256(raw).hexdigest() != a["sha256"]:
                print(f"SNAPSHOT TAMPER at {a['artifact_id']}")
                ok = False
        else:
            print(f"SNAPSHOT MISSING at {a['artifact_id']}")
            ok = False
        prev_sha = a["sha256"]
    print(f"chain verdict: {'INTACT' if ok else 'BROKEN'} ({len(ledger)} artifacts)")
    return ok


def main():
    p = argparse.ArgumentParser(description="Swarm Bench — the staff shared world")
    sub = p.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register")
    reg.add_argument("--agent", required=True)
    reg.add_argument("--type", required=True, choices=["script", "doctrine", "report", "tool", "fix", "analysis"])
    reg.add_argument("--title", required=True)
    reg.add_argument("--path")
    reg.add_argument("--text")
    reg.add_argument("--parents", help="comma-separated parent artifact ids")
    reg.add_argument("--notes", default="")

    obs = sub.add_parser("observe")
    obs.add_argument("--agent", required=True)

    sub.add_parser("status")
    sub.add_parser("tally")
    sub.add_parser("verify")

    args = p.parse_args()
    os.makedirs(BENCH_ROOT, exist_ok=True)
    if args.cmd == "register":
        parents = [x.strip() for x in args.parents.split(",") if x.strip()] if args.parents else []
        register(args.agent, args.type, args.title, args.path, args.text, parents, args.notes)
    elif args.cmd == "observe":
        observe(args.agent)
    elif args.cmd == "status":
        ledger = read_ledger()
        print(f"swarm bench: {len(ledger)} artifacts, {len([a for a in ledger if a['world_verdict']=='PASS'])} world-verified")
        observe("founder")
    elif args.cmd == "tally":
        tally()
    elif args.cmd == "verify":
        sys.exit(0 if verify() else 1)


if __name__ == "__main__":
    main()
