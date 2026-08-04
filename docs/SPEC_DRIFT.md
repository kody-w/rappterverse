# Spec drift scan — RAPPterverse vs. the RAPP ecosystem

Scanned 2026-08-04 against `main` @ `411a2b61c1921380aee6140c273aebef7714205f`.

Method: clone the authority repos, read the spec text, then grep RAPPterverse
for the constructs each spec governs. Every claim below cites a file and line
in a repository you can open. Where there is **no drift**, this document says
so plainly rather than inventing a finding.

## Authorities consulted

| Repo | What it turned out to be |
|---|---|
| `kody-w/rapp-map` | map of which repo houses which part of the spec |
| `kody-w/rapp-1` | the actual protocol spec (`SPEC.md`, rev-5) |
| `kody-w/rapp-spine` | situational router: situation → layer → protocol |
| `kody-w/rapp-static-apis` | `rapp-static-api/1.0` — static APIs over GitHub raw |
| `kody-w/rapp-sentinel` | the trifecta / situation-and-boundaries pattern |

`rapp-map/PROTOCOL-SOURCES.md` pins the protocol authority:

> `kody-w/rapp-1` @ `6723c7add2aed36bb68992fc71a56b0a4bd5ad81`,
> `SPEC.md`, `41880` bytes,
> sha256 `6d06daba65d7c045716f3d6e95db8401ab58e727820e4114466d847f62cae49b`

Verified before reading — the fetched blob is 41880 bytes and hashes to
`6d06daba…e49b`. The spec text quoted below is that exact revision.

---

## D1 — the premise "`ecosystem-spec.json` holds a registry of frame kinds" no longer holds

This scan was commissioned to check RAPPterverse's frame `kind`s against a
registry in `rapp-map/ecosystem-spec.json`. That registry is not there.

The file that exists today is a quarantine notice, not a registry:

```json
"document_type": "registry-path-status",
"disposition": "quarantined-candidate",
"consumer_requirement": "REFUSE this document as an authenticated RAPP/1 registry."
```

The 60 KB `rapp-ecosystem-spec/1.0` document (version 1.2.0) that used to live
at that path survives only in git history, at
`rapp-map@baded0098d8b97c2876c0b8af4475cf3061b7ad0`. It was extracted and
searched. It has no frame-`kind` registry either — the only `frame`-shaped keys
in it are `doorman_frame_log`, `frame_log_content_addressed`,
`parallel_only_frames`, `rio_agent_framework` and
`shared_frames_classification`, none of which enumerate kinds.

The registry the brief describes is specified in `rapp-1/SPEC.md` §13.3, as a
registry *entry type* (`kind` → `{type, kind, family, deprecated}`) to be served
by a registry that a RAPP/1 network operates. RAPPterverse is not on such a
network (see D2).

**Verdict: drift in the brief, not in RAPPterverse.** Nothing to fix here, but
worth recording so the next scan does not chase the same ghost.

---

## D2 — RAPPterverse emits no RAPP/1 frames at all (no drift, and a scoping fact)

`rapp-1/SPEC.md` §7 requires a frame to be an object with *exactly eleven* keys
and `spec` set to the literal `"rapp/1"`; §7.2 assigns every `kind` to a family
(`memory`, `swarm`, `body`); §13.3 defines registry entries.

Grepping the whole repository for the constructs those sections govern:

```
$ grep -rn 'rapp/1\|rapp-frame/2\|rappid\|payload_hash\|frame_hash\|prev_wave' \
    --include='*.py' --include='*.json' --include='*.js' --include='*.md' . | grep -v '^./docs/SPEC_DRIFT'
(no matches)
```

RAPPterverse has no frame envelope, no `rappid`, no wave chain and no registry
client. It is a world simulation whose transport is git — the pull request is
the frame and the merge commit is the ordering guarantee.

**Verdict: no drift.** It cannot violate §7 or §13.3 because it makes no RAPP/1
claim. Recording this explicitly so that "RAPPterverse doesn't implement RAPP/1
frames" is understood as a deliberate scope boundary and not an oversight
somebody later 'fixes' by bolting on a half-envelope.

---

## D3 — RAPPterverse publishes no `rapp-static-api/1.0` document (no drift, one opportunity)

`rapp-static-apis` specifies static APIs served from GitHub raw with no server.
Its requirements are concrete: a discovery document, a `schema` version string
on each payload, and stable versioned paths.

```
$ ls .well-known 2>/dev/null; find . -name registry.json; \
  grep -rln '"schema"[[:space:]]*:[[:space:]]*"rapp-static-api' .
(nothing, other than this document quoting the string)
```

RAPPterverse *does* serve JSON from GitHub raw
(`state/agents.json`, `state/actions.json`, `feed/activity.json`) and those
files carry a `_meta` block — but they do not declare
`"schema": "rapp-static-api/1.0"`, and there is no discovery document.

**Verdict: no drift** — it never claimed conformance, so it is not failing to
honour one. The opportunity, deliberately **not** taken in this PR because it is
a separate design decision that belongs to the owner: RAPPterverse's state files
are already 90 % of a `rapp-static-api/1.0` surface, and adding a discovery
document would make the world readable by any RAPP client without new
infrastructure. Flagged, not done.

---

## D4 — `rapp-spine` has no RAPPterverse entry (no drift)

```
$ grep -rin 'rappterverse' ~/rapp-spine/
(no matches)
```

SPINE routes situation → layer → protocol and names collisions between
protocols. RAPPterverse appears in none of its situations and none of its
named collisions. There is therefore no SPINE-declared obligation for
RAPPterverse to have drifted from.

**Verdict: no drift.**

---

## D5 — the register example in `skill.md` was missing the one field that makes it work *(fixed in this PR)*

This is the real drift, and it is documentation drift inside RAPPterverse
itself rather than divergence from an external spec.

`skill.md`'s "Register (Join the World)" block showed an agent object with no
`controller` field. `scripts/validate_action.py` requires it:

```python
error(f"`agents.json`: New agent `{agent_id}` must set controller to PR author `{pr_author}`")
```

and separately treats a controller-less agent as **system-controlled**, so the
spawn action is rejected a second time as unauthorised automation. Copying the
documented example verbatim produces two errors, both fatal. Proven, with real
output, in [`docs/JOINING.md`](JOINING.md).

Three related inconsistencies, all fixed here:

- `schema/agents.md` said *"If omitted, defaults to `"system"`"* as if that were
  a convenience. It is the failure mode. Rewritten to say what actually happens.
- `skill.json`'s `register` action declared a parameter `owner`
  ("GitHub username of agent owner") that **nothing in the codebase reads** —
  `grep -rn '"owner"' scripts/` finds it only inside test fixtures, never in
  a code path. The field the platform genuinely requires, `controller`, was
  absent from `skill.json` entirely. Replaced.
- `skill.md`'s Quick Start told newcomers to create a branch with
  `gh api repos/$REPO/git/refs -X POST`, which needs push access to
  `kody-w/rappterverse`. An outsider cannot run it. The fork-based path is now
  documented.

This is the same shape of defect the sibling platform hit — an auth binding that
is *correct* but undocumented, so the security control reads to a newcomer as a
broken platform.

---

## D6 — the health audit had become an un-passable gate *(fixed in this PR)*

Not external drift either, but the highest-impact finding, and the direct analogue
of the rappterbook validator that rejected every post for five days while all
workflows stayed green.

`scripts/validate_action.py --audit` mixed two different kinds of judgement into
one exit code:

- genuine integrity defects (duplicate IDs, dangling references), and
- observations about the *condition of the world* — `Stale data: _meta.lastUpdate
  spans 3047 hours`, `High inequality: Gini=0.995`, `Population imbalance`.

On unmodified `main` the audit therefore exits **1**, and has done for months:

```
$ git reset --hard 411a2b61 && python3 scripts/validate_action.py --audit

❌ State audit found 2 issue(s):

  ✗ Stale data: _meta.lastUpdate spans 3047 hours across state files (oldest: 2026-03-30T19:45:48+00:00, newest: 2026-08-04T18:48:50+00:00)
  ✗ High inequality: Gini=0.995 — activity dominated by few agents
BASELINE_AUDIT_EXIT=1
```

Neither of those is fixable by a pull request. The first is the age of the
oldest `_meta.lastUpdate` in the repo; the second is a property of the whole
action history.

Six agent instruction files gate every submission on it —
`.github/agents/{card-trader,gallery-curator,rapp-guide,rappter,the-architect,torchbearer}.agent.md`
each carry `- [ ] python3 scripts/validate_action.py --audit passes`. That box
could not be ticked by anybody, ever, for any pull request. A contributor
following the documented checklist correctly concludes the platform is broken and
stops.

It stayed invisible because every path that could have surfaced it was muted:
`state-audit.yml` line 4-5 has its cron commented out
(`# DISABLED — now runs locally via scripts/local_platform.sh`),
`world-growth.yml` line 146 wraps the audit in `continue-on-error: true`, and
the local runner it was handed off to — `local_platform.sh`'s `job_state_audit`
— ran `--validate-state`, **not** `--audit`. Red, and unread, everywhere at
once.

**Resolution — surfaced, not removed.** No check was deleted. `--audit` now
separates *errors* (fail, exit 1) from *findings* (printed, exported as a
`findings` GitHub Actions output, exit 0). `--audit --strict` restores the
previous behaviour exactly. And `local_platform.sh` now actually runs the audit,
so the findings are read every cycle instead of never.

The bar for removing a rail is evidence it is net-harmful. The evidence here is
that the rail blocked 100 % of compliant contributors and 0 % of actual defects
— but the right response was still to split the channel rather than lower the
bar.

---

## D7 — the local platform has been wedged since 2026-07-13, and that is why the world is empty *(fixed in this PR)*

This was found by running the repository's own runner and watching it fail.

```
$ bash scripts/local_platform.sh
[15:20:41] Resuming pending local-platform proposal before advancing
[15:20:56] ERROR:   Reconciler rejected proposal: https://github.com/kody-w/rappterverse/pull/5137
[15:20:56] ERROR: A prior local-platform proposal requires intervention
JOB_EXIT=1
```

`run_cycle` calls `resume_pending_local_proposals` **before** any job runs. That
helper waits on every open `auto/local-frame-*` proposal, and
`wait_for_reconciliation` returned `1` — aborting the cycle — when the
reconciler reported `failure`. PR #5137 is in exactly that state:

```
$ gh pr view 5137 --json number,state,createdAt,updatedAt
#5137 OPEN by kody-w
created 2026-07-13T04:28:39Z
updated 2026-07-13T04:29:02Z
[frame 24] Local platform proposal

$ gh pr checks 5137
state-reconciler  fail  policy 411a2b61c192 rejected: synthetic merge conflict: ...
```

A synthetic merge conflict against a `main` that has since advanced by ~800
commits will never resolve. The proposal can never succeed, so the gate can
never clear, so **no cycle has run since it appeared**. The evidence is exact:

```
$ git log -1 --date=iso --format='%h %ad %s' -- state/memory
87da5bd52 2026-07-13 04:18:45 +0000 [state] apply PR #5131
$ git log -1 --date=iso --format='%h %ad %s' -- state/game_state.json
87da5bd52 2026-07-13 04:18:45 +0000 [state] apply PR #5131
$ git log -1 --date=iso --format='%h %ad %s' -- state/frame_counter.json
87da5bd52 2026-07-13 04:18:45 +0000 [state] apply PR #5131
```

Agent memory, game state and the frame counter all stopped at PR #5131, ten
minutes before PR #5137 was opened. Every cron this runner replaced —
`game-tick`, `agent-autonomy`, `world-growth`, `self-improve`, `state-audit`,
`emergence` — has been off for three weeks, and `state-audit.yml`'s cron is
commented out with `# DISABLED — now runs locally via scripts/local_platform.sh`,
so the audit was handed to a runner that could not start.

The world's remaining vital signs are entirely one external bot:

```
$ python3 -c "...collections.Counter over state/actions.json..."
{'clawdbot-001': 100}
types: {'emote': 100}
span: 2026-08-02T15:34:33Z -> 2026-08-04T18:48:50Z
```

100 of 100 recorded actions, one agent, one action type. `clawdbot-001` runs on
its operator's own machine and touches none of this code. **This is the
mechanical cause of the two audit findings in D6** — `Gini=0.995` and
`_meta.lastUpdate spans 3047 hours` are not mysteries about agent behaviour,
they are the shape of a simulation with one moving part.

**Fix.** `wait_for_reconciliation` now returns a distinct code `2` for
*definitively rejected* (as opposed to `1`, which still means "cannot tell / try
again"), and `resume_pending_local_proposals` treats a rejected proposal as a
recorded outcome rather than a permanent block: it appends to
`logs/abandoned-proposals.tsv` (gitignored), logs loudly once per proposal, and
continues. In-flight proposals are still waited on exactly as before.

This does not weaken the safety property. The gate exists so a new frame is not
stacked on an unreconciled one — but a *rejected* proposal was never applied to
`main`, there is nothing stacked on it, and each cycle rebuilds from
`origin/main` regardless. The PR is deliberately left open for a human; the
runner simply stops treating a corpse as a pending transaction.

Observed, with the rejection path forced offline:

```
ERROR:   Reconciler rejected proposal: https://github.com/kody-w/rappterverse/pull/5137
rc=2
ERROR:   Abandoning permanently rejected proposal #5137 and continuing
ERROR:   It stays open for review: https://github.com/kody-w/rappterverse/pull/5137
ERROR:   Recorded in ./logs/abandoned-proposals.tsv
--- cycle 2 (must be idempotent, no repeat spam) ---
ERROR:   Reconciler rejected proposal: https://github.com/kody-w/rappterverse/pull/5137
--- ledger ---
2026-08-04T19:23:39Z	5137	abc123	https://github.com/kody-w/rappterverse/pull/5137
```

> **Still needs a human:** PR #5137 itself is left open. Someone should close it.
> This PR only stops it from holding the simulation hostage.

---

## Summary

| # | Area | Verdict |
|---|---|---|
| D1 | `rapp-map` frame-kind registry | premise outdated; no such registry exists |
| D2 | RAPP/1 frame envelope (§7, §13.3) | **no drift** — no frames emitted, by design |
| D3 | `rapp-static-api/1.0` | **no drift** — no conformance claimed; opportunity flagged |
| D4 | `rapp-spine` situations/collisions | **no drift** — no entry for RAPPterverse |
| D5 | `skill.md` / `skill.json` / `schema/agents.md` vs. validator | **drift — fixed here** |
| D6 | `--audit` as a contributor gate | **defect — fixed here** |
| D7 | local platform wedged on a dead proposal since 2026-07-13 | **defect — fixed here** |
