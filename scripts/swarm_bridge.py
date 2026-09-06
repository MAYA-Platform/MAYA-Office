#!/usr/bin/env python3
"""
Swarm Bench — Ecology Bridge. Wires the bench into every staff surface.

This is the ORGANISM layer: on each tick it
  1. Reads the runner-sweep outbox / live-log for new staff output and
     auto-registers genuine work products as bench artifacts (dedup-safe).
  2. Syncs the bench state to:
       - staff-office.html   (2D office: artifact feed per active desk)
       - Claw3D adapter       (reads the ledger directly — already live)
       - Memory Lane          (chain-linked blocks via :8770 write API)
       - Obsidian vault       (ecology note under 10-Architecture/)
       - live-log.md          (world state, already injected pre-sweep)
  3. Tallies emergence and flags role drift to FOUNDER_REVIEW_QUEUE.md
     when an agent's observed behavior diverges twice in a row.

Run manually or via cron. Idempotent: safe to run any time.
  python swarm_bridge.py            # full tick
  python swarm_bridge.py --open     # also opens the Claw3D office
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BENCH = "./bench"
LEDGER = os.path.join(BENCH, "LEDGER.jsonl")
FOUNDER_FILES = Path(r"./founder-files")
STAFF_COMMS = FOUNDER_FILES / "staff-comms"
LIVE_LOG = STAFF_COMMS / "live-room" / "live-log.md"
PROGRESS_LOG = FOUNDER_FILES / "STAFF_PROGRESS_LOG.md"
REVIEW_QUEUE = FOUNDER_FILES / "FOUNDER_REVIEW_QUEUE.md"
OFFICE_HTML = STAFF_COMMS / "staff-office.html"
VAULT_NOTE = FOUNDER_FILES / "10-Architecture" / "Swarm Bench Ecology.md"
BENCH_PY = r"./scripts/swarm_bench.py"
ML_WRITE = "http://localhost:8770/api/blocks/write"

# Active management+council roster for office rendering (souls exist for all;
# bench ASSIGNED_ROLES in swarm_bench.py already knows them).
OFFICE_STAFF = [
    ("shadow", "Shadow", "The Banker — Strategy & Intel Synthesis"),
    ("chief", "Chief", "Operations Commander — Chain of Command"),
    ("nova", "Nova", "Design Lead — Visual Identity & UI"),
    ("herald", "Herald", "Communications — Debrief & Delivery"),
    ("sage", "Sage", "Security — AI Red Team & Scans"),
    ("scribe", "Scribe", "Memory — Founder Files & Progress"),
    ("flint", "Flint", "Discovery — Repo Scout"),
    ("forge", "Forge", "Builder — Implementation"),
    ("specter", "Specter", "Security Research — SPECTER Ops"),
    ("plumb", "Plumb", "Maintenance — Ops Hygiene"),
]


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]


def bench(*args):
    return subprocess.run([sys.executable, BENCH_PY, *args],
                          capture_output=True, text=True, timeout=60)


def now_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 1. Auto-register staff work from the live room's reply stream.
#    The sweep writes replies to live-log.md; sections starting with agent
#    names + substantive bodies become 'report' artifacts. Dedup by title.
# ---------------------------------------------------------------------------

def harvest_live_log():
    if not LIVE_LOG.exists():
        return 0
    ledger = read_ledger()
    known = {a["title"] for a in ledger}
    body = LIVE_LOG.read_text(encoding="utf-8", errors="replace")
    # Staff reply pattern in live-log: "**Name** ..." reply blocks.
    blocks = re.findall(r"\*\*(Nova|Shadow|Chief|Herald|Sage|Scribe|Flint|Plumb|Gatekeeper|Kai|Zen|Forge)\*\*[:\s]\s*(.+?)(?=\n\*\*|\n---|\Z)",
                        body, re.S)
    registered = 0
    for name, reply in blocks:
        reply = reply.strip()
        if len(reply) < 200:  # substantive work only, not chatter
            continue
        title = f"Live-room output: {name} ({reply[:40].strip()}...)"
        if title in known:
            continue
        # Substantive replies count as analysis artifacts from that agent.
        agent = {"Flint": "flint", "Gatekeeper": "gatekeeper"}.get(name, name.lower())
        r = bench("register", "--agent", agent, "--type", "analysis",
                  "--title", title, "--text", reply[:4000],
                  "--notes", "auto-harvested from live-room output")
        if r.returncode == 0 and "registered" in r.stdout:
            registered += 1
            known.add(title)
    return registered


# ---------------------------------------------------------------------------
# 2a. Sync artifact feed into staff-office.html (2D office desks)
# ---------------------------------------------------------------------------

def sync_office_html():
    if not OFFICE_HTML.exists():
        return False
    ledger = read_ledger()
    by_agent = {}
    for a in ledger:
        if a["world_verdict"] == "PASS":
            by_agent.setdefault(a["agent"], []).append(a)

    # Build an artifact ticker block and inject before the log-hdr section
    rows = []
    for slug, name, _role in OFFICE_STAFF:
        arts = by_agent.get(slug, [])
        if arts:
            latest = arts[-1]
            rows.append(
                f"<div class='bench-row'><b>{name}</b> · {len(arts)} verified artifact(s) · "
                f"latest: <i>{latest['title'][:48]}</i> <code>{latest['artifact_id']}</code></div>")
        else:
            rows.append(f"<div class='bench-row'><b>{name}</b> · no artifacts yet</div>")
    ticker = ("<div id='swarm-bench-feed' style='margin:10px 0 18px;padding:12px 14px;"
              "border:1px solid #3a2f1f;border-radius:10px;background:rgba(230,168,23,0.05);'>"
              "<div style='font-size:11px;letter-spacing:2px;color:#e6a817;margin-bottom:8px;'>"
              "SWARM BENCH — WORLD-VERIFIED ARTIFACTS</div>" + "".join(rows) + "</div>")

    html = OFFICE_HTML.read_text(encoding="utf-8")
    if "swarm-bench-feed" in html:
        # replace existing block
        html = re.sub(r"<div id='swarm-bench-feed'.*?</div>\s*</div>",
                      ticker, html, count=1, flags=re.S)
    else:
        html = html.replace("<div class=\"log-hdr\">", ticker + "\n<div class=\"log-hdr\">", 1)
    OFFICE_HTML.write_text(html, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# 2b. Memory Lane: every Nth artifact seals a chain-linked block
# ---------------------------------------------------------------------------

def sync_memory_lane():
    ledger = read_ledger()
    if not ledger:
        return 0
    # Only seal the latest artifact if it's not already the newest ML swarm block
    latest = ledger[-1]
    try:
        req = urllib.request.Request("http://localhost:8770/api/recent?n=5")
        with urllib.request.urlopen(req, timeout=8) as resp:
            recent = json.loads(resp.read().decode())
        already = any(l.get("lineage") == "swarm_bench" and latest["artifact_id"] in (l.get("body") or "")
                      for l in recent.get("blocks", []))
        if already:
            return 0
        text = (f"Swarm artifact {latest['artifact_id']}: {latest['title']} — "
                f"built by {latest['agent']}, type {latest['type']}, "
                f"world verdict {latest['world_verdict']}."
                + (f" Inherits {', '.join(latest['parents'])}." if latest.get("parents") else ""))
        body = json.dumps({"text": text, "source": "swarm-bench", "lineage": "swarm_bench"}).encode()
        req = urllib.request.Request(ML_WRITE, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 1 if json.loads(resp.read().decode()).get("ok") else 0
    except Exception as e:
        print(f"ML sync skipped: {e}")
        return 0


# ---------------------------------------------------------------------------
# 2c. Obsidian vault: ecology note ((dataview-friendly, plain markdown)
# ---------------------------------------------------------------------------

def sync_vault_note():
    ledger = read_ledger()
    by_agent = {}
    for a in ledger:
        by_agent.setdefault(a["agent"], []).append(a)
    lines = [
        "---", "artifact_type: ecology_note", "source: swarm-bench",
        f"updated: {now_ts()}", "---", "",
        "# Swarm Bench Ecology", "",
        f"> *Auto-generated from the staff shared world. {len(ledger)} artifacts, "
        f"{sum(1 for a in ledger if a['world_verdict']=='PASS')} world-verified. "
        f"Last sync {now_ts()}.*", "",
        "## Lineage map", "",
    ]
    for a in ledger:
        parents = f" ← {', '.join(a['parents'])}" if a.get("parents") else ""
        icon = {"PASS": "✅", "FAIL": "❌", "UNVERIFIABLE": "🔵"}.get(a["world_verdict"], "⚪")
        lines.append(f"- {icon} **[[{a['artifact_id']}]]** {a['title']} — *{a['agent']}*, {a['type']}{parents}")
    lines += ["", "## Agents in the ecology", ""]
    for agent, arts in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- **{agent}**: {len(arts)} artifact(s)")
    VAULT_NOTE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_NOTE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# 3. Emergence → founder queue on repeated drift
# ---------------------------------------------------------------------------

def check_drift_to_founder_queue():
    r = bench("tally")
    drift_lines = [l for l in r.stdout.splitlines() if "<-- DRIFT" in l]
    if len(drift_lines) < 3:
        return False  # normal variation
    new_block = f"\n- **{now_ts()}** SWARM EMERGENCE: {len(drift_lines)} agents showing sustained role drift — " \
                + "; ".join(l.strip() for l in drift_lines) + \
                ". Review whether to bless the drift (update souls) or redirect."
    new_signature = "; ".join(l.strip() for l in drift_lines)
    if REVIEW_QUEUE.exists():
        existing = REVIEW_QUEUE.read_text(encoding="utf-8", errors="replace")
        # Dedup on drift CONTENT (agent:assigned vs observed), never timestamp.
        # Signature appears anywhere in the line (timestamp prefix varies per run).
        existing_lines = existing.splitlines()
        for line in existing_lines:
            if "SWARM EMERGENCE" in line and new_signature[:120] in line:
                return False  # this exact drift state already flagged
        REVIEW_QUEUE.write_text(existing.rstrip() + "\n" + new_block, encoding="utf-8")
    else:
        REVIEW_QUEUE.write_text("# Founder Review Queue\n" + new_block, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main tick
# ---------------------------------------------------------------------------

def main():
    opened = "--open" in sys.argv
    harvested = harvest_live_log()
    office = sync_office_html()
    ml = sync_memory_lane()
    vault = sync_vault_note()
    drift = check_drift_to_founder_queue()

    receipt = (f"swarm bridge tick: harvested={harvested} office={'ok' if office else 'skip'} "
               f"ml_sealed={ml} vault_note={'ok' if vault else 'skip'} drift_flag={drift}")
    print(receipt)

    if opened:
        subprocess.Popen(["cmd", "/c", "start", "", "http://localhost:3000"],
                         shell=True)


if __name__ == "__main__":
    main()
