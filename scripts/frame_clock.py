"""Universal frame number for the metaverse — derived from git log.

There is ONE canonical frame: the highest [frame N] tag in commit history.
The pump (and any other agent that produces a frame) commits with subject
`[frame N] <action> by <agent>`. That number IS the frame.

state/frame_counter.json is a CACHE of this — kept up to date so the
frontend can read it via raw.githubusercontent.com without crawling git
history. When `frame_counter.json` and git log disagree, git log wins.

Time machine ⇒ each frame commit IS a snapshot of the world at that frame.
Walking back through commits = scrubbing the timeline.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "state"
FRAME_COUNTER_PATH = STATE_DIR / "frame_counter.json"

_FRAME_RE = re.compile(r"^\[frame\s+(\d+)\]")


def _git_log_frame_subjects(limit: int = 5000) -> list[tuple[str, int]]:
    """Return [(sha, frame_n), ...] for commits whose subject starts with [frame N]."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "log",
             f"--max-count={limit}", "--pretty=%H%x09%s"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    out_pairs: list[tuple[str, int]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        sha, subj = line.split("\t", 1)
        m = _FRAME_RE.match(subj)
        if m:
            out_pairs.append((sha, int(m.group(1))))
    return out_pairs


def latest_frame() -> int:
    """Highest [frame N] number anywhere in git log. 0 if none found."""
    pairs = _git_log_frame_subjects()
    if not pairs:
        return 0
    return max(n for _sha, n in pairs)


def latest_frame_with_sha() -> tuple[int, str | None]:
    """Highest frame number and the commit sha that produced it."""
    pairs = _git_log_frame_subjects()
    if not pairs:
        return 0, None
    sha, n = max(pairs, key=lambda p: p[1])
    return n, sha


def sync_frame_counter() -> int:
    """Rewrite state/frame_counter.json so its `frame` field matches git log.

    Preserves started_at, frames_per_hour, sim_minutes_per_frame. Updates
    last_frame_at to the timestamp of the head [frame N] commit if we can
    find it; otherwise to now. Returns the canonical frame number.
    """
    frame, sha = latest_frame_with_sha()
    raw = {}
    if FRAME_COUNTER_PATH.exists():
        try:
            raw = json.loads(FRAME_COUNTER_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            raw = {}
    raw["frame"] = frame
    raw.setdefault("started_at", "2026-03-27T13:00:00Z")
    raw.setdefault("frames_per_hour", 12)
    raw.setdefault("sim_minutes_per_frame", 45)

    last_frame_at = None
    if sha:
        try:
            ts = subprocess.check_output(
                ["git", "-C", str(REPO_ROOT), "show", "-s", "--format=%cI", sha],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            if ts:
                # Normalize to Z form
                if "+" in ts or ts.endswith("Z"):
                    last_frame_at = datetime.fromisoformat(ts.replace("Z", "+00:00")) \
                        .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (subprocess.CalledProcessError, ValueError):
            pass
    if not last_frame_at:
        last_frame_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw["last_frame_at"] = last_frame_at

    meta = raw.get("_meta", {}) or {}
    meta["lastUpdate"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["version"] = meta.get("version", 1)
    raw["_meta"] = meta

    FRAME_COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRAME_COUNTER_PATH.write_text(json.dumps(raw, indent=4) + "\n")
    return frame


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        f = sync_frame_counter()
        print(f"frame {f} synced to {FRAME_COUNTER_PATH}")
    else:
        print(latest_frame())
