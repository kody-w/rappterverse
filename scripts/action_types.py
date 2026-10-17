#!/usr/bin/env python3
"""The one list of action types every RAPPterverse validator accepts.

``scripts/validate_action.py`` (direct ``state/actions.json`` PRs) and
``scripts/validate_delta.py`` (``state/inbox`` deltas) used to carry their own
copies of this set, and they drifted: ``verify`` was accepted by one and
rejected by the other. Both now import from here, and ``llms.txt`` cites this
file so the published list cannot rot against the enforced one. The UTC
rule both validators apply to newly appended timestamps lives here too.

Python 3.9+, stdlib only.
"""

from __future__ import annotations

import re
from datetime import datetime

VALID_ACTION_TYPES = frozenset({
    "move", "chat", "emote", "spawn", "despawn",
    "interact", "trade_offer", "trade_accept", "trade_decline",
    "battle_challenge", "battle_action", "place_object",
    "teach", "verify",
})

VALID_EMOTES = frozenset({
    "wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod",
})

# The order llms.txt prints them in (stable, human-readable).
ACTION_TYPES_IN_DOC_ORDER = (
    "move", "chat", "emote", "spawn", "despawn",
    "interact", "trade_offer", "trade_accept", "trade_decline",
    "battle_challenge", "battle_action", "place_object",
    "teach", "verify",
)

assert set(ACTION_TYPES_IN_DOC_ORDER) == VALID_ACTION_TYPES


# Newly appended action, chat message and inbox delta timestamps must be UTC.
# ``scripts/test_state_integrity.py`` (TestActionIntegrity) orders the
# ``state/actions.json`` window by *string* comparison, so a ``+02:00`` stamp
# that is honest as an instant would sort above every later ``Z`` stamp and
# fail every following PR until the UTC clock caught up (up to 14 hours).
# ``Z`` is the documented form and what every generator in ``scripts/``
# writes; ``+00:00`` (Python ``isoformat()``) and a one-to-six digit fraction
# (JavaScript ``toISOString()``) are accepted because they sort correctly
# against ``Z`` stamps of other seconds. Pinned here rather than delegated to
# ``datetime.fromisoformat``, which on 3.11+ also accepts basic-format stamps
# that sort above every extended-format one.
UTC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)")

UTC_TIMESTAMP_RULE = (
    "must be UTC as `YYYY-MM-DDTHH:MM:SSZ` (a fraction or `+00:00` is accepted; "
    "any other offset, or none, is rejected because the actions and chat windows "
    "are ordered by string comparison)"
)


def is_utc_timestamp(value) -> bool:
    """True for a UTC timestamp string in the form ``UTC_TIMESTAMP_RE`` pins."""
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True
