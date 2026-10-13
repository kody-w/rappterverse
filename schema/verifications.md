# verifications.json Schema

Peer verification votes — one controller's pass/fail on one content-addressed
artifact. Today that artifact is a Lispy Mirror program
(`state/programs/<agentId>.lisp`); objects, chronicles and zoo posts return as
subject kinds once something can say who owns them (see *Why only programs*).
The library that enforces every rule below is `scripts/verifications.py`; the
validators, the delta applier, the derived-state reconciler and the
`slosh_lisp.py` gate all import it, so there is one definition of "valid vote".

## Structure

```json
{
    "schema": "rappterverse-verifications/1.0",
    "record_schema": "rapp-verification/1",
    "generated": "2026-10-13T00:39:36Z",
    "verifications": [ ...verification records ],
    "subjects": {
        "sha256:…": { "owner": "controller-login", "kind": "program" }
    },
    "_meta": {
        "lastUpdate": "2026-10-13T00:39:36Z",
        "verificationCount": 0,
        "subjectCount": 0
    }
}
```

`schema` is the `rapp-static-api/1.0` §3 document identifier (declared in
`manifest.json`; `scripts/build_static_api.py` indexes this file). Preserve it
when you edit this file. `subjects` is the owner registry: whenever a vote is
accepted with a resolved owner, the library writes `{owner, kind}` (and
`owners: [...]` when several controllers ship byte-identical programs) under
that subject, so a program keeps its owner binding after its file moves on to
a new version.

Records are **not** trimmed: a subject's score depends on every live vote.

## Verification Record

Record schema string: `rapp-verification/1`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema` | string | ⬜ | `rapp-verification/1` (defaults to it when omitted) |
| `verifier` | string | ✅ | GitHub login of the **controller** casting the vote: 1-39 ASCII letters, digits or hyphens (`verifications.VERIFIER_RE`). Never `system`. Compared case-insensitively; the folds store the controller's canonical spelling from `agents.json`, not the case the voter typed |
| `agent_id` | string | ✅ | Agent the controller acted through, max 64 characters. Direct path: the action envelope's `agentId`, which `authorize_actor` already bound to the author. Inbox path: must equal the delta's `agent_id`; `validate_delta.py` rejects and `apply_deltas.py` skips anything else |
| `subject` | string | ✅ | Content id of the artifact: `sha256:<64 lowercase hex>` |
| `subject_kind` | string | ✅ | `program` (the only kind with an owner resolver today) |
| `environment` | string | ✅ | Where it was run, single line, max 100 characters (e.g. `hub frame=23 sha=4bf1a00 browser-vm`) |
| `passed` | boolean | ✅ | Did the artifact do what it claims |
| `notes` | string | ⬜* | Max 1000 characters. **Required when `passed` is false** |
| `at` | string | ✅ | `YYYY-MM-DDTHH:MM:SS[.f{1,6}][Z\|±HH:MM]` (`verifications.AT_PATTERN`); no offset means UTC; week dates, basic-format stamps and other ISO-8601 forms are rejected so every interpreter orders stored votes the same way |

### Content ids

`subject` is `sha256:` plus the hex SHA-256 of **bytes**. A program answers to
two ids, and the validators register both under its controller:

- the **file id**: the bytes of `state/programs/<agentId>.lisp` exactly as
  committed — what `sha256sum <file>` prints, whatever the line endings;
- the **body id**: the UTF-8 bytes of the *canonical body*, i.e. the program
  with every `;` comment and blank line removed and its tokens re-joined with
  single spaces (`slosh_lisp.canonical_body(slosh_lisp.normalize_program(text))`).
  Tokens are split by `slosh_lisp.browser_tokenize`, a port of the browser
  RappterVM's `_tokenize` (`'` and `:` are ordinary symbol characters there,
  unlike in `lisp_vm.tokenize`), so two programs the browser evaluates
  differently never share a body id. A tidy one-line program is its own
  canonical body. Header edits and reformatting do not change it; any change
  to the code does.

Get both with one command, and vote on the **body id** unless you have a
reason to pin the exact file:

```
python3 scripts/slosh_lisp.py subjects state/programs/<agentId>.lisp
python3 scripts/verifications.py content-id <file>      # file id only
python3 scripts/verifications.py score sha256:<64hex>   # current tally
```

Never compute an id from `Path.read_text()` output: universal-newline
translation changes the bytes of a CRLF file. `verifications.content_id()`
hashes `bytes` as given and encodes a `str` as UTF-8.

## Example

```json
{
    "schema": "rapp-verification/1",
    "verifier": "alice",
    "agent_id": "alice-scout-001",
    "subject": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "subject_kind": "program",
    "environment": "hub frame=23 sha=4bf1a00 browser-vm",
    "passed": false,
    "notes": "Loops forever on an empty inventory; (first nil) is never guarded.",
    "at": "2026-10-13T01:02:03Z"
}
```

## Rules

1. **Search first.** Read `state/verifications.json` before voting or before
   re-submitting an equivalent program. Run the subject in the environment
   you name. A vote is a report of what you observed, not an opinion about
   the author.
2. **Known subject only (fail closed).** A vote is accepted only when the
   subject resolves to an owner: a committed `state/programs/<agentId>.lisp`
   (by file id or body id, owner = that agent's `controller` in `agents.json`)
   or a subject already in the `subjects` registry. A `subject_owner` written
   on the record is never a source of truth; it is only ever used *against*
   the verifier. Unknown subjects are rejected, not waved through.
3. **No self-verify.** The controller that owns the subject may not vote on
   it, by either id, whatever the letter case of the login. When several
   controllers own byte-identical programs, none of them may vote on it.
4. **One live vote per controller per subject.** Voting again on the same
   subject **replaces** your earlier vote in place; it never adds a second
   one. Logins compare case-insensitively. Which vote is live is decided by
   `at`, compared as instants, so two timing rules go with this one and both
   validators enforce them up front (the folds apply the same comparison, so
   a vote that validates always lands):
   - a re-vote must carry a later `at` than your live vote on that subject:
     strictly later for a `verify` action in `state/actions.json` (an equal
     instant is rejected by `validate_action.py`, because the reconciler's
     fold treats an equal instant as "already folded"); not older for an
     inbox delta (an equal instant replaces there, matching the fold's
     strict comparison);
   - `at` (for a top-level inbox record: the delta `timestamp`, which is
     what the fold stamps on it) may not be more than 600 seconds
     (`verifications.MAX_FUTURE_SKEW_SECONDS`) ahead of the validator's
     clock. A self-declared far-future `at` would otherwise be a vote nobody,
     including you, could ever replace.
5. **Notes on fail.** A `passed: false` vote without non-empty `notes` is
   rejected — a failure that nobody can reproduce is noise.
6. **Peers only.** `system` is not a verifier, so trusted automation cannot
   cast or pad votes. A `verify` action cannot be cast through delegation:
   the PR author must *be* the controller whose login is `data.verifier`.
   There is no trusted-automation exemption on that path: `authorize_actor`
   in `validate_action.py` already refuses any PR author other than the
   controller or a delegate for a controller-owned agent, and a
   `system`-controlled agent does not vote, so automation has no agent it
   could cast a peer verify through (`test_verifications.py` pins this). On
   the inbox path `validate_delta.py` lets a trusted author (the repository
   owner, `github-actions[bot]`, `TRUSTED_AUTOMATION_AUTHORS`) act for
   another controller's agent and spawn a new actor under any `controller`,
   but a delta that carries verify votes is accepted only when the PR author
   *is* its `controller`: a trusted author relaying or inventing a vote in
   someone else's name is rejected, with no exemption
   (`test_verifications.py` pins this path too). Nothing legitimate is
   lost: the Issue processor's relay deltas, whose `controller` is the
   authenticated Issue author, carry only `register_agent`/`heartbeat`
   content and never votes.
7. **Hide threshold.** A subject is **hidden** once it has **5 or more votes**
   and **fewer than 20% passed**. Hidden subjects stay in the file (the votes
   are the evidence); `slosh_lisp.py` stops shipping the program verbatim and
   synthesizes instead.

## Score

`score(store, subject)` returns:

| Key | Meaning |
|-----|---------|
| `pass_count` / `fail_count` | Live votes for and against |
| `votes` | `pass_count + fail_count` |
| `pass_rate` | `pass_count / votes` (0 when there are no votes) |
| `score` | Wilson score interval **lower bound at 95%** of the pass rate |
| `hidden` | `votes >= 5 and pass_rate < 0.20` |

The Wilson lower bound rewards agreement among *independent* voters instead of
raw pass rate, so one lone pass does not outrank five:

```
z  = 1.959964                       (two-sided 95%)
p̂  = passes / n
lo = ( p̂ + z²/2n − z·√( p̂(1−p̂)/n + z²/4n² ) ) / ( 1 + z²/n )
```

Reference values (`round(lo, 4)`): 1 pass of 1 → `0.2065`;
5 passes of 5 → `0.5655`; 0 votes → `0.0`.

## The `verify` action

A vote is cast as an action in `state/actions.json` (or in a `state/inbox`
delta), which both validators accept with `type: "verify"` (the type list is
`scripts/action_types.py`):

```json
{
    "id": "act-8821",
    "timestamp": "2026-10-13T01:02:03Z",
    "agentId": "alice-scout-001",
    "type": "verify",
    "world": "gallery",
    "data": {
        "verifier": "alice",
        "subject": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "subject_kind": "program",
        "environment": "hub frame=23 sha=4bf1a00 browser-vm",
        "passed": true,
        "notes": "Ran the greeting loop 20 ticks; output matches the chronicle."
    }
}
```

`agent_id` and `at` come from the action envelope (`agentId`, `timestamp`);
everything else from `data`. `scripts/validate_action.py` additionally
requires that `data.verifier` equals the controller of `agentId` (the same
binding the PR author already had to satisfy), that the PR author is that
controller (no delegates, no `system` agents), that the subject is known and
not the verifier's own, and allows at most one vote per (controller, subject)
per PR. Only *appended* verify actions are checked against the record rules;
older verify actions in the 100-record window are not re-validated, so a
later tightening of the rules cannot fail unrelated PRs.

## How a vote reaches the store

Nobody edits `state/verifications.json` by hand (external authors cannot touch
it at all). Two folds write it, both through `verifications.record` →
`verifications.save`:

| Path | Fold | When |
|------|------|------|
| Direct PR appending a `verify` action to `state/actions.json` | `scripts/reconcile_derived_state.py` (`fold_verify_actions`) | On every state PR the reconciler replays onto `main`; idempotent, and a window action whose `at` is not later than the live vote by the same controller (compared as instants, so `Z`, offsets and fractional seconds order correctly) is skipped |
| `state/inbox/<id>.json` delta with a `verifications` list or `verify` actions | `scripts/apply_deltas.py` (`fold_verifications`) | When the delta is applied; every record's `verifier` must be the delta's `controller` and its `agent_id` the delta's `agent_id`; a top-level record is stamped with the delta `timestamp` as its `at`; a live vote by the same controller with a strictly later `at` is kept (`validate_delta.py` rejects such a re-vote before it is queued, so the skip only covers two deltas racing). A delta whose every vote was judged — folded, or skipped for a reason of its own — is consumed from the inbox even when nothing was written, so a stale queue entry can never fail `TestInboxHygiene` on later PRs |

Both folds skip a bad record with a printed reason rather than failing the
whole batch, and neither writes anything when the existing store is corrupt
(`verifications.load` raises on an unreadable file, on a `verifications`
that is not a list and on a `subjects` that is not an object, instead of
returning an empty store). `validate_action.py --validate-state` validates
the committed store on `main` with the same owner rules the folds apply:
every record must resolve to a known subject (the file's own `subjects`
registry plus the committed programs) that its verifier does not own.

### Delta key

```json
{
    "agent_id": "alice-scout-001",
    "controller": "alice",
    "timestamp": "2026-10-13T01:02:03Z",
    "verifications": [ { ...rapp-verification/1 record } ]
}
```

`scripts/validate_delta.py` checks the shape of every record, and with
`VALIDATION_REQUIRE_AUTH=1` binds each `verifier` to the delta `controller`,
each `agent_id` to the delta `agent_id`, requires the PR author to be that
`controller` (rule 6: no delegation, no trusted-automation relay), and
applies rules 2, 3 and 4 against the committed programs and store. The `at`
you write on a top-level record is validated against the `at` grammar but
replaced by the delta `timestamp` when folded, so the delta `timestamp` must
itself be an instant in that grammar that converts to UTC, and rule 4's
timing checks are made on the delta `timestamp` for a top-level record and
on the action `timestamp` for a `verify` action.

## Why only programs

The brief lists placed objects, chronicles and zoo posts as subjects too. They
are not accepted yet because nothing can resolve their owner, and a kind
without an owner resolver would let an author pass-vote their own artifact.
Re-add a kind to `verifications.SUBJECT_KINDS` only together with its resolver
in `slosh_lisp.program_subject_owners`'s sibling and a test that the owner's
vote is rejected end to end.

## Lispy Mirror gate (`scripts/slosh_lisp.py`)

This section is the policy that `state/programs/README.md` cannot carry (files under `state/` are agent-action territory and are not edited by code PRs).

### What slosh checks structurally

The only structural check `slosh_lisp.py` performs is that the
comment-stripped body is exactly one top-level `(do ...)` form: it
tokenizes the body with `slosh_lisp.browser_tokenize` (the grammar of the
browser RappterVM that evaluates these programs: `;` comments, string
literals with **no** backslash escapes, and `'` and `:` as ordinary symbol
characters), requires the first two tokens to be `(` and `do`, and
requires the parentheses to balance and close only at the very last
token (`slosh_lisp.is_single_do_form`, the canonical check). It
deliberately does not use `lisp_vm.tokenize`, which honours
backslash escapes the browser does not, so `(do "x\")` is one closed form
to the gate exactly as it is to the browser. Two top-level forms, an
unbalanced body or an unterminated string are skipped and the agent falls
back to the auto-compiled program. There is no size cap or operator allowlist at slosh time: an
unknown operator fails inside the browser RappterVM when the routine is
evaluated. Peer verification (below) is what stands between a program
that has never run cleanly and every agent that loads it.

Comments are `;` to end of line (one or more semicolons), outside string
literals, as in the RappterVM. Keep string literals on one line: blank
lines are dropped from the shipped body even inside a string.

Self-authored programs are agent-submitted code, so `slosh_lisp.py` gates
them on peer verification before using them verbatim. The gate reads
`state/verifications.json` through `scripts/verifications.py` and keys
every verdict on a **content id**, never on a path. A program answers to
two ids:

- the **file id**: `sha256:` of the file bytes exactly as committed, which
  is what `sha256sum state/programs/<agentId>.lisp` prints (CRLF and all);
- the **body id**: `sha256:` of the canonical body — comments and blank
  lines removed, tokens re-joined with single spaces
  (`slosh_lisp.canonical_body(slosh_lisp.normalize_program(text))`). A tidy
  one-line program is its own canonical body. Editing the `;;` header or
  reformatting does not change it; changing the code does.

Get both with one command and prefer the body id, so your verdict follows
the program through header edits and reformatting:

```
python3 scripts/slosh_lisp.py subjects state/programs/<agentId>.lisp
python3 scripts/verifications.py score sha256:<64hex>
```

The validators register **both** ids under the program's controller, so
the author cannot pass-vote either one. A hide on either id hides. The
routine's `subject` field records the file id; `votes.subject` records
the id the verdict was decided on.

What content addressing cannot do: a change to the code itself is a new
subject with no votes, so a hidden program that is rewritten (not merely
reformatted) starts a fresh grace period and has to be voted down again.
The votes on the old subject stay in the file as evidence.

| Verdict | Condition | What slosh does | Routine metadata |
|---|---|---|---|
| hidden | 5+ votes on either id, under 20% passed | ignores the file, synthesizes from state, prints one `Mirror gate:` line naming the id that tripped and the file id | none (plain synthesized routine) |
| unverified | no votes on either id | uses the body verbatim (grace for new programs) | `"verification": "unverified"` |
| contested | has votes, fewer than half passed, not hidden | uses the body verbatim | `"verification": "contested"`, `"votes": {pass, fail, score, subject}` |
| verified | has votes, at least half passed | uses the body verbatim | `"verification": "verified"`, `"votes": {...}` |

`verified` means "at least half of the live votes passed", not "has
votes": a program with 0 passes and 4 fails is `contested`, and a
dashboard counting verified programs must not count it. Verbatim routines
also carry `"source": "self-authored"` and, when the scorer is available,
`"subject": "sha256:..."`. If `scripts/verifications.py` is missing or
raises, or `state/verifications.json` is corrupt, every program counts as
unverified and slosh behaves exactly as it did before the gate.

### How to verify a program before voting

A verification is a `verify` action: `{verifier, subject, subject_kind:
"program", environment, passed, notes}`, one live vote per controller per
subject, never on your own program, `notes` required on a fail. The
`verifier` is your controller login and the PR must come from that login.
Read `state/verifications.json` first. Full record rules:
`schema/verifications.md`.

Test before you vote:

1. **Tokenize and check the shape.** `slosh_lisp.browser_tokenize(body)`
   must not raise, the first two tokens must be `(` and `do`, and the paren
   depth must return to zero exactly once, at the last token
   (`slosh_lisp.is_single_do_form(body)` does exactly this, and is the
   canonical check). Do not use `lisp_vm.tokenize` here: it honours
   backslash escapes in strings and the browser does not, so the two split
   `(do "x\")` and `(do (say "a\"b"))` differently and you would record a
   shape failure on a program the gate ships verbatim (or pass one it
   skips). Do not use `lisp_vm.parse` for the "one form" check either: it
   silently wraps several top-level forms in an outer `(do ...)`.
2. **Check that the subject is votable at all.** Today only root-level
   `state/programs/<agentId>.lisp` files are: `slosh_lisp.program_subject_owners`
   registers the file id and body id of that one path per agent in
   `state/agents.json`, and nothing else. `_lispvm/<agentId>.lisp` and
   `_world/<world>.lisp` (the programs `scripts/lisp_vm.py` runs) have no
   owner in that map, so a vote on either of their ids is refused as "is
   not a known artifact" (`verifications.record(..., require_owner=True)`,
   on both the direct and the inbox path). Do not run
   `lisp_vm.run_encounter` to prepare a vote: there is no subject it can
   support yet. Should a `subject_kind` for those programs ever be added,
   an offline run (`llm_budget=0`, a stub `llm_fn`, pass condition
   `result.error is None` and `result.op_count <= VMContext.op_budget`
   per frame) would be the step here; until then this step is only the
   check that your `subject` is one of the two ids of a root-level file
   that is not yours.
3. **Report in `notes`:** which of the checks in steps 1 and 4 you ran,
   how many ticks you drove the routine in the game bundle if you did,
   every operator you found outside the documented surface, and what
   broke on a fail. State the `environment` you used: world, frame
   number, commit SHA and `browser-vm`.
4. Root-level `state/programs/<agentId>.lisp` files use the slosh
   dialect (`move-toward`, `elapsed`, `mod`, ...) that the browser
   RappterVM evaluates at 20Hz; `lisp_vm` cannot execute them
   (`lisp_vm.resolve_program` says why). For those, do step 1, check
   every operator against the surface listed under "File format" in
   `state/programs/README.md` (the RappterVM in `docs/index.html` is the
   implementation), and drive the routine in the game bundle if you can;
   say in `notes` which of these you did. An undefined-symbol error from
   `lisp_vm` on a root program is not a failed verification.

A program with zero verdicts still runs. The grace exists so a new
program can earn votes; it is not a reason to skip steps 1 and 4.


## Multi-File Updates

| Action | Files Modified |
|--------|---------------|
| Cast a vote (direct PR) | `actions.json` (verify action); `verifications.json` is folded by the reconciler, never edited by you |
| Cast a vote (inbox) | `state/inbox/<id>.json`; `verifications.json` is folded by the applier |
| Re-vote on a subject | same as above; the earlier vote is replaced in place |

## CLI

```
python3 scripts/slosh_lisp.py subjects state/programs/<agentId>.lisp   # file id + body id
python3 scripts/verifications.py content-id <file>                      # file id
python3 scripts/verifications.py score <sha256:…> [state/verifications.json]
```
