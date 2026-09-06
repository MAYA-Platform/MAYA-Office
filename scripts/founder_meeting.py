#!/usr/bin/env python3
"""
Founder Meeting Request — emails the founder when review-ready documents pile up.

The trigger philosophy: only ping when there's a genuine SIT-DOWN decision set.
Groups: doctrine (T3/T4 tiers), skills (T3/T4), desktop (dup/archive decisions),
board escalations (the founder-needed cards). When total decision items >= threshold
(default 8), send ONE email with: what needs deciding, the docs to read,
and a proposed meeting agenda.

Cron: weekly check (Monday morning). Also runnable manually.
  python founder_meeting.py check [--force]
  python founder_meeting.py status
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path("./bench")
DOCTRINE_JSON = BENCH / "doctrine-reports" / "doctrine-hitrate-latest.json"
DESKTOP_DIR = BENCH / "desktop-reports"
MEETING_SENT_LOG = BENCH / "founder-meetings-sent.json"
THRESHOLD = 8

FOUNDER_EMAIL = "founder@example.com"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load_json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def gather_decision_items():
    items = {"doctrine": [], "skills": [], "desktop": [], "board": [], "crons": []}
    # cron housekeeping: count stale-target/dead-provider/duplicate-name jobs
    try:
        r = subprocess.run(["hermes", "cron", "list"], capture_output=True, text=True, timeout=60)
        lines = (r.stdout or "").splitlines()
        names = [l.split("Name:")[-1].strip() for l in lines if "Name:" in l]
        dupes = len(names) - len(set(names))
        deadref = sum(1 for l in lines if re.search(r"deepseek|groq|omniroute", l, re.I))
        items["crons"] = [{"name": "cron fleet audit", "count": dupes + deadref,
                            "detail": f"{len(names)} total jobs, {dupes} duplicate names, {deadref} dead-provider refs"}]
    except Exception:
        pass

    data = load_json(DOCTRINE_JSON)
    if data:
        t34 = [d for d in data.get("doctrine", []) if d["tier"].startswith(("T3", "T4"))]
        items["doctrine"] = t34
        sk34 = [s for s in data.get("skills", []) if s["tier"].startswith(("T3", "T4"))]
        items["skills"] = sk34

    # desktop scan: count decision items from latest report
    if DESKTOP_DIR.exists():
        reports = sorted(DESKTOP_DIR.glob("desktop-scan-*.md"))
        if reports:
            text = reports[-1].read_text(encoding="utf-8", errors="replace")
            dups = len(re.findall(r"^\- \*\*.*x\d+", text, re.M))
            copies = len(re.findall(r"^- [^\n]+/$", text, re.M))
            archives = len(re.findall(r"archive-to-E: candidates", text))
            items["desktop"] = [{"name": "desktop decisions", "count": dups + copies + archives}]

    # board: count the founder-needed cards from the review board state file if present
    board_state = Path(r"./2ndnatureai-maya-beta/maya-agent/state/team-review-board.json")
    if board_state.exists():
        try:
            bs = json.load(open(board_state, encoding="utf-8"))
            cards = bs.get("cards", bs if isinstance(bs, list) else [])
            josh_needed = [c for c in cards if isinstance(c, dict) and
                           (c.get("requiresFounderApproval") or c.get("founderApprovalRequired"))]
            items["board"] = josh_needed
        except Exception:
            pass

    return items


def total_count(items):
    return (len(items["doctrine"]) + len(items["skills"]) +
            len(items["desktop"]) + len(items["board"]) +
            len(items.get("crons", [])))


def already_sent_recently():
    log = load_json(MEETING_SENT_LOG) or {"sent": []}
    for s in log["sent"]:
        if (datetime.now(timezone.utc) - datetime.fromisoformat(s["ts"])).days < 5:
            return True
    return False


def build_email(items, total, score_line=""):
    t34 = items["doctrine"]
    sk34 = items["skills"]
    top_doctrine = sorted(t34, key=lambda x: -x.get("size_kb", 0))[:10]
    agenda = [
        f"1. DOCTRINE cleanup ({len(t34)} dormant/outdated files)",
        f"2. SKILLS cleanup ({len(sk34)} dormant/outdated skills)",
        f"3. Desktop organization ({items['desktop'][0]['count'] if items['desktop'] else 0} items)",
        f"4. Board escalations ({len(items['board'])} the founder-needed cards)",
        f"5. CRON fleet housekeeping ({items.get('crons', [{}])[0].get('detail', 'see audit') if items.get('crons') else 'clean'})",
    ]
    doctrine_list = "\n".join(
        f"  - {d['name']} ({d['tier']}, {d['size_kb']}KB)" for d in top_doctrine) or "  (none)"
    skills_list = "\n".join(
        f"  - {s['skill']} ({s['tier']})" for s in sk34[:15]) or "  (none)"
    desktop_list = "\n".join(
        f"  - {d['name']}: {d.get('count', '?')} items" for d in items["desktop"]) or "  (none)"
    board_list = "\n".join(
        f"  - {c.get('title', c.get('id', '?'))}" for c in items["board"][:10]) or "  (none)"

    body = f"""Founder Meeting Request — {total} decision items waiting

Hi the founder,

The office has piled up review-ready work. This is the sit-down-you-asked-for email:
everything below is organized and ready for us to make decisions together.

AGENDA
{chr(10).join(agenda)}

DOCTRINE (read the full report first: ./bench/doctrine-reports/doctrine-hitrate-{datetime.now().strftime('%Y-%m-%d')}.md)
{doctrine_list}

SKILLS
{skills_list}

DESKTOP
{desktop_list}

BOARD
{board_list}

WHAT WE'LL DECIDE
- Which T4 doctrine gets archived vs rewritten vs deleted
- Which dormant skills get removed vs revived
- Which desktop duplicates get merged/archived
- Which board escalations get approved

SWARM EFFICIENCY: {score_line or "not yet scored"}

Bring 30 minutes. I'll bring the reports.
- Hermes, on behalf of the swarm
"""
    return body


def send_meeting_email(body):
    subject = f"FOUNDER MEETING NEEDED — swarm review decisions ready ({_now()[:10]})"
    mml = (f"From: founder@example.com\n"
           f"To: {FOUNDER_EMAIL}\n"
           f"Subject: {subject}\n"
           f"Content-Type: text/plain; charset=utf-8\n\n{body}\n")
    import tempfile
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".mml", delete=False, encoding="utf-8")
    f.write(mml)
    f.close()
    r = subprocess.run(["himalaya", "message", "send"],
                       stdin=open(f.name, encoding="utf-8"),
                       capture_output=True, text=True, timeout=60)
    os.unlink(f.name)
    return "successfully sent" in (r.stdout or "")


def check(force=False):
    items = gather_decision_items()
    total = total_count(items)
    if not force and total < THRESHOLD:
        print(f"below threshold: {total}/{THRESHOLD} decision items. No meeting email.")
        return False
    if not force and already_sent_recently():
        print("meeting email sent within the last 5 days — not re-sending.")
        return False
    body = build_email(items, total, score_line=score_line)
    # efficiency score snapshot for the meeting
    try:
        r2 = subprocess.run(["python", r"./scripts/swarm_efficiency.py", "report"],
                            capture_output=True, text=True, timeout=60)
        score_line = next((l for l in (r2.stdout or "").splitlines() if "SCORE" in l), "")
    except Exception:
        score_line = ""
    ok = send_meeting_email(body)
    if ok:
        log = load_json(MEETING_SENT_LOG) or {"sent": []}
        log["sent"].append({"ts": datetime.now(timezone.utc).isoformat(), "total": total})
        json.dump(log, open(MEETING_SENT_LOG, "w", encoding="utf-8"), indent=1)
        print(f"FOUNDER MEETING EMAIL SENT ({total} decision items).")
        print(body[:600])
        return True
    print("email send FAILED")
    return False


def status():
    items = gather_decision_items()
    total = total_count(items)
    print(f"decision items: {total} (threshold {THRESHOLD})")
    print(f"  doctrine T3/T4: {len(items['doctrine'])}")
    print(f"  skills T3/T4:   {len(items['skills'])}")
    print(f"  desktop:        {items['desktop'][0]['count'] if items['desktop'] else 0}")
    print(f"  board:          {len(items['board'])}")
    print(f"sent recently: {'yes' if already_sent_recently() else 'no'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "check":
        check(force="--force" in sys.argv)
    elif cmd == "status":
        status()
    else:
        print("usage: founder_meeting.py [check|status] [--force]")
