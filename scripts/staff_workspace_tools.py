#!/usr/bin/env python3
"""
Staff Workspace Tools — the capability layer that makes staff a REAL office.

Each staff turn can now, autonomously:
  - web_search(query)        real-time web research (DuckDuckGo HTML, no key)
  - github_repos()           list/star/read the founder's repos via gh CLI
  - github_read(owner/repo)  read a repo's README + recent commits
  - email_triage(limit)      read Gmail inbox summaries (himalaya), flag what matters
  - read_file(path)          read any file inside allowed roots
  - write_note(filename, text)  write a work note into their workspace (their own desk)
  - propose_code(filename, code)  stage a code change for Hermes review (never self-apply)
  - escalate_to_hermes(msg)  drop a request into Hermes' escalation inbox
  - bench_register(...)      file artifacts on the swarm bench

SAFETY MODEL (the founder's standard, 2026-09-06):
  - Autonomous: read anything, research anything, write NOTES + STAGED CODE only.
  - Autonomous: reversible ops (archive to E: with manifest, rename with record).
  - Escalate: deletion, mass changes, destructive ops, anything touching
    secrets/credentials/financial — via propose_code -> Hermes review -> board.
  - Staff never run: rm/del on anything, git push, pip install system-wide,
  - or anything that touches Desktop/Downloads/AppData outside allowed roots.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("./bench/staff-workspace")
ESCALATION_INBOX = Path(r"./scripts")
HERMES_ESCALATION_FILE = ESCALATION_INBOX / "hermes_staff_escalations.jsonl"
ALLOWED_READ_ROOTS = [
    r"./2ndnatureai-maya-beta",
    r"./scripts",
    r"./founder-files",
    r"./memory-lane",
    r"./repo-shelves",
    r"./claw3d",
]

MAX_WEB_RESULTS = 5
MAX_READ_BYTES = 200_000


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- web research

def web_search(query):
    """Real-time web research via DuckDuckGo HTML (no API key)."""
    try:
        q = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?q={q}",
            headers={"User-Agent": "Mozilla/5.0 (staff-research)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        results = []
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
            url = m.group(1)
            # ddg wraps urls; extract real target
            um = re.search(r'uddg=([^&]+)', url)
            if um:
                import base64
                url = base64.urlsafe_b64decode(um.group(1) + "==").decode("utf-8", errors="replace")
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            results.append({"title": title, "url": url})
            if len(results) >= MAX_WEB_RESULTS:
                break
        if not results:
            # ddgs package fallback (installed locally)
            try:
                from ddgs import DDGS
                with DDGS() as d:
                    for row in d.text(query, max_results=MAX_WEB_RESULTS):
                        results.append({"title": row.get("title", "")[:120],
                                        "url": row.get("href", "")})
            except Exception:
                pass
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------- github

def github_repos(limit=30):
    """the founder's starred repos — the discovery shelf."""
    try:
        r = subprocess.run(
            ["gh", "api", f"user/starred?per_page={limit}",
             "--jq", ".[] | [.full_name, .stargazers_count, .pushed_at] | @tsv"],
            capture_output=True, text=True, timeout=30)
        rows = []
        for line in (r.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                rows.append({"repo": parts[0], "stars": int(parts[1]), "pushed": parts[2]})
        return {"ok": True, "repos": rows}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def github_read(repo):
    """Read a repo's README + last 5 commits."""
    out = {}
    try:
        r = subprocess.run(["gh", "api", f"repos/{repo}/readme",
                            "--jq", ".content"],
                           capture_output=True, text=True, timeout=30)
        import base64
        if r.stdout.strip():
            out["readme"] = base64.b64decode(r.stdout.strip()).decode("utf-8", errors="replace")[:6000]
        r2 = subprocess.run(["gh", "api", f"repos/{repo}/commits?per_page=5",
                             "--jq", '.[] | .commit.message | split("\\n")[0]'],
                            capture_output=True, text=True, timeout=30)
        out["recent_commits"] = [l for l in (r2.stdout or "").splitlines() if l.strip()]
        return {"ok": True, **out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------- email triage

def email_triage(limit=15):
    """Read Gmail inbox summaries. READ-ONLY — staff never send or delete."""
    try:
        r = subprocess.run(["himalaya", "envelope", "list", "--page-size", str(limit),
                            "--output", "json"],
                           capture_output=True, text=True, timeout=45)
        import json as _json
        data = _json.loads(r.stdout) if (r.stdout or "").strip() else []
        items = []
        for e in data if isinstance(data, list) else []:
            items.append({
                "id": e.get("id"),
                "subject": e.get("subject", "")[:100],
                "from": (e.get("from") or [{}])[0].get("email", "?") if isinstance(e.get("from"), list) else str(e.get("from", "?"))[:60],
                "date": e.get("date", ""),
            })
        # triage classification: what needs the founder vs what's noise
        needs_josh = [i for i in items if re.search(
            r"(invoice|payment|bill|legal|deadline|action required|security|verify|suspended|urgently)",
            i["subject"], re.I)]
        return {"ok": True, "count": len(items), "items": items,
                "needs_josh_attention": needs_josh,
                "note": "read-only triage; staff never send/delete/reply"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------- file access

def _allowed(path):
    rp = os.path.realpath(path).replace("\\", "/").lower()
    return any(rp.startswith(root.replace("\\", "/").lower()) for root in ALLOWED_READ_ROOTS)


def read_file(path):
    if not _allowed(path):
        return {"ok": False, "error": f"outside allowed roots: {path}"}
    try:
        body = open(path, encoding="utf-8", errors="replace").read()
        truncated = len(body) > MAX_READ_BYTES
        return {"ok": True, "content": body[:MAX_READ_BYTES], "truncated": truncated,
                "size": len(body)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def list_dir(path):
    if not _allowed(path):
        return {"ok": False, "error": f"outside allowed roots: {path}"}
    try:
        entries = os.listdir(path)
        return {"ok": True, "entries": entries[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------- staff desk

def write_note(staff, filename, text):
    """Staff write into their OWN desk only. Their workspace, their notes."""
    d = WORKSPACE / staff
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
    if not safe.endswith((".md", ".txt", ".json")):
        safe += ".md"
    p = d / safe
    p.write_text(f"---\nauthor: {staff}\nts: {_ts()}\n---\n\n{text}\n", encoding="utf-8")
    return {"ok": True, "path": str(p)}


def propose_code(staff, target_hint, filename, code, rationale):
    """Stage a code change for HERMES review. Never self-applied.
    Lands in the staff workspace + Hermes escalation file + bench."""
    d = WORKSPACE / staff / "proposals"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
    p = d / safe
    p.write_text(
        f"// PROPOSED by {staff} at {_ts()}\n"
        f"// TARGET: {target_hint}\n"
        f"// RATIONALE: {rationale}\n"
        f"// STATUS: staged — Hermes reviews, decides apply/reject\n\n" + code,
        encoding="utf-8")
    # escalate to Hermes
    esc = {"ts": _ts(), "staff": staff, "type": "code_proposal",
           "target": target_hint, "file": str(p), "rationale": rationale[:300]}
    try:
        with open(HERMES_ESCALATION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(esc) + "\n")
    except OSError:
        pass
    return {"ok": True, "staged": str(p), "escalated_to_hermes": True,
            "note": "Hermes reviews and applies/rejects. Staff code never self-applies."}


def escalate_to_hermes(staff, message, severity="normal"):
    """Drop a request/finding into Hermes' escalation inbox."""
    esc = {"ts": _ts(), "staff": staff, "type": "escalation",
           "severity": severity, "message": message[:2000]}
    try:
        with open(HERMES_ESCALATION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(esc) + "\n")
        return {"ok": True, "note": "Hermes will see this in the next check."}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def read_escalations(limit=20):
    """Hermes-side: read the staff escalation inbox."""
    try:
        if not HERMES_ESCALATION_FILE.exists():
            return {"ok": True, "escalations": []}
        lines = open(HERMES_ESCALATION_FILE, encoding="utf-8").read().splitlines()
        return {"ok": True, "escalations": [json.loads(l) for l in lines[-limit:] if l.strip()]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------- dispatch

TOOLMAP = {
    "web_search": web_search,
    "github_repos": github_repos,
    "github_read": github_read,
    "email_triage": email_triage,
    "read_file": read_file,
    "list_dir": list_dir,
    "write_note": write_note,
    "propose_code": propose_code,
    "escalate_to_hermes": escalate_to_hermes,
    "read_escalations": read_escalations,
}


def dispatch(tool, **kwargs):
    fn = TOOLMAP.get(tool)
    if not fn:
        return {"ok": False, "error": f"unknown tool: {tool}"}
    if tool in ("write_note", "propose_code", "escalate_to_hermes"):
        if not kwargs.get("staff"):
            return {"ok": False, "error": "staff name required"}
    # Only pass kwargs each tool actually accepts.
    import inspect
    sig = inspect.signature(fn)
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(**accepted)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("tool")
    ap.add_argument("--staff")
    ap.add_argument("--query")
    ap.add_argument("--repo")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--path")
    ap.add_argument("--filename")
    ap.add_argument("--text")
    ap.add_argument("--code")
    ap.add_argument("--rationale")
    ap.add_argument("--target-hint")
    ap.add_argument("--message")
    ap.add_argument("--severity", default="normal")
    a = ap.parse_args()
    kwargs = {}
    for k in ("staff", "query", "repo", "limit", "path", "filename", "text",
              "code", "rationale", "target_hint", "message", "severity"):
        v = getattr(a, k, None)
        if v is not None:
            kwargs[k] = v
    import json as _json
    print(_json.dumps(dispatch(a.tool, **kwargs), indent=1)[:4000])


if __name__ == "__main__":
    main()
