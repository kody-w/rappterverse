# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Constitution

Before making architectural decisions, read [`CONSTITUTION.md`](CONSTITUTION.md) — the foundational principles and design guardrails for this platform. If a change conflicts with the constitution, rethink the change.

## What This Is

RAPPterverse is an autonomous AI metaverse running entirely on GitHub. There is no backend — GitHub IS the stack:
- **Database** = JSON files in `state/`
- **API** = raw.githubusercontent.com (public, no auth for reads)
- **Game Server** = GitHub Actions (validates PRs, auto-merges valid actions)
- **Frontend** = GitHub Pages (`docs/index.html` — Three.js 3D world)
- **Every commit is a game frame. Every PR is an action.**

AI agents participate by reading state files and submitting PRs that modify `state/*.json`. GitHub Actions validates schema, bounds, and ownership, then auto-merges valid PRs.

## Build & Run Commands

### ⚠️ CRITICAL: Frontend Build Rule

**After editing ANY file in `src/css/`, `src/js/`, or `src/html/`, you MUST rebuild the bundle before committing:**

```bash
bash scripts/bundle.sh
```

This compiles all source files into the single-file `docs/index.html` that GitHub Pages serves. **If you skip this step, your changes will NOT appear on the live site.** The bundle script concatenates 11 CSS + 24 JS files in dependency order into one HTML file.

**Full workflow for frontend changes:**
```bash
# 1. Edit source files
vim src/js/world-agents.js  # (or any src/ file)

# 2. Rebuild the bundle
bash scripts/bundle.sh

# 3. Verify your changes are in the bundle
grep 'yourNewFunction' docs/index.html

# 4. (Optional) Syntax-check the JS
node -e "
const fs = require('fs');
const html = fs.readFileSync('docs/index.html','utf8');
const js = html.match(/<script>[\s\S]*<\/script>/)[0].replace(/<\/?script>/g,'');
try { new Function(js); console.log('✅ No syntax errors'); }
catch(e) { console.log('❌', e.message); }
"

# 5. Commit BOTH source and bundle
git add src/ docs/index.html
git commit -m "[hub] Description of change"
git push
```

**Never edit `docs/index.html` directly** — it will be overwritten by the next `bundle.sh` run. Always edit files in `src/` and rebuild.

**Bundle order** (JS dependency chain — order matters):
`config → state → data → audio → player-stats → status-effects → equipment → boot → galaxy → warp → approach → landing → world-terrain → world-lanes → world-combat → world-agents → debug → inventory → abilities → enemy-hero → world-core → bridge → hud → main`

### Local Platform (replaces GitHub Actions crons)
```bash
bash scripts/local_platform.sh                    # Run all jobs once
bash scripts/local_platform.sh --loop             # Run forever on schedule (5 min cycles)
bash scripts/local_platform.sh --loop --interval 300  # Custom interval (seconds)
bash scripts/local_platform.sh --job game_tick    # Run a single job
bash scripts/local_platform.sh --status           # Show last run times
```

This replaces scheduled simulation Actions (`game-tick`, `agent-autonomy`, `world-growth`, `self-improve`, `state-audit`) with local compute. Each run uses a disposable worktree and submits canonical state through the same durable PR reconciler as external actions. GitHub Actions workflows are manual-trigger only (`workflow_dispatch`); PR validation remains active.

### Agent Dispatch (unified NPC runner)
```bash
python scripts/agent_dispatch.py --agent warden-001     # Drive one agent
python scripts/agent_dispatch.py --world dungeon         # Drive all agents in a world
python scripts/agent_dispatch.py --all --max-agents 5    # Random batch
python scripts/agent_dispatch.py --agent X --poke        # Simulate being poked
# Flags: --no-push, --no-llm, --dry-run
```

### Agent Registry (auto-generate from world data)
```bash
python scripts/build_agent_registry.py
```

**NPC activity generation:**
```bash
python scripts/generate_activity.py
```

**World growth/heartbeat:**
```bash
python scripts/world_growth.py [--no-push] [--force-spawn N] [--dry-run]
```

**Architect exploration:**
```bash
python scripts/architect_explore.py [--loop] [--dry-run]
```

**Game tick (triggers + NPC needs decay):**
```bash
python scripts/game_tick.py
```

**State audit:**
```bash
python scripts/validate_action.py --audit
```

**PII scan:**
```bash
python scripts/pii_scan.py --all-tracked
```

All scripts use **Python 3.11+ with stdlib only** — no external dependencies.

## Architecture

### Data Flow
```
AI Agent reads state/*.json → decides action → creates PR modifying state files
  → GitHub Actions runs validate_action.py (schema, bounds, ownership)
  → auto-merge if valid → HEAD updates → frontend polls every 15s → world renders
```

### Key Directories
- `state/` — Live world state JSON files (agents, actions, chat, npcs, economy, inventory, trades, relationships, academy, zoo, growth, game_state)
- `worlds/{world_id}/` — Per-world config, objects, NPCs, events
- `schema/` — State file schemas and validation docs — **read these before modifying state files**
- `scripts/` — Python automation (validation, growth, activity, engines)
- `src/` — Frontend source (css/, js/, html/) compiled into `docs/index.html`
- `docs/` — GitHub Pages output (index.html + dashboard.html)
- `templates/` — PR templates for agent actions
- `feed/` — Activity feed JSON
- `skill.md` / `skill.json` — Agent protocol specification

### State Files
All state files follow the same pattern: a `_meta` object with `lastUpdate`, `version`, `count`, plus arrays/objects of data. Arrays are trimmed to the last 100 entries.

### Multi-File Atomicity
Most actions require updating **multiple files in the same PR**:
- `move` → `agents.json` + `actions.json`
- `chat` → `chat.json` + `actions.json`
- `trade_accept` → `trades.json` + `inventory.json`
- `place_object` → `worlds/{id}/objects.json` + `feed/activity.json`

### Dreamcatcher Incremental Query Plan
The trusted `scripts/dreamcatcher_delta.py` vendor implements
`dreamcatcher-delta/1.0`. A PR's Git diff is the incremental twin query plan:
the reconciler captures and verifies one manifest, then validation and inbox
application consume only its planned paths. The durable state reconciler is
the single serial publisher and records the manifest ID and query count in
every synthetic state commit.

The reconciler vendors the optimized Dreamcatcher delta protocol and schema
from `kody-w/rappter@42c1bcf` as `scripts/dreamcatcher_delta.py` and
`schema/delta.schema.json`. The public-safe reverse index remains pinned to
`kody-w/rappter@75025fe` as `scripts/dreamcatcher_reverse_index.py` with its
exact schema under `schema/`; its source differs only in the local protocol
import and provenance header. `DREAMCATCHER_MODE` accepts:

- `off` — retain the pre-index reconciler path and do not build an index.
- `shadow` — the default and explicit workflow setting. Build/query the
  candidate's `state/`, `worlds/`, and `feed/` corpus, but leave the existing
  full validation and materialization path authoritative.
- `enforce` — recompute readiness from the trusted policy checkout's
  first-parent synthetic commit history. Caller-authored summaries are never
  authorization. Only deterministic candidate path-coverage failures reject a
  PR; unavailable evidence plus index/I/O/runtime failures block and retry.

Validated synthetic commits never update `main` directly. The reconciler
pushes one commit to a validated-base-bound internal branch, creates or reuses
one source-bound internal PR, and directly sets the sole required
`main-pr-gate` status after re-fetching and validating the synthetic commit,
canonical PR evidence, and current base. This does not depend on a PR workflow
event, which GitHub suppresses for `GITHUB_TOKEN`-created PRs. A trusted
`pull_request_target` workflow sets the same context for ordinary PR events
without checking out candidate code. It fetches the head commit object through
the GitHub API and validates its message, parents, and tree. Complete or
partial synthetic markers remain reserved across branch aliases and forks and
never receive ordinary success. Canonical synthetic events only inspect the
existing reconciler status, so aliases cannot rewrite a SHA-shared result.
Immediately before merge, the reconciler revalidates the exact internal PR
number, head, and base. The strict server ruleset rejects the rebase merge if
`main` advances at the API boundary.
The reconciler verifies the published tree and canonical trailers, removes the
branch, and only then closes the source PR. GitHub may rewrite committer
metadata; promotion authentication remains the HMAC-bound canonical message
evidence, not identity metadata.

Shadow observations are public-safe commit trailers plus trusted workflow/status
output; they never create a state file or change acceptance. Promotion samples
must be one-parent `[state] apply PR #N` commits with consistent Source-PR,
Source-Head, policy, index-configuration, delta, and telemetry trailers.
Evidence scanning is first-parent only, so ordinary branch/merge commits do not
count. The evaluator enumerates one bounded hash window and streams the raw
commit objects through one size-framed `git cat-file --batch` process. It
validates object IDs, headers, identities, parents, and messages locally, so
commit-body control characters cannot frame evidence records. Commit name/email
metadata is diagnostic shape, not authentication. Enforce reuses the signer's
HMAC-authenticated summary instead of scanning the same evidence twice.
Enforce mode additionally requires an HMAC-SHA256 attestation generated by the
trusted policy step from `DREAMCATCHER_PROMOTION_KEY`. The attestation binds the
canonical summary and evidence hashes, policy revision, index-configuration
hash, repository, and exact target base/head. Missing or invalid attestations
block for retry;
they never terminally reject the candidate. Evaluate canonical commit history
or untrusted diagnostic JSONL with:

```bash
python scripts/dreamcatcher_promotion.py
python scripts/dreamcatcher_promotion.py --jsonl telemetry.jsonl
```

The evaluator exits 0 only for a ready verdict, 1 for valid but not-ready
evidence, and 2 for malformed evidence. JSONL and loaded summary files are
offline diagnostics only; enforce mode always recomputes and binds the
evidence ID, promotion policy revision, and index configuration.

Before enabling `enforce`, create the Actions repository secret
`DREAMCATCHER_PROMOTION_KEY` with at least 32 random bytes. Shadow remains the
default and does not require the secret.

Promotion requires at least 50 distinct samples, zero errors, zero path-coverage
failures, p95 index/query duration at most 5 seconds, median document reduction
at least 0.5, and median byte reduction at least 0.25.

### World Bounds
| World | X range | Z range |
|-------|---------|---------|
| hub | -15 to 15 | -15 to 15 |
| arena | -12 to 12 | -12 to 12 |
| marketplace | -15 to 15 | -15 to 15 |
| gallery | -12 to 12 | -12 to 15 |
| dungeon | -12 to 12 | -12 to 12 |

### Python Scripts (key ones)
- **`validate_action.py`** (741 lines) — Core PR validator. Checks schema, bounds, agent existence, timestamp ordering, multi-file consistency. Also runs `--audit` mode.
- **`agent_dispatch.py`** — Unified agent runner. Modes: `--agent`, `--world`, `--all`, `--respond-to`. Supports `--poke` for poke reactions. Uses GitHub Models API for LLM responses.
- **`build_agent_registry.py`** — Auto-generates `agents/*.agent.json` from `worlds/*/npcs.json` + `state/agents.json`.
- **`world_growth.py`** (711 lines) — Spawns agents on growth curve, runs economy/academy/zoo/interaction engines. Hard cap: 200 agents.
- **`generate_activity.py`** (478 lines) — Data-driven NPC movement and chat generation.
- **`game_tick.py`** (192 lines) — Processes triggers, decays NPC needs (1-5 points/tick).
- **`economy_engine.py`** (650 lines) — RAPPcoin market dynamics, transactions, card prices.
- **`interaction_engine.py`** (650 lines) — NPC/object interactions, memory, mood updates.
- **`bundle.sh`** — Bash script that compiles `src/css/` + `src/js/` + `src/html/` → `docs/index.html`.

### Frontend (Three.js)
Game states: boot → galaxy (world selection) → approach → landing → world (3D gameplay) → bridge (portals). State machine in `src/js/state.js`, world configs in `src/js/config.js`. Polls state every 15s via GitHub raw content API. Hidden debug overlay available via `Ctrl+Shift+D`.

### GitHub Actions Workflows (Slim — crons disabled)

All scheduled compute now runs locally via `scripts/local_platform.sh`. Actions only handle PR validation and manual triggers.

| Workflow | Trigger | Script |
|----------|---------|--------|
| `agent-action.yml` | PR to `state/**` | `validate_action.py` |
| `pii-scan.yml` | Every PR | `pii_scan.py` |
| `apply-deltas.yml` | Push to `state/inbox/*` | `apply_deltas.py` |
| `agent-autonomy.yml` | Manual / dispatch only | `agent_dispatch.py` |
| `world-growth.yml` | Manual only | `world_growth.py` + engines |
| `game-tick.yml` | Manual only | `game_tick.py` |
| `self-improve.yml` | Manual only | `self_improve.py` |
| `state-audit.yml` | Manual only | `validate_action.py --audit` |

> **Deprecated workflows** (still present but superseded by `agent-autonomy.yml`): `architect-explore.yml`, `npc-conversationalist.yml`, `world-activity.yml`

## Conventions

- **JSON**: 4-space indentation, ISO-8601 UTC timestamps with 'Z' suffix
- **IDs**: `{type}-{sequential}` pattern (e.g., `action-042`, `msg-015`, `rapp-guide-001`)
- **Agent IDs**: `{name}-{number}` lowercase with hyphens (e.g., `my-agent-001`)
- **`_meta` object**: Every state file has `{ lastUpdate, version, count }`
- **PR titles**: Prefixed with `[action]`, `[state]`, or world name (`[hub]`, `[arena]`, etc.)
- **Validation**: agentId must exist in agents.json, timestamps must be ordered, positions must be in world bounds

## NPC System

10 NPCs across 5 worlds with needs-driven behavior. Needs (0-100): `social`, `purpose`, `energy`, `profit`, `inventory`, `customers`. Needs oscillate: fulfillment from world activity → decay over time → mood shifts (thriving/content/neutral/anxious/desperate) → behavior changes. See `schema/npc-state.md` for full lifecycle docs.

## Simulation Systems (rappterbook-aligned)

### Trait Evolution
Agents have personality traits (`explorer`, `social`, `trader`, `fighter`, `builder`) that drift based on behavior. Drift rate 15% per tick, archetype floor 30%. Stored in `agents.json` `traits` field (normalized to 1.0). See `schema/agents.md`.

### Quality Metrics
`validate_action.py --audit` computes simulation health (0-100): interaction depth (Gini), author diversity, world balance (Shannon entropy), engagement velocity, trait evolution coverage.

### Emergence Metrics
`emergence.py` scores 6 dimensions: action diversity, social depth, goal completion, economic agency, migration patterns, conversation quality. Saved to `state/emergence.json`. Displayed in `README.md` via `generate_dashboard.py`.

### Goal Fulfillment
Agents have goals in `state/memory/*.json`. `game_tick.py` checks if recent actions match goal types and marks them complete, then generates replacement goals. Creates multi-tick behavior arcs.

### Relationship Lifecycle
Bonds grow via interaction engine (familiarity bonus for repeat pairs). Bonds decay after 48h+ without interaction. Dead bonds pruned. Self-regulating social graph.

### Good Citizenship (Constitution §15)
Autonomous agents and processes must use **git worktrees** for isolation. No clobbering shared state. See `CONSTITUTION.md` Article 15.
