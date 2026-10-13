#!/usr/bin/env python3
"""Peer verification primitive for RAPPterverse (record shape ``rapp-verification/1``).

A verification is one controller's pass/fail vote on one content-addressed
artifact. Today the only artifact kind with an owner resolver is a Lispy
Mirror program (``state/programs/<agentId>.lisp``); objects, chronicles and
zoo posts return as ``SUBJECT_KINDS`` entries once something can say who owns
them. Votes live in ``state/verifications.json``; the score for a subject is a
confidence-weighted pass rate (Wilson lower bound at 95%), and a subject is
*hidden* once five or more controllers have voted and fewer than 20% passed.

Rules enforced here, so every caller (validator, delta applier, reconciler,
slosh gate, CLI) agrees:

- one live vote per ``verifier`` (a controller GitHub login, compared
  case-insensitively like GitHub does) per ``subject`` — a re-vote replaces
  the earlier one in place;
- no self-verify — a controller that owns the subject may not vote on it;
- the subject's owner must be *known* when the caller says so
  (``require_owner=True``): a vote on an artifact nobody can attribute is
  refused, never waved through;
- ``system`` is not a verifier: trusted automation does not cast peer votes;
- ``notes`` are required when ``passed`` is false;
- ``subject`` is a ``sha256:<64 hex>`` content id, the same shape
  ``scripts/dreamcatcher_promotion.py`` uses, so a vote survives file moves.

Public surface (keep it this small; both repos vendor it):

    content_id(data) -> str                 # bytes hashed as-is, str as UTF-8
    load(path=None) -> dict                 # missing -> empty; corrupt -> ValueError
    record(store, rec, subject_owner=None, *, subject_owners=None,
           require_owner=False) -> dict
    record_from_action(action) -> dict      # verify action -> record
    find_vote(store, verifier, subject) -> dict | None
    parse_at(value) -> datetime | None     # aware UTC instant of an ``at``
    supersedes(existing_at, new_at) -> bool # existing vote is at least as new
    too_far_in_future(value, now=None) -> bool  # beyond MAX_FUTURE_SKEW_SECONDS
    score(store, subject) -> dict
    is_hidden(store, subject) -> bool
    save(store, path, timestamp=None)

Python 3.9+, stdlib only (repo constraint — no ``pip install``).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(
    os.environ.get("RAPPTERVERSE_REPO_ROOT", Path(__file__).resolve().parent.parent)
).resolve()
DEFAULT_PATH = ROOT / "state" / "verifications.json"

# Document schema: what the served state file carries as its first key, in the
# ``rappterverse-<name>/1.0`` family every other state file uses.
DOC_SCHEMA = "rappterverse-verifications/1.0"
# Record schema: the cross-repo vote shape shared with Rappterbook.
RECORD_SCHEMA = "rapp-verification/1"

SUBJECT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# Only kinds with an owner resolver are votable. ``object``, ``chronicle`` and
# ``post`` were in the brief; they come back when a resolver can name their
# controller, because a kind without one would let an author pass-vote their
# own artifact.
SUBJECT_KINDS = ("program",)
ENVIRONMENT_MAX = 100
NOTES_MAX = 1000
# ``verifier`` is a GitHub login: 1-39 chars of [A-Za-z0-9-], no leading,
# trailing or doubled hyphen. Anything else (a Kelvin-sign look-alike, a
# space, a 2 MB string) is not a controller and never reaches the store.
VERIFIER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
VERIFIER_MAX = 39
# ``agent_id`` is an agent record id; the longest in state/agents.json is far
# below this, and an unbounded field would let one record bloat the store.
AGENT_ID_MAX = 64
HIDE_MIN_VOTES = 5
HIDE_PASS_RATE = 0.20
WILSON_Z = 1.959964  # two-sided 95%
# Logins that may never appear as a verifier: they are not peers.
RESERVED_VERIFIERS = frozenset({"system"})
# A vote's ``at`` decides which of a controller's votes on a subject is live,
# so a self-declared far-future instant would pin a vote nobody could ever
# replace. The validators refuse an ``at`` (and a delta ``timestamp`` that
# becomes one) more than this far ahead of their own clock; honest clock skew
# fits comfortably inside it.
MAX_FUTURE_SKEW_SECONDS = 600
# The one ``at`` grammar every interpreter reads the same way:
# ``YYYY-MM-DDTHH:MM:SS``, an optional fraction of one to six digits, and an
# optional ``Z`` or ``+HH:MM`` offset (a missing offset is UTC). It is pinned
# here instead of delegated to ``datetime.fromisoformat`` because 3.11+ also
# accepts week dates, basic-format stamps, nine-digit fractions and bare
# ``+HHMM`` offsets that 3.9 rejects; a record stored by a 3.11 fold would
# then be unparseable on a 3.9 fold and push ``supersedes`` into its string
# fallback.
AT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?P<fraction>\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?"
)

RECORD_FIELDS = (
    "schema", "verifier", "agent_id", "subject", "subject_kind",
    "environment", "passed", "notes", "at",
)


# ── content ids ──────────────────────────────────────────────────────────────

def content_id(data) -> str:
    """``sha256:<hex>`` of ``data``.

    ``bytes`` are hashed exactly as given, so for a file
    ``content_id(path.read_bytes())`` equals ``sha256sum <file>`` whatever its
    line endings. A ``str`` is encoded as UTF-8 first; use that for text you
    produced yourself (a canonical program body, a canonical JSON form such as
    ``json.dumps(value, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)``). Never hash ``Path.read_text()`` output for a file
    id — universal-newline translation changes the bytes.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("content_id expects str or bytes")
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


# ── store ────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_store(store: dict) -> dict:
    """Give a (possibly empty) mapping the keys a store needs. In place."""
    if not isinstance(store, dict):
        raise TypeError("store must be a dict")
    if store.get("schema") != DOC_SCHEMA:
        store["schema"] = DOC_SCHEMA
    store.setdefault("record_schema", RECORD_SCHEMA)
    store.setdefault("generated", _utc_now())
    if not isinstance(store.get("verifications"), list):
        store["verifications"] = []
    if not isinstance(store.get("subjects"), dict):
        store["subjects"] = {}
    meta = store.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
        store["_meta"] = meta
    meta.setdefault("lastUpdate", store["generated"])
    meta.setdefault("verificationCount", len(store["verifications"]))
    meta.setdefault("subjectCount", len({
        r.get("subject") for r in store["verifications"] if isinstance(r, dict)
    }))
    return store


def load(path=None) -> dict:
    """Load the store at ``path`` (default ``state/verifications.json``).

    A *missing* file yields an empty store, so a first vote can create the
    file. A file that exists but cannot be read or parsed, whose top level is
    not an object, whose ``verifications`` is not a list, whose ``subjects``
    is not an object, or that carries other keys but no ``verifications`` at
    all, raises ``ValueError``: silently treating a damaged store as empty
    would drop the subject registry and every prior vote, and a writer that
    then saved would replace the whole history with nothing. Only a
    brand-new ``{}`` is repaired into an empty store (see
    ``store_shape_problem``).
    """
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        with open(target, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except FileNotFoundError:
        return _ensure_store({})
    except (OSError, ValueError) as exc:
        raise ValueError(f"verifications store unreadable: {target}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"verifications store unreadable: {target}: top level is not an object")
    problem = store_shape_problem(loaded)
    if problem:
        raise ValueError(f"verifications store unreadable: {target}: {problem}")
    return _ensure_store(loaded)


def store_shape_problem(store) -> str:
    """Why ``store`` must not be repaired into an empty store, or ``""``.

    Shared by ``load`` and the direct-edit validator so a damaged file is
    rejected the same way on every path.
    """
    if not isinstance(store, dict):
        return "top level is not an object"
    if "verifications" not in store:
        # ``{}`` is a brand-new store. Anything else without the votes list
        # (a ``subjects`` registry, ``_meta`` counts, a schema string) is a
        # store that lost its history, not an empty one.
        return "`verifications` is missing" if store else ""
    if not isinstance(store["verifications"], list):
        return "`verifications` is not a list"
    if "subjects" in store and not isinstance(store["subjects"], dict):
        return "`subjects` is not an object"
    return ""


def save(store: dict, path, timestamp=None) -> Path:
    """Write ``store`` to ``path`` with the house formatting.

    ``schema`` stays the first key (rapp-static-api/1.0 §3), ``_meta`` counts
    are refreshed, ``generated`` and ``_meta.lastUpdate`` are set to
    ``timestamp`` (default: now, UTC), and the file is written with 4-space
    indent plus a trailing newline like every other ``save_json`` under
    ``scripts/``. Both folds write through here.
    """
    _ensure_store(store)
    now = timestamp if isinstance(timestamp, str) and timestamp else _utc_now()
    store["generated"] = now
    store["_meta"]["lastUpdate"] = now
    store["_meta"]["verificationCount"] = len(store["verifications"])
    store["_meta"]["subjectCount"] = len({
        r.get("subject") for r in store["verifications"] if isinstance(r, dict)
    })
    ordered = {"schema": DOC_SCHEMA}
    for key, value in store.items():
        if key != "schema":
            ordered[key] = value
    try:
        from static_api import stamp_mapping  # manifest-declared schema wins when present
        ordered = stamp_mapping(ordered, path)
    except ImportError:  # pragma: no cover - vendored copy without static_api
        pass
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(ordered, handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    return target


# ── records ──────────────────────────────────────────────────────────────────

def _valid_iso8601(value) -> bool:
    """True for an ``at`` in the pinned grammar that also converts to a UTC instant.

    Only ``AT_PATTERN`` is accepted, on every interpreter alike. An offset
    timestamp at the very edge of the datetime range (such as
    ``0001-01-01T00:00:00+01:00``) matches but cannot be expressed in UTC; it
    is rejected here too, so no stored record can make ``supersedes`` fall
    back to a string comparison.
    """
    return parse_at(value) is not None


def parse_at(value):
    """Aware UTC ``datetime`` for an ``at`` in ``AT_PATTERN``, or None otherwise.

    ``Z``, ``+HH:MM`` offsets, fractional seconds and naive values (taken as
    UTC) all compare as instants, so ``09:00-05:00`` sorts after ``10:00Z``
    the way a string comparison never would. The fraction is padded to six
    digits before parsing so 3.9 (which reads only three or six) agrees with
    3.11+. Never raises: a value outside the grammar, or one that parses but
    overflows when converted to UTC, is ``None``.
    """
    if not isinstance(value, str) or not value:
        return None
    match = AT_PATTERN.fullmatch(value)
    if match is None:
        return None
    fraction = match.group("fraction")
    if fraction is not None and len(fraction) < 7:
        value = value.replace(fraction, fraction.ljust(7, "0"), 1)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def too_far_in_future(value, now=None, *, skew_seconds: int = MAX_FUTURE_SKEW_SECONDS) -> bool:
    """True when ``value`` is an instant more than ``skew_seconds`` after ``now``.

    ``now`` defaults to the current UTC time; an unparseable ``value`` is not
    "in the future" (the shape checks report it). Used by the validators so a
    vote's self-declared ``at`` cannot outrun every later re-vote.
    """
    instant = parse_at(value)
    if instant is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    elif isinstance(now, str):
        now = parse_at(now)
        if now is None:
            return False
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return instant > now + timedelta(seconds=skew_seconds)


def supersedes(existing_at, new_at, *, strict: bool = False) -> bool:
    """True when the vote at ``existing_at`` keeps its place against ``new_at``.

    Instants are compared when both parse; equal instants count as "already
    folded" (the existing vote wins) unless ``strict`` is set, in which case
    only a strictly newer existing vote wins. When either value does not
    parse the comparison falls back to the strings, so a fold never crashes
    on a record the validators have not seen.
    """
    left = parse_at(existing_at)
    right = parse_at(new_at)
    if left is None or right is None:
        left, right = str(existing_at or ""), str(new_at or "")
    return left > right if strict else left >= right


def _single_line(value: str) -> bool:
    return "\n" not in value and "\r" not in value


def same_login(left, right) -> bool:
    """GitHub logins are case-insensitive; compare them that way everywhere."""
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return left.strip().casefold() == right.strip().casefold()


def _validate_record(rec: dict) -> dict:
    """Return a normalised copy of ``rec`` or raise ``ValueError``."""
    if not isinstance(rec, dict):
        raise ValueError("verification must be an object")
    schema = rec.get("schema", RECORD_SCHEMA)
    if schema != RECORD_SCHEMA:
        raise ValueError(f"verification schema must be `{RECORD_SCHEMA}`")

    verifier = rec.get("verifier")
    if not isinstance(verifier, str) or not verifier.strip() or not _single_line(verifier):
        raise ValueError("`verifier` (controller login) is required")
    if verifier.strip().casefold() in RESERVED_VERIFIERS:
        raise ValueError("`verifier` must be a controller login; `system` does not cast peer votes")
    if len(verifier.strip()) > VERIFIER_MAX or not VERIFIER_RE.match(verifier.strip()):
        raise ValueError(
            f"`verifier` must be a GitHub login (1-{VERIFIER_MAX} ASCII letters, digits or hyphens)"
        )
    agent_id = rec.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip() or not _single_line(agent_id):
        raise ValueError("`agent_id` is required")
    if len(agent_id.strip()) > AGENT_ID_MAX:
        raise ValueError(f"`agent_id` must be at most {AGENT_ID_MAX} characters")

    subject = rec.get("subject")
    if not isinstance(subject, str) or not SUBJECT_RE.match(subject):
        raise ValueError("`subject` must match ^sha256:[0-9a-f]{64}$")
    kind = rec.get("subject_kind")
    if kind not in SUBJECT_KINDS:
        raise ValueError("`subject_kind` must be one of: " + ", ".join(SUBJECT_KINDS))

    environment = rec.get("environment")
    if not isinstance(environment, str) or not environment.strip():
        raise ValueError("`environment` is required")
    if len(environment) > ENVIRONMENT_MAX or not _single_line(environment):
        raise ValueError(f"`environment` must be a single line of at most {ENVIRONMENT_MAX} characters")

    passed = rec.get("passed")
    if not isinstance(passed, bool):
        raise ValueError("`passed` must be true or false")

    notes = rec.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise ValueError("`notes` must be a string")
    if len(notes) > NOTES_MAX:
        raise ValueError(f"`notes` must be at most {NOTES_MAX} characters")
    if not passed and not notes.strip():
        raise ValueError("`notes` are required when `passed` is false")

    at = rec.get("at")
    if not _valid_iso8601(at):
        raise ValueError("`at` must be an ISO-8601 timestamp")

    return {
        "schema": RECORD_SCHEMA,
        "verifier": verifier.strip(),
        "agent_id": agent_id.strip(),
        "subject": subject,
        "subject_kind": kind,
        "environment": environment.strip(),
        "passed": passed,
        "notes": notes,
        "at": at,
    }


def _as_login_set(value) -> set:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {v.strip() for v in value if isinstance(v, str) and v.strip()}
    return set()


def resolved_owners(store: dict, subject: str, subject_owners=None) -> set:
    """Every controller login known to own ``subject``, from authoritative sources only.

    ``subject_owners`` is either a login (a string, meaning "the caller already
    resolved the owner of this subject") or a ``{subject: login | [logins]}``
    map built from the repository (``slosh_lisp.program_subject_owners``).
    The store's ``subjects`` registry, written by earlier accepted votes, is
    the second source, so a program keeps its owner binding after its file
    moves on to a new version. A ``subject_owner`` declared on the vote itself
    is *not* a source: it is only ever used against the verifier.
    """
    owners: set = set()
    if isinstance(subject_owners, str):
        owners |= _as_login_set(subject_owners)
    elif isinstance(subject_owners, dict):
        owners |= _as_login_set(subject_owners.get(subject))
    registry = store.get("subjects") if isinstance(store.get("subjects"), dict) else {}
    registered = registry.get(subject)
    if isinstance(registered, dict):
        owners |= _as_login_set(registered.get("owner"))
        owners |= _as_login_set(registered.get("owners"))
    return owners


def _remember_owners(store: dict, subject: str, kind: str, owners: set):
    """Persist the (subject -> owners) binding so later votes keep it."""
    if not owners:
        return
    entry = store["subjects"].get(subject)
    if not isinstance(entry, dict):
        entry = {}
    known = _as_login_set(entry.get("owner")) | _as_login_set(entry.get("owners")) | owners
    ordered = sorted(known, key=str.casefold)
    entry["owner"] = ordered[0]
    if len(ordered) > 1:
        entry["owners"] = ordered
    else:
        entry.pop("owners", None)
    entry["kind"] = kind
    store["subjects"][subject] = entry


def record(store: dict, rec: dict, subject_owner=None, *, subject_owners=None,
           require_owner: bool = False, controller=None) -> dict:
    """Validate ``rec`` and fold it into ``store``; return the store.

    Raises ``ValueError`` on an invalid record, a self-verify, or (with
    ``require_owner=True``) a subject whose owner nobody can name. The owner
    set comes from ``subject_owner`` (a login, or a ``{subject: login(s)}``
    map — ``subject_owners=`` is the same thing spelled as a keyword) and from
    the store's ``subjects`` registry; see ``resolved_owners``. A
    ``rec["subject_owner"]`` the voter declares is only used *against* them.
    An existing vote by the same verifier (case-insensitive) on the same
    subject is replaced in place; the store is never appended twice for one
    (verifier, subject).

    ``controller`` is the login the caller resolved from ``agents.json`` (or
    the delta envelope). When given, it must be the same login as the
    declared ``verifier`` (case-insensitively) and is what gets *stored*, so
    the file carries one spelling per controller rather than whatever case
    the voter typed.
    """
    _ensure_store(store)
    clean = _validate_record(rec)
    if controller is not None:
        if not same_login(controller, clean["verifier"]):
            raise ValueError(
                f"`verifier` `{clean['verifier']}` is not the controller `{controller}`"
            )
        clean["verifier"] = controller.strip()
    source = subject_owner if subject_owner is not None else subject_owners
    owners = resolved_owners(store, clean["subject"], source)
    declared = _as_login_set(rec.get("subject_owner"))
    if any(same_login(owner, clean["verifier"]) for owner in owners | declared):
        raise ValueError(
            f"self-verify rejected: `{clean['verifier']}` controls subject {clean['subject'][:19]}…"
        )
    if require_owner and not owners:
        raise ValueError(
            f"subject {clean['subject'][:19]}… is not a known artifact: vote on the "
            "content id of a committed state/programs/<agentId>.lisp (see "
            "`python3 scripts/slosh_lisp.py subjects <file>`)"
        )

    votes = store["verifications"]
    for index, existing in enumerate(votes):
        if (
            isinstance(existing, dict)
            and same_login(existing.get("verifier"), clean["verifier"])
            and existing.get("subject") == clean["subject"]
        ):
            votes[index] = clean
            break
    else:
        votes.append(clean)

    _remember_owners(store, clean["subject"], clean["subject_kind"], owners)
    store["_meta"]["verificationCount"] = len(votes)
    store["_meta"]["subjectCount"] = len({v.get("subject") for v in votes if isinstance(v, dict)})
    return store


def record_from_action(action: dict) -> dict:
    """The ``rapp-verification/1`` record a ``verify``-typed action carries.

    ``agent_id`` and ``at`` come from the action envelope (``agentId``,
    ``timestamp``); everything else from ``data``. ``verifier`` is copied as
    declared — the caller binds it to the actor's controller.
    """
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    return {
        "schema": RECORD_SCHEMA,
        "verifier": data.get("verifier"),
        "agent_id": action.get("agentId"),
        "subject": data.get("subject"),
        "subject_kind": data.get("subject_kind"),
        "environment": data.get("environment"),
        "passed": data.get("passed"),
        "notes": data.get("notes", ""),
        "at": action.get("timestamp"),
        "subject_owner": data.get("subject_owner"),
    }


def find_vote(store: dict, verifier: str, subject: str):
    """The live vote by ``verifier`` on ``subject``, or None."""
    for existing in store.get("verifications") or []:
        if (
            isinstance(existing, dict)
            and same_login(existing.get("verifier"), verifier)
            and existing.get("subject") == subject
        ):
            return existing
    return None


# ── scoring ──────────────────────────────────────────────────────────────────

def _wilson_lower(passes: int, total: int, z: float = WILSON_Z) -> float:
    if total <= 0:
        return 0.0
    p_hat = passes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = p_hat + z2 / (2.0 * total)
    margin = z * math.sqrt(p_hat * (1.0 - p_hat) / total + z2 / (4.0 * total * total))
    return max(0.0, (centre - margin) / denominator)


def score(store: dict, subject: str) -> dict:
    """Aggregate the live votes on ``subject``.

    Returns ``pass_count``, ``fail_count``, ``votes``, ``pass_rate``, ``score``
    (Wilson lower bound at 95% of the pass rate — one lone pass scores 0.21,
    five unanimous passes 0.57, so confidence grows with independent voters)
    and ``hidden`` (``votes >= 5`` and ``pass_rate < 0.20``).
    """
    votes = [
        v for v in (store.get("verifications") or [])
        if isinstance(v, dict) and v.get("subject") == subject
    ]
    pass_count = sum(1 for v in votes if v.get("passed") is True)
    fail_count = len(votes) - pass_count
    total = len(votes)
    pass_rate = (pass_count / total) if total else 0.0
    return {
        "subject": subject,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "votes": total,
        "pass_rate": round(pass_rate, 4),
        "score": round(_wilson_lower(pass_count, total), 4),
        "hidden": total >= HIDE_MIN_VOTES and pass_rate < HIDE_PASS_RATE,
    }


def is_hidden(store: dict, subject: str) -> bool:
    """True once five or more controllers voted and fewer than 20% passed."""
    return bool(score(store, subject)["hidden"])


# ── tiny CLI, for verifiers at the keyboard ──────────────────────────────────

def _main(argv: list) -> int:
    usage = (
        "usage: verifications.py content-id <file>      # sha256 of the file bytes\n"
        "       verifications.py score <sha256:...> [store.json]"
    )
    if len(argv) >= 2 and argv[0] == "content-id":
        print(content_id(Path(argv[1]).read_bytes()))
        return 0
    if len(argv) >= 2 and argv[0] == "score":
        store = load(argv[2] if len(argv) > 2 else None)
        print(json.dumps(score(store, argv[1]), indent=2))
        return 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
