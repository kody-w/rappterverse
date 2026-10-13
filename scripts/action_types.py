#!/usr/bin/env python3
"""The one list of action types every RAPPterverse validator accepts.

``scripts/validate_action.py`` (direct ``state/actions.json`` PRs) and
``scripts/validate_delta.py`` (``state/inbox`` deltas) used to carry their own
copies of this set, and they drifted: ``verify`` was accepted by one and
rejected by the other. Both now import from here, and ``llms.txt`` cites this
file so the published list cannot rot against the enforced one.

Python 3.9+, stdlib only.
"""

from __future__ import annotations

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
