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

# Anti-reward-hacking triad (Ornith 1.0 doctrine, docs/anti-reward-hacking-triad.md):
# locked environment + peek-monitor + frozen judge. State files:
EVAL_LOCK_PATH = os.path.join(BENCH_ROOT, "EVAL_LOCK.json")
MONITOR_LOG_PATH = os.path.join(BENCH_ROOT, "MONITOR_LOG.jsonl")
SELF_PATH = os.path.abspath(__file__)

# Peek tells: judge internals an artifact must not reach for while an eval
# lock is active. Body scan applies to code-like artifacts only; prose that
# merely discusses the doctrine is not a peek.
PEEK_PATH_TELLS = ("LEDGER.jsonl", "EVAL_LOCK.json", "MONITOR_LOG.jsonl", "swarm_bench.py")
PEEK_BODY_TELLS = ("run_evaluators", "world_verdict", "EVAL_LOCK.json",
                   "MONITOR_LOG.jsonl", "LEDGER.jsonl", "swarm_bench.py")
CODE_EXTS = {".py", ".js", ".mjs", ".sh", ".ps1", ".bat", ".cmd"}

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
# ANTI-REWARD-HACKING TRIAD state: envlock + peek-monitor + frozen judge.
# See docs/anti-reward-hacking-triad.md. All deterministic, no LLM.
# ---------------------------------------------------------------------------

def judge_code_hash():
    """SHA-256 of the judge itself — the 'frozen judge' fingerprint."""
    return hashlib.sha256(open(SELF_PATH, "rb").read()).hexdigest()


def read_lock():
    if not os.path.exists(EVAL_LOCK_PATH):
        return None
    try:
        return json.load(open(EVAL_LOCK_PATH, encoding="utf-8"))
    except Exception:
        return {"corrupt": True}


def write_lock(lock):
    if lock is None:
        if os.path.exists(EVAL_LOCK_PATH):
            os.remove(EVAL_LOCK_PATH)
    else:
        os.makedirs(BENCH_ROOT, exist_ok=True)
        with open(EVAL_LOCK_PATH, "w", encoding="utf-8") as f:
            json.dump(lock, f, indent=2)


def ledger_baseline():
    ledger = read_ledger()
    return {"length": len(ledger),
            "head_sha256": ledger[-1]["sha256"] if ledger else None}


def monitor_log(keep_predicate=None):
    """Read (and optionally rewrite) the monitor log. Rewriting without
    flagged lines is the founder-only 'zero the trajectory' move."""
    if not os.path.exists(MONITOR_LOG_PATH):
        return []
    out = []
    with open(MONITOR_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    if keep_predicate is not None:
        kept = [e for e in out if keep_predicate(e)]
        with open(MONITOR_LOG_PATH, "w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e) + "\n")
    return out


def monitor_append(event):
    os.makedirs(BENCH_ROOT, exist_ok=True)
    with open(MONITOR_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def peek_scan(path, body_bytes, atype=None):
    """Return peek reason string if the artifact reaches for judge internals,
    else None. Path tells apply to every artifact; body tells apply to
    code-like artifacts — by extension or by declared artifact type (a
    --text script has no code extension but is still code). Prose that merely
    discusses the doctrine is not a peek."""
    p = path or ""
    for tell in PEEK_PATH_TELLS:
        if tell in p:
            return f"source path references judge internals: {tell}"
    ext = os.path.splitext(path or "")[1].lower()
    if ext in CODE_EXTS or (atype or "").lower() == "script":
        try:
            body = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            return "code artifact body undecodable under eval lock"
        for tell in PEEK_BODY_TELLS:
            if tell in body:
                return f"code body references judge internals: {tell}"
    return None


def envlock_cmd(action, agent):
    agent = (agent or "unknown").lower().strip()
    lock = read_lock()
    if action == "start":
        if lock and not lock.get("corrupt"):
            print(f"WORLD SAYS NO: eval lock already active since {lock['started_at']} "
                  f"by {lock['agent']}. Run 'envlock end' first.")
            return False
        lock = {
            "active": True,
            "agent": agent,
            "started_at": now_iso(),
            "judge_sha256": judge_code_hash(),
            "ledger_baseline": ledger_baseline(),
        }
        write_lock(lock)
        monitor_append({"event": "envlock_start", "agent": agent,
                        "ts": lock["started_at"], "judge_sha256": lock["judge_sha256"],
                        "ledger_baseline": lock["ledger_baseline"]})
        print(f"[LOCK] eval window open by {agent}: judge {lock['judge_sha256'][:16]}…, "
              f"ledger baseline {lock['ledger_baseline']['length']} artifacts")
        return True
    if action == "end":
        if not lock or lock.get("corrupt"):
            print("No active eval lock.")
            return False
        monitor_append({"event": "envlock_end", "agent": agent, "ts": now_iso(),
                        "lock_started_at": lock.get("started_at")})
        write_lock(None)
        print(f"[UNLOCK] eval window closed (opened {lock['started_at']} by {lock['agent']})")
        return True
    if action == "status":
        if not lock or lock.get("corrupt"):
            print("eval lock: none active")
            return True
        mutated = judge_code_hash() != lock.get("judge_sha256")
        print(f"eval lock: ACTIVE since {lock['started_at']} by {lock['agent']}")
        print(f"  judge: {lock.get('judge_sha256', '?')[:16]}… "
              f"({'MUTATED since start' if mutated else 'unchanged since start'})")
        print(f"  ledger baseline: {lock.get('ledger_baseline')}")
        return True
    print(f"Unknown envlock action: {action}")
    return False


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

    # ANTI-REWARD-HACKING TRIAD: peek-monitor. While an eval lock is active
    # every registration passes the monitor; peeking trajectories are zeroed
    # (refused + permanently logged), not silently scored.
    lock = read_lock()
    if lock and not lock.get("corrupt"):
        peek_reason = peek_scan(path, body_bytes, atype)
        monitor_append({
            "event": "register",
            "ts": ts,
            "agent": agent,
            "artifact_id": art_id,
            "title": title,
            "peek": peek_reason,
            "judge_sha256": judge_code_hash(),
        })
        if peek_reason:
            print(f"WORLD SAYS NO: peek-monitor flagged this trajectory — {peek_reason}")
            print(f"            (attempt logged permanently in MONITOR_LOG.jsonl; "
                  f"the run it belongs to cannot pass verify)")
            # Zero the trajectory: nothing enters the world.
            return None

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
        "eval_window": bool(lock and not lock.get("corrupt")),
        "judge_sha256": judge_code_hash() if (lock and not lock.get("corrupt")) else None,
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
    if lock and not lock.get("corrupt"):
        print(f"    eval-window: judged under frozen judge {lock['judge_sha256'][:16]}…")
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

    # TRIAD CHECK 1 — LOCKED ENVIRONMENT: the judge must be unchanged while
    # an eval lock is active.
    lock = read_lock()
    if lock and not lock.get("corrupt"):
        if judge_code_hash() != lock.get("judge_sha256"):
            print("ENVIRONMENT MUTATED: bench judge code changed while an eval "
                  "lock is active (locked at %s by %s)." %
                  (lock.get("started_at"), lock.get("agent")))
            ok = False
        base = lock.get("ledger_baseline") or {}
        cur = ledger_baseline()
        if cur["length"] < base.get("length", 0) or \
           (base.get("length", 0) > 0 and cur["head_sha256"] != base.get("head_sha256")):
            print("LEDGER BASELINE VIOLATION: ledger shrank or head changed "
                  "under an active eval lock (baseline %s vs current %s)." %
                  (base, cur))
            ok = False

    # TRIAD CHECK 2 — PEEK-MONITOR: every eval-window artifact must have a
    # monitor entry; any flagged peek fails the run.
    mon = monitor_log()
    mon_by_art = {}
    for e in mon:
        if e.get("event") == "register" and e.get("artifact_id"):
            mon_by_art.setdefault(e["artifact_id"], []).append(e)
    for a in ledger:
        if a.get("eval_window"):
            entries = mon_by_art.get(a["artifact_id"], [])
            if not entries:
                print("UNMONITORED REGISTRATION at %s: eval-window artifact has "
                      "no monitor entry (ledger written around register?)." % a["artifact_id"])
                ok = False
    peek_events = [e for e in mon if e.get("event") == "register" and e.get("peek")]
    if peek_events:
        print("PEEK FLAGGED: %d peeking trajectory(ies) on record — the run(s) "
              "they belong to cannot pass. Founder must review and zero them "
              "(rewrite MONITOR_LOG.jsonl without flagged lines)." % len(peek_events))
        for e in peek_events:
            print("  %s  %s  %s" % (e.get("ts"), e.get("agent"), e.get("peek")))
        ok = False

    # TRIAD CHECK 3 — FROZEN JUDGE: eval-window entries record the judge hash
    # they were judged under; re-running evaluators must reproduce verdicts.
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
        if a.get("eval_window"):
            if a.get("judge_sha256") != judge_code_hash():
                # Grandfathered: a later, reviewed judge rotation is legitimate.
                # A live eval lock makes this a hard failure instead (caught above).
                if not (lock and not lock.get("corrupt")):
                    print(f"JUDGE ROTATION (grandfathered) at {a['artifact_id']}: "
                          f"judged under {a.get('judge_sha256', '?')[:16]}…, current judge differs")
            # Re-run the world's evaluators on every snapshot — verdict
            # tampering in the ledger must not survive verify, regardless of
            # artifact type.
            if os.path.exists(snap):
                worst, results = run_evaluators(snap)
                recorded = a.get("world_verdict")
                if worst != recorded and not (worst == "UNVERIFIABLE" and recorded == "FAIL"):
                    print(f"JUDGE DRIFT at {a['artifact_id']}: recorded {recorded}, "
                          f"re-evaluated {worst}")
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

    el = sub.add_parser("envlock", help="anti-reward-hacking eval window (triad)")
    el.add_argument("action", choices=["start", "end", "status"])
    el.add_argument("--agent", default="unknown")

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
    elif args.cmd == "envlock":
        sys.exit(0 if envlock_cmd(args.action, args.agent) else 1)
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
