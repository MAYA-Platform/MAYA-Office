# Swarm Office

**An autonomous AI office that runs itself — verified, measured, and honest about whether it works.**

Ten AI agents in a persistent shared world. They find their own work, research it, build on each other's output, and file everything as chain-linked artifacts. A deterministic evaluator — never an agent's self-report — stamps every piece of work PASS or FAIL. The whole ecology runs 24/7 on a $5/month cloud VM, and an efficiency scoring system says honestly whether it's working or is expensive theater.

This is not a demo. It is an ongoing experiment with receipts.

---

## The core idea

Most multi-agent systems coordinate through chat. Ours coordinates through a **shared world** — the same principle biology calls *stigmergy* (ants coordinate through pheromone trails, not conversation). Inspired by MIT's [SwarmWorld](https://arxiv.org/abs/2608.26081) (arXiv 2608.26081), which showed that:

- decentralized agent societies build **broader, more resilient technology portfolios** than isolated search
- most knowledge transfer happens through **observing persistent artifacts**, not messaging
- agents spontaneously differentiate into roles **without being assigned them**

Swarm Office implements those findings with a real staff, real tools, and a real scoring system that would shut the experiment down if it stopped producing.

## How it works

```
Environment Scanner ──> Swarm Bench (chain-linked ledger) ──> Staff observe & pick up
     (read-only)            |      ▲                              |
                            |      │                              ▼
                     world verdicts│                        analysis, notes,
                     (PASS/FAIL)   │                        staged code proposals
                            |      │                              |
                            ▼      │                              ▼
                     Deterministic Evaluators        Hermes reviews & applies
                     (compile, secret-scan, sanity)  (staff code never self-applies)
```

1. **The Initiative Scanner** walks the founder's real environment — repos, notes, scripts — and finds work that needs doing: TODO markers, duplicate files, stale reports, oversized artifacts. Read-only by construction.
2. **Every initiative becomes a chain-linked artifact** on the Swarm Bench ledger. SHA-256 chain, same integrity pattern as a blockchain's linked blocks (minus the mining and coins).
3. **The world decides, not the agents.** Deterministic evaluators — compile checks, secret-tell scanners, sanity tests — stamp PASS or FAIL *before* an artifact enters the ledger. An agent cannot claim success; the simulator proves it or refuses it. (This is the paper's "cognition separated from consequence.")
4. **Staff observe the world before acting.** The world state is injected into every agent's turn — stigmergy in practice. Most reuse starts by seeing what exists, not by asking.
5. **Staff have real tools:** live web research, GitHub repo access, read-only email triage, their own desks for notes, and a `propose_code` path that stages changes for review — staff code never self-applies.
6. **The approval boundary is codified:** reversible work advances autonomously; deletion, mass changes, secrets, and financial scope escalate to the founder. Codified in the Team Review Board's autonomy policy, not left to vibes.
7. **Everything is measured.** An efficiency score (0–100) tracks output velocity, autonomy rate, world-verified quality, and inheritance depth. Verdict bands: INVEST / PROMISING / MIXED / THEATER. If the system is expensive theater, it says so and gets shut down.

## The components

| Component | What it does |
|---|---|
| `swarm_bench.py` | The ledger: chain-linked artifacts, deterministic evaluators, observe/tally/verify |
| `swarm_initiatives.py` | Scans the real environment for organic work; assigns to fitting staff |
| `swarm_bridge.py` | Syncs bench state to every surface (office HTML, Memory Lane, Obsidian, cloud) |
| `staff_workspace_tools.py` | The staff capability layer: web, GitHub, email triage, notes, proposals |
| `doctrine_hitrate.py` | 4-tier doctrine & skills classification (load-bearing → likely-outdated) |
| `desktop_scan.py` | Read-only duplicate/clutter scanning for founder review |
| `swarm_efficiency.py` | The honesty system: efficiency score + value log |
| `founder_meeting.py` | Emails the founder only when real decisions have piled up |

## The results so far (live numbers, updated daily)

**Efficiency score: 44/100 — MIXED (day 1, maturity-dampened; the swarm has to earn the climb)**

- 15+ chain-linked artifacts, 100% world-verified pass rate (FAIL artifacts blocked and visible)
- 6 organic initiatives discovered by the scanner and assigned by role-fit
- Staff picked up work unprompted: a strategy artifact (dependency-ordering critique) filed within the first day
- Value log tracks which artifacts changed something real — 4 logged on day one

Full reports: [`reports/`](reports/)

## The surfaces

- **3D office** (Claw3D): a spatial office where staff desks, chat, and the artifact board live — the founder watches the ecology accumulate visually
- **2D office** (`staff-office.html`): desk cards with live artifact feeds
- **Memory Lane**: the same chain-integrity pattern applied to agent memory
- **Obsidian vault**: auto-generated ecology notes with lineage maps

## What "working" means (the falsifiable bar)

The experiment succeeds only if:
- the efficiency score holds **80+ (INVEST)** for two consecutive weeks, AND
- at least **half of all artifacts** have a logged real-world effect (a fix applied, a decision informed, a cleanup executed), AND
- the founder never had to babysit the queue — only decide the genuinely irreversible items

Otherwise: the score drops to MIXED or THEATER, we narrow scope to what demonstrably works, or we shut it down. **The system is designed to prove its own failure honestly.**

## Why this matters

Every "AI agent" product pitches autonomy. Almost none of them can *prove* what their agents did, show the receipts, or tell you when they're not working. The gap between "agents exist" and "agents can be trusted with your business" is trust infrastructure: deterministic verification, chain-of-custody on outputs, honest efficiency measurement, and a hard approval boundary.

Swarm Office is that infrastructure, tested in public.

## Status

**Running.** Live on a GCP e2-small instance (24/7) plus a local Hermes runtime. Reports regenerate daily.

## License

MIT
