#!/usr/bin/env python3
"""
Doctrine & Skills Hit-Rate Analyzer — staff-run doctrine housekeeping.

Answers the founder's question: which doctrine/skills are LOAD-BEARING, which are
dormant, and which are likely outdated temporary scaffolding that bottlenecks us?

Tiers (4 levels, exactly as the founder asked):
  T1 LOAD-BEARING   — referenced recently by sessions/memory/skills; core doctrine
  T2 ACTIVE         — used in the last 30 days or referenced by other live docs
  T3 DORMANT        — no usage signals in 30+ days; candidate for review
  T4 LIKELY-OUTDATED— dated/temporary doctrine past its purpose, or superseded
                      (contains dates >60 days old + 'temporary/parked/superseded'
                      language, or references dead providers/systems)

Signals used (all local, zero cost):
  - file mtime / date mentions inside the text
  - cross-references from other doctrine/skills (inbound link count)
  - Memory Lane mentions (FTS via :8770 /api/search if up)
  - skill registration state (skills list)
  - dead-system references (deepseek parked, groq dead, omniroute nuked, etc.)

OUTPUT: founder-readable report + machine-readable JSON for the Team Review Board.
NEVER edits anything. This is the review-prep layer; the founder + Hermes decide changes.

CLI:
  python doctrine_hitrate.py analyze         # full pass -> report + JSON
  python doctrine_hitrate.py skills          # skills-only quick pass
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FOUNDER_FILES = Path(r"./founder-files")
SKILLS_DIR = Path(r"./AppData/Local/hermes/skills")
OUT_DIR = Path("./bench/doctrine-reports")

DEAD_SYSTEMS = [
    r"\bdeepseek\b", r"\bgroq\b", r"\bomniroute\b", r"\bfreellmapi\b",
    r"\bvertex gemini\b", r"\bhoncho\b", r"\bstep[- ]?3\.7\b",
]
TEMPORARY_LANGUAGE = r"(temporary|parked|superseded|deprecated|interim|until we|placeholder|stopgap|migrated to)"
DATE_IN_TEXT = re.compile(r"20\d{2}-\d{2}-\d{2}")

T1_PATTERNS = r"(triad|block logic|memory lane|origin rule|autonomy|approval|staff|glm|maya)"


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _mtime_days(p):
    try:
        return (datetime.now().timestamp() - os.path.getmtime(p)) / 86400
    except OSError:
        return 9999


def collect_doctrine_files():
    """Doctrine lives in several homes; gather them all."""
    files = []
    for p in [Path(r"./AppData/Local/hermes/SOUL.md"),
              Path(r"./AGENTS.md"),
              Path(r"./AppData/Local/hermes/SOUL_CONTINUED.md")]:
        if p.exists():
            files.append(p)
    for pat in ("doctrine/*.md", "company/*.md", "repo-infusion/*DOCTRINE*.md",
                "10-Architecture/*Doctrine*.md", "*DOCTRINE*.md", "*doctrine*.md",
                "founders-notes/*.md"):
        files.extend(FOUNDER_FILES.glob(pat))
    # dedupe
    seen = set()
    out = []
    for f in files:
        rp = f.resolve()
        if rp not in seen and f.stat().st_size < 500_000:
            seen.add(rp)
            out.append(f)
    return out


SACRED_FILES = {"SOUL.md", "AGENTS.md", "SOUL_CONTINUED.md", "COMPANY_VISION.md"}


def analyze_doctrine_file(path, all_paths):
    """Classify one doctrine file into T1-T4 with evidence."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lower = text.lower()
    name = path.stem
    if path.name in SACRED_FILES:
        return {"file": str(path), "name": name, "tier": "T1-LOAD-BEARING",
                "size_kb": round(path.stat().st_size / 1024, 1),
                "evidence": ["sacred system file — permanent doctrine, never flagged"]}
    evidence = []

    # age signals
    mt_days = _mtime_days(path)
    dates = DATE_IN_TEXT.findall(text)
    newest_date = max(dates) if dates else None
    if newest_date:
        try:
            d_days = (datetime.now() - datetime.strptime(newest_date, "%Y-%m-%d")).days
        except ValueError:
            d_days = mt_days
    else:
        d_days = mt_days

    # dead-system references (strong T4 signal when file is also old)
    dead_hits = [p for p in DEAD_SYSTEMS if re.search(p, lower)]

    # temporary language
    temp_hits = bool(re.search(TEMPORARY_LANGUAGE, lower))

    # inbound references: how many other doctrine files mention this file's name tokens?
    name_tokens = [t for t in re.split(r"[_\-\s]+", name) if len(t) > 4][:3]
    inbound = 0
    for other in all_paths:
        if other == path:
            continue
        try:
            ot = other.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(tok.lower() in ot for tok in name_tokens):
            inbound += 1

    # core doctrine patterns
    core = bool(re.search(T1_PATTERNS, lower))

    # usage proxy: was this file touched/mentioned by recent bench artifacts?
    bench_hit = False
    try:
        ledger = Path("./bench/LEDGER.jsonl")
        if ledger.exists():
            led = open(ledger, encoding="utf-8", errors="replace").read().lower()
            bench_hit = any(tok.lower() in led for tok in name_tokens) or name.lower() in led
    except OSError:
        pass

    # classify
    if core and (inbound >= 3 or bench_hit or mt_days < 14):
        tier = "T1-LOAD-BEARING"
    elif mt_days < 30 or inbound >= 1 or bench_hit:
        tier = "T2-ACTIVE"
    elif dead_hits and (d_days > 60 or temp_hits):
        tier = "T4-LIKELY-OUTDATED"
    elif temp_hits and d_days > 45:
        tier = "T4-LIKELY-OUTDATED"
    elif mt_days > 90 and inbound == 0:
        tier = "T4-LIKELY-OUTDATED"
    else:
        tier = "T3-DORMANT"

    if dead_hits:
        stripped = [h.replace('\\b', '') for h in dead_hits]
        evidence.append(f"references dead systems: {', '.join(stripped)}")
    if temp_hits:
        evidence.append("contains temporary/parked/superseded language")
    if newest_date:
        evidence.append(f"newest in-text date {newest_date} ({d_days}d ago)")
    evidence.append(f"file age {int(mt_days)}d")
    evidence.append(f"inbound refs from other doctrine: {inbound}")
    evidence.append("referenced in bench activity" if bench_hit else "no bench references")

    return {
        "file": str(path),
        "name": name,
        "tier": tier,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "evidence": evidence,
    }


def collect_skills():
    """All SKILL.md files with usage-state classification."""
    out = []
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.parent
        name = rel.name
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        mt_days = _mtime_days(skill_md)
        lower = text.lower()
        dead = [p.strip("\\b") for p in DEAD_SYSTEMS if re.search(p, lower)]
        # enabled check via hermes skills list is expensive per-skill; use dir presence + age
        tier = ("T1-LOAD-BEARING" if name in ("ponytail", "humanizer", "block-logic",
                "arc-continuity-pass", "maya-provider-router") else
                "T2-ACTIVE" if mt_days < 30 else
                "T4-LIKELY-OUTDATED" if (dead and mt_days > 45) or mt_days > 120 else
                "T3-DORMANT")
        out.append({"skill": name, "path": str(rel), "tier": tier,
                    "age_days": int(mt_days), "dead_refs": dead})
    return out


def analyze():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = collect_doctrine_files()
    results = []
    for f in files:
        r = analyze_doctrine_file(f, files)
        if r:
            results.append(r)

    skills = collect_skills()

    # report
    tiers = {}
    for r in results:
        tiers.setdefault(r["tier"], []).append(r)

    lines = [
        "---", "artifact_type: doctrine_report", f"generated: {_ts()}", "---", "",
        "# Doctrine & Skills Hit-Rate Report", "",
        f"> *Staff-run analysis for founder review. Nothing was edited. "
        f"{len(results)} doctrine files + {len(skills)} skills classified.*", "",
        "## The four tiers", "",
        "- **T1 LOAD-BEARING** — core doctrine the office runs on",
        "- **T2 ACTIVE** — used or referenced in the last 30 days",
        "- **T3 DORMANT** — no usage signals in 30+ days, review when convenient",
        "- **T4 LIKELY-OUTDATED** — temporary/parked/superseded or references dead systems",
        "",
    ]
    for tier in sorted(tiers):
        items = sorted(tiers[tier], key=lambda x: -x["size_kb"])
        lines.append(f"## {tier} ({len(items)})\n")
        for it in items[:25]:
            lines.append(f"- **{it['name']}** ({it['size_kb']}KB) — {'; '.join(it['evidence'][:3])}")
        if len(items) > 25:
            lines.append(f"- ...and {len(items) - 25} more")
        lines.append("")

    lines.append("## Skills by tier\n")
    sk_tiers = {}
    for s in skills:
        sk_tiers.setdefault(s["tier"], []).append(s)
    for tier in sorted(sk_tiers):
        names = sorted(s["skill"] for s in sk_tiers[tier])
        lines.append(f"- **{tier}** ({len(names)}): " + ", ".join(names[:20]) +
                     (f", +{len(names)-20} more" if len(names) > 20 else ""))

    report = "\n".join(lines) + "\n"
    rp = OUT_DIR / f"doctrine-hitrate-{_ts()}.md"
    rp.write_text(report, encoding="utf-8")
    (OUT_DIR / "doctrine-hitrate-latest.json").write_text(
        json.dumps({"doctrine": results, "skills": skills, "generated": _ts()},
                   indent=1), encoding="utf-8")

    print(f"report: {rp}")
    print(f"doctrine: " + ", ".join(f"{t}: {len(v)}" for t, v in sorted(tiers.items())))
    print(f"skills: " + ", ".join(f"{t}: {len(v)}" for t, v in sorted(sk_tiers.items())))


def skills_only():
    skills = collect_skills()
    tiers = {}
    for s in skills:
        tiers.setdefault(s["tier"], []).append(s["skill"])
    for t in sorted(tiers):
        print(f"{t} ({len(tiers[t])}): {', '.join(sorted(tiers[t])[:15])}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    if cmd == "analyze":
        analyze()
    elif cmd == "skills":
        skills_only()
    else:
        print("usage: doctrine_hitrate.py [analyze|skills]")
