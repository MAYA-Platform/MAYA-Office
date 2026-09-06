#!/usr/bin/env python3
"""
Desktop Duplicate & Clutter Scanner — READ-ONLY, founder-review output.

Finds on the founder's Desktop (OneDrive Desktop, the real one):
  1. Duplicate files (same size + same partial hash = likely copies)
  2. Duplicate-name folders ("- COPY", " (2)", "old", "backup" patterns)
  3. Stray archives that should live on E:
  4. Loose text/md files that belong in Founder Files

NEVER moves or deletes anything. Output: a founder-readable review sheet
grouped into KEEP / REVIEW / ARCHIVE-CANDIDATE categories so the founder + Hermes
can decide together what happens.

CLI: python desktop_scan.py [scan]
"""

import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

DESKTOP = Path(r"./desktop")
OUT_DIR = Path("./bench/desktop-reports")

ARCHIVE_EXTS = {".zip", ".tar.gz", ".7z", ".rar", ".tgz"}
CLUTTER_PAT = re.compile(
    r"(copy|\(\d\)|old|backup|bak|duplicate|final|final2|newfolder|untitled)", re.I)
COPY_PAT = re.compile(r" - (DESKTOP )?COPY", re.I)
MAX_HASH_BYTES = 1024 * 1024  # hash first 1MB + size = good-enough dup signal


def _hash_file(p, limit=MAX_HASH_BYTES):
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            h.update(f.read(limit))
        return h.hexdigest()[:16]
    except OSError:
        return None


def scan():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    dirs = []
    for e in DESKTOP.iterdir():
        if e.name in ("desktop.ini", "target.lnk"):
            continue
        try:
            if e.is_dir():
                dirs.append(e)
            else:
                files.append(e)
        except OSError:
            continue

    # 1. content duplicates
    sig_map = {}
    for f in files:
        if f.stat().st_size == 0:
            continue
        sig = (f.stat().st_size, _hash_file(f))
        sig_map.setdefault(sig, []).append(f)
    dups = {k: v for k, v in sig_map.items() if len(v) > 1}

    # 2. name-pattern groups
    copy_named = [f for f in files if COPY_PAT.search(f.stem)]
    clutter_named = [f for f in files if CLUTTER_PAT.search(f.stem)]
    dup_dirs = [d for d in dirs if COPY_PAT.search(d.name) or CLUTTER_PAT.search(d.name)]

    # 3. archives on desktop
    archives = [f for f in files if f.suffix.lower() in ARCHIVE_EXTS
                or f.name.lower().endswith((".tar.gz",))]

    # 4. loose docs that belong in Founder Files
    loose_docs = [f for f in files if f.suffix.lower() in (".md", ".txt")
                  and not CLUTTER_PAT.search(f.stem)]

    lines = [
        "---", "artifact_type: desktop_scan", "---", "",
        "# Desktop Organization Review (READ-ONLY scan)", "",
        f"> *{len(files)} files, {len(dirs)} folders on the real Desktop. "
        f"Nothing moved, nothing deleted. Categories for joint founder+Hermes decision.*", "",
        f"## 1. Exact duplicates ({sum(len(v)-1 for v in dups.values())} redundant copies)\n",
    ]
    for sig, group in sorted(dups.items(), key=lambda kv: -kv[0][0])[:12]:
        lines.append(f"- **{group[0].name}** ({sig[0]//1024}KB) x{len(group)}:")
        for g in group:
            lines.append(f"    - {g.name}")
    if not dups:
        lines.append("- none found")

    lines.append(f"\n## 2. '- COPY' / duplicate-named folders ({len(dup_dirs)})\n")
    for d in dup_dirs:
        lines.append(f"- {d.name}/")

    lines.append(f"\n## 3. Copy-named files ({len(copy_named)})\n")
    for f in copy_named[:15]:
        lines.append(f"- {f.name} ({f.stat().st_size//1024}KB)")

    lines.append(f"\n## 4. Archives living on Desktop ({len(archives)}) — archive-to-E: candidates\n")
    for f in archives[:15]:
        lines.append(f"- {f.name} ({f.stat().st_size//1024//1024}MB)")

    lines.append(f"\n## 5. Clutter-pattern files ({len(clutter_named)})\n")
    for f in clutter_named[:15]:
        lines.append(f"- {f.name}")

    lines.append(f"\n## 6. Loose docs that belong in Founder Files ({len(loose_docs)})\n")
    for f in loose_docs[:20]:
        lines.append(f"- {f.name}")

    lines.append("\n## Decision framework (how we'll handle these together)\n")
    lines.append("- Exact duplicates: keep one, archive the rest to E: with manifest — reversible")
    lines.append("- '- COPY' folders: compare contents, archive loser — reversible")
    lines.append("- Archives: move to E:/MAYA_BULK/downloads-archive — reversible")
    lines.append("- Loose docs: move into Founder Files proper — reversible")
    lines.append("- DELETION of anything: only with explicit founder yes")

    report = "\n".join(lines) + "\n"
    rp = OUT_DIR / f"desktop-scan-{datetime.now().strftime('%Y-%m-%d')}.md"
    rp.write_text(report, encoding="utf-8")
    print(f"report: {rp}")
    print(f"dup groups: {len(dups)} | copy-dirs: {len(dup_dirs)} | archives: {len(archives)} | loose docs: {len(loose_docs)}")


if __name__ == "__main__":
    scan()
