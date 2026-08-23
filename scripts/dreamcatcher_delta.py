#!/usr/bin/env python3
"""Deterministic git-worktree deltas for Dreamcatcher fan-out/fan-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Optional

SCHEMA = "dreamcatcher-delta/1.0"
BATCH_SCHEMA = "dreamcatcher-batch/1.0"
PRODUCER = {"name": "twin-dreamcatcher", "version": "0.2.1"}
LINE_COORDINATES = "git-xdiff-unified-0/base-v1"
STATUSES = {"A", "M", "D", "R", "C", "T", "U"}
ENTITY_KEYS = {
    "id",
    "frame_id",
    "agent_id",
    "rappid",
    "tile_id",
    "stream_id",
    "node_id",
    "discussion_id",
    "discussion_number",
    "post_id",
    "world_id",
}
ENTITY_PATTERN = re.compile(
    r"""["'](?P<key>"""
    + "|".join(sorted(ENTITY_KEYS, key=len, reverse=True))
    + r""")["']\s*:\s*(?P<value>["'][^"'\r\n]{1,256}["']|-?\d+)"""
)
HUNK_PATTERN = re.compile(
    r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
)
HUNK_BYTES_PATTERN = re.compile(
    rb"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? "
    rb"\+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
)
RAW_DIFF_PATTERN = re.compile(
    rb"^:[0-7]{6} [0-7]{6} [0-9a-f]+ [0-9a-f]+ "
    rb"(?P<status>[A-Z])(?P<similarity>\d*)$"
)
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
BLOB_STREAM_CHUNK_BYTES = 64 * 1024
GIT_RECORD_MAX_BYTES = 1024 * 1024
ENTITY_LINE_MAX_BYTES = 1024 * 1024
PATCH_LINE_MAX_BYTES = 1024 * 1024
PATCH_LINE_PREFIX_BYTES = 4096
WORKTREE_CAPTURE_MAX_ATTEMPTS = 3


class DeltaProtocolError(ValueError):
    """A delta manifest is malformed or cannot be generated safely."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _content_id(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _with_id(payload: dict, field: str) -> dict:
    result = dict(payload)
    result[field] = _content_id(payload)
    return result


def _run_git(
    repo: Path,
    args: list[str],
    *,
    binary: bool = False,
    check: bool = True,
    input_data: Optional[bytes] = None,
) -> bytes | str:
    env = os.environ.copy()
    env.update({"LANG": "C", "LC_ALL": "C"})
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=not binary,
        input=input_data,
        env=env,
    )
    if check and result.returncode != 0:
        stderr = (
            result.stderr.decode("utf-8", "replace")
            if binary
            else result.stderr
        )
        raise DeltaProtocolError(
            f"git {' '.join(args)} failed: {stderr.strip() or result.returncode}"
        )
    return result.stdout


def _popen_git(
    repo: Path,
    args: list[str],
    *,
    pipe_stdin: bool = False,
) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({"LANG": "C", "LC_ALL": "C"})
    return subprocess.Popen(
        ["git", *args],
        cwd=repo,
        stdin=subprocess.PIPE if pipe_stdin else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _resolve_commit(repo: Path, ref: str) -> str:
    value = str(_run_git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])).strip()
    if not COMMIT_PATTERN.fullmatch(value):
        raise DeltaProtocolError(f"{ref!r} did not resolve to a commit")
    return value


def _merge_base(repo: Path, left: str, right: str) -> str:
    value = str(_run_git(repo, ["merge-base", left, right])).strip()
    if not COMMIT_PATTERN.fullmatch(value):
        raise DeltaProtocolError("git merge-base did not return a commit")
    return value


def _normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DeltaProtocolError(f"invalid repository path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DeltaProtocolError(f"path escapes repository: {value!r}")
    canonical = path.as_posix()
    if canonical != value:
        raise DeltaProtocolError(
            f"repository path is not canonical: {value!r}"
        )
    return canonical


def _note_buffered_blob(metrics: Optional[dict], size: int) -> None:
    if metrics is None:
        return
    metrics["max_buffered_blob_bytes"] = max(
        int(metrics.get("max_buffered_blob_bytes", 0)),
        size,
    )


def _note_buffered_patch(metrics: Optional[dict], size: int) -> None:
    if metrics is None:
        return
    metrics["max_buffered_patch_bytes"] = max(
        int(metrics.get("max_buffered_patch_bytes", 0)),
        size,
    )


def _note_accumulated_entities(metrics: Optional[dict], size: int) -> None:
    if metrics is None:
        return
    metrics["max_accumulated_entity_ids"] = max(
        int(metrics.get("max_accumulated_entity_ids", 0)),
        size,
    )


def _read_nul_record(stream: BinaryIO, *, context: str) -> bytes:
    value = bytearray()
    while True:
        chunk = stream.read(1)
        if not chunk:
            raise DeltaProtocolError(f"{context} returned a truncated record")
        if chunk == b"\0":
            return bytes(value)
        value.extend(chunk)
        if len(value) > GIT_RECORD_MAX_BYTES:
            raise DeltaProtocolError(f"{context} returned an oversized record")


class _GitBlobBatch:
    def __init__(
        self,
        repo: Path,
        *,
        metrics: Optional[dict] = None,
    ) -> None:
        self.process = _popen_git(
            repo,
            ["cat-file", "--batch", "-Z"],
            pipe_stdin=True,
        )
        if (
            self.process.stdin is None
            or self.process.stdout is None
            or self.process.stderr is None
        ):
            raise DeltaProtocolError("cannot open git cat-file pipes")
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.stderr = self.process.stderr
        self.metrics = metrics
        self.closed = False

    def summary(self, ref: str, path: str) -> Optional[dict]:
        query = f"{ref}:{path}".encode("utf-8", "surrogateescape")
        try:
            self.stdin.write(query + b"\0")
            self.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise DeltaProtocolError("git cat-file closed its input") from exc
        header = _read_nul_record(self.stdout, context="git cat-file")
        if header == query + b" missing":
            return None
        fields = header.rsplit(b" ", 2)
        if len(fields) != 3:
            raise DeltaProtocolError("git cat-file returned an invalid header")
        try:
            size = int(fields[2])
        except ValueError as exc:
            raise DeltaProtocolError(
                "git cat-file returned an invalid object size"
            ) from exc
        if size < 0:
            raise DeltaProtocolError("git cat-file returned an invalid object size")
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            chunk = self.stdout.read(min(BLOB_STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                raise DeltaProtocolError("git cat-file returned truncated content")
            _note_buffered_blob(self.metrics, len(chunk))
            digest.update(chunk)
            remaining -= len(chunk)
        if self.stdout.read(1) != b"\0":
            raise DeltaProtocolError("git cat-file returned truncated framing")
        return {"sha256": digest.hexdigest(), "bytes": size}

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.stdin.close()
            trailing = False
            while True:
                chunk = self.stdout.read(BLOB_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                _note_buffered_blob(self.metrics, len(chunk))
                trailing = True
            stderr = self.stderr.read().decode("utf-8", "replace")
            returncode = self.process.wait()
            self.stdout.close()
            self.stderr.close()
        except OSError as exc:
            self.process.kill()
            self.process.wait()
            raise DeltaProtocolError("cannot finish git cat-file") from exc
        if returncode != 0:
            raise DeltaProtocolError(
                "git cat-file --batch failed: "
                f"{stderr.strip() or returncode}"
            )
        if trailing:
            raise DeltaProtocolError("git cat-file returned trailing content")

    def __enter__(self) -> "_GitBlobBatch":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self.process.kill()
            self.process.wait()
            self.stdin.close()
            self.stdout.close()
            self.stderr.close()
            self.closed = True
            return False
        self.close()
        return False


def _stream_file_summary(
    candidate: Path,
    *,
    metrics: Optional[dict] = None,
) -> Optional[dict]:
    if candidate.is_symlink():
        content = os.fsencode(os.readlink(candidate))
        _note_buffered_blob(metrics, len(content))
        return {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    size = 0
    with candidate.open("rb") as handle:
        while True:
            chunk = handle.read(BLOB_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            _note_buffered_blob(metrics, len(chunk))
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _parse_name_status(raw: bytes) -> list[dict]:
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    changes: list[dict] = []
    index = 0
    while index < len(tokens):
        status_token = tokens[index].decode("ascii", "strict")
        index += 1
        status = status_token[:1]
        if status not in STATUSES:
            raise DeltaProtocolError(f"unsupported git status {status_token!r}")
        if status in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise DeltaProtocolError("truncated rename/copy record")
            old_path = _normalize_path(tokens[index].decode("utf-8", "surrogateescape"))
            path = _normalize_path(tokens[index + 1].decode("utf-8", "surrogateescape"))
            index += 2
            changes.append({
                "status": status,
                "similarity": int(status_token[1:] or 0),
                "old_path": old_path,
                "path": path,
            })
        else:
            if index >= len(tokens):
                raise DeltaProtocolError("truncated name-status record")
            path = _normalize_path(tokens[index].decode("utf-8", "surrogateescape"))
            index += 1
            changes.append({"status": status, "path": path})
    return changes


def _hunk_ranges(patch: str) -> list[dict]:
    ranges = []
    for line in patch.splitlines():
        match = HUNK_PATTERN.match(line)
        if not match:
            continue
        new_start = int(match.group("new"))
        new_count = int(match.group("new_count") or 1)
        old_start = int(match.group("old"))
        old_count = int(match.group("old_count") or 1)
        ranges.append({
            "old_start": old_start,
            "old_lines": old_count,
            "new_start": new_start,
            "new_lines": new_count,
        })
    return ranges


def _entity_ids(path: str, patch: str) -> list[str]:
    entities = {f"path:{path}"}
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        for match in ENTITY_PATTERN.finditer(line[1:]):
            value = match.group("value").strip("\"'")
            entities.add(f"{match.group('key')}:{value}")
    return sorted(entities)


class _BufferedGitOutput:
    def __init__(
        self,
        stream: BinaryIO,
        *,
        metrics: Optional[dict] = None,
    ) -> None:
        self.stream = stream
        self.buffer = bytearray()
        self.eof = False
        self.metrics = metrics
        self.digest = hashlib.sha256()

    def _extend(self, content: bytes) -> None:
        self.buffer.extend(content)
        _note_buffered_patch(self.metrics, len(self.buffer))

    def _read(self, size: int) -> bytes:
        content = self.stream.read(size)
        if content:
            self.digest.update(content)
        return content

    def read_until(
        self,
        delimiter: bytes,
        *,
        max_bytes: Optional[int] = None,
    ) -> Optional[bytes]:
        while True:
            index = self.buffer.find(delimiter)
            if index >= 0:
                value = bytes(self.buffer[:index])
                del self.buffer[:index + len(delimiter)]
                return value
            if self.eof:
                if not self.buffer:
                    return None
                value = bytes(self.buffer)
                self.buffer.clear()
                return value
            read_size = BLOB_STREAM_CHUNK_BYTES
            if max_bytes is not None:
                read_size = min(
                    read_size,
                    max_bytes + 1 - len(self.buffer),
                )
                if read_size <= 0:
                    raise DeltaProtocolError(
                        "git diff returned an oversized record"
                    )
            chunk = self._read(read_size)
            if chunk:
                self._extend(chunk)
                if max_bytes is not None and len(self.buffer) > max_bytes:
                    raise DeltaProtocolError("git diff returned an oversized record")
            else:
                self.eof = True

    def read_line(
        self,
        *,
        max_bytes: int,
    ) -> Optional[tuple[bytes, bool]]:
        while True:
            index = self.buffer.find(b"\n")
            if index >= 0:
                value = bytes(self.buffer[:index])
                del self.buffer[:index + 1]
                return value, True
            if self.eof:
                if not self.buffer:
                    return None
                value = bytes(self.buffer)
                self.buffer.clear()
                return value, True
            if len(self.buffer) >= max_bytes:
                prefix = bytes(self.buffer[:PATCH_LINE_PREFIX_BYTES])
                self.buffer.clear()
                self._drain_line()
                return prefix, False
            chunk = self._read(min(
                BLOB_STREAM_CHUNK_BYTES,
                max_bytes - len(self.buffer),
            ))
            if chunk:
                self._extend(chunk)
            else:
                self.eof = True

    def _drain_line(self) -> None:
        while True:
            chunk = self._read(BLOB_STREAM_CHUNK_BYTES)
            if not chunk:
                self.eof = True
                return
            newline = chunk.find(b"\n")
            if newline < 0:
                continue
            self._extend(chunk[newline + 1:])
            return


def _parse_raw_change(
    header: bytes,
    reader: _BufferedGitOutput,
) -> dict:
    match = RAW_DIFF_PATTERN.fullmatch(header)
    if not match:
        raise DeltaProtocolError("git diff returned invalid raw metadata")
    status = match.group("status").decode("ascii")
    if status not in STATUSES:
        raise DeltaProtocolError(f"unsupported git status {status!r}")
    first = reader.read_until(b"\0", max_bytes=GIT_RECORD_MAX_BYTES)
    if first is None:
        raise DeltaProtocolError("git diff returned a truncated path")
    first_path = _normalize_path(first.decode("utf-8", "surrogateescape"))
    if status in {"R", "C"}:
        second = reader.read_until(b"\0", max_bytes=GIT_RECORD_MAX_BYTES)
        if second is None:
            raise DeltaProtocolError("git diff returned a truncated rename/copy")
        path = _normalize_path(second.decode("utf-8", "surrogateescape"))
        return {
            "status": status,
            "similarity": int(match.group("similarity") or b"0"),
            "old_path": first_path,
            "path": path,
        }
    if match.group("similarity"):
        raise DeltaProtocolError("git diff returned similarity for a non-rename")
    return {"status": status, "path": first_path}


def _read_raw_changes(reader: _BufferedGitOutput) -> list[dict]:
    changes = []
    header = reader.read_until(b"\0", max_bytes=GIT_RECORD_MAX_BYTES)
    if header is None:
        return changes
    while header:
        changes.append(_parse_raw_change(header, reader))
        header = reader.read_until(b"\0", max_bytes=GIT_RECORD_MAX_BYTES)
        if header is None:
            raise DeltaProtocolError("git diff omitted the raw/patch separator")
    return changes


def _disable_entity_accumulation(metadata: dict) -> None:
    metadata["entities_complete"] = False
    metadata["entities"].clear()


def _scan_entity_line(
    metadata: dict,
    content: bytes,
    *,
    metrics: Optional[dict] = None,
) -> None:
    if not metadata["entities_complete"]:
        return
    if len(content) > ENTITY_LINE_MAX_BYTES:
        _disable_entity_accumulation(metadata)
        return
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError:
        _disable_entity_accumulation(metadata)
        return
    for match in ENTITY_PATTERN.finditer(text):
        value = match.group("value").strip("\"'")
        metadata["entities"].add(f"{match.group('key')}:{value}")
    _note_accumulated_entities(metrics, len(metadata["entities"]))


def _finish_patch_hunk(metadata: dict) -> None:
    if metadata["old_remaining"] or metadata["new_remaining"]:
        raise DeltaProtocolError("git diff returned a truncated hunk")
    metadata["in_hunk"] = False


def _new_patch_metadata(path: str) -> dict:
    return {
        "line_ranges": [],
        "entities": {f"path:{path}"},
        "entities_complete": True,
        "coordinates_complete": True,
        "binary": False,
        "in_hunk": False,
        "old_remaining": 0,
        "new_remaining": 0,
    }


def _stream_patch_metadata(
    reader: _BufferedGitOutput,
    changes: list[dict],
    *,
    metrics: Optional[dict] = None,
) -> list[dict]:
    metadata = [_new_patch_metadata(change["path"]) for change in changes]
    for value in metadata:
        _note_accumulated_entities(metrics, len(value["entities"]))
    # Raw and patch records share Git's order; a type change expands to delete/add.
    section_targets = [
        index
        for index, change in enumerate(changes)
        for _ in range(2 if change["status"] == "T" else 1)
    ]
    section_index = -1
    current: Optional[dict] = None
    allowed_metadata = (
        b"index ",
        b"old mode ",
        b"new mode ",
        b"new file mode ",
        b"deleted file mode ",
        b"similarity index ",
        b"dissimilarity index ",
        b"rename from ",
        b"rename to ",
        b"copy from ",
        b"copy to ",
        b"--- ",
        b"+++ ",
    )
    while True:
        record = reader.read_line(max_bytes=PATCH_LINE_MAX_BYTES)
        if record is None:
            break
        line, line_complete = record
        if line.startswith(b"diff --git "):
            if current is not None and current["in_hunk"]:
                _finish_patch_hunk(current)
            section_index += 1
            if section_index >= len(section_targets):
                raise DeltaProtocolError("git diff returned an extra patch section")
            change_index = section_targets[section_index]
            if changes[change_index]["status"] == "U":
                raise DeltaProtocolError(
                    "unmerged diffs do not have shared-base coordinates"
                )
            current = metadata[change_index]
            if changes[change_index]["status"] == "T":
                current["coordinates_complete"] = False
                _disable_entity_accumulation(current)
            continue
        if line.startswith((b"diff --cc ", b"diff --combined ")):
            raise DeltaProtocolError(
                "combined diffs do not have shared-base coordinates"
            )
        if current is None:
            if line:
                raise DeltaProtocolError("git diff returned patch data without a path")
            continue
        if not line_complete:
            _disable_entity_accumulation(current)
            current["coordinates_complete"] = False
        if line.startswith(b"@@ "):
            if current["in_hunk"]:
                _finish_patch_hunk(current)
            match = HUNK_BYTES_PATTERN.match(line)
            if not match:
                raise DeltaProtocolError("git diff returned an invalid hunk header")
            old_lines = int(match.group("old_count") or 1)
            new_lines = int(match.group("new_count") or 1)
            current["line_ranges"].append({
                "old_start": int(match.group("old")),
                "old_lines": old_lines,
                "new_start": int(match.group("new")),
                "new_lines": new_lines,
            })
            current["old_remaining"] = old_lines
            current["new_remaining"] = new_lines
            current["in_hunk"] = True
            if not old_lines and not new_lines:
                raise DeltaProtocolError("git diff returned an empty hunk")
            continue
        if current["in_hunk"]:
            if line.startswith(b"+"):
                if current["new_remaining"] <= 0:
                    raise DeltaProtocolError("git diff hunk exceeds its new range")
                current["new_remaining"] -= 1
                _scan_entity_line(current, line[1:], metrics=metrics)
            elif line.startswith(b"-"):
                if current["old_remaining"] <= 0:
                    raise DeltaProtocolError("git diff hunk exceeds its old range")
                current["old_remaining"] -= 1
                _scan_entity_line(current, line[1:], metrics=metrics)
            elif line.startswith(b" "):
                if (
                    current["old_remaining"] <= 0
                    or current["new_remaining"] <= 0
                ):
                    raise DeltaProtocolError("git diff hunk has excess context")
                current["old_remaining"] -= 1
                current["new_remaining"] -= 1
            elif line.startswith(b"\\ No newline at end of file"):
                continue
            else:
                raise DeltaProtocolError("git diff returned invalid hunk content")
            if not current["old_remaining"] and not current["new_remaining"]:
                current["in_hunk"] = False
            continue
        if line.startswith(b"Binary files ") or line == b"GIT binary patch":
            current["binary"] = True
            _disable_entity_accumulation(current)
        elif line.startswith(b"\\ No newline at end of file"):
            continue
        elif line.startswith(b"Submodule "):
            current["coordinates_complete"] = False
            _disable_entity_accumulation(current)
        elif line and not line.startswith(allowed_metadata):
            current["coordinates_complete"] = False
            _disable_entity_accumulation(current)
    if current is not None and current["in_hunk"]:
        _finish_patch_hunk(current)
    if changes and section_index + 1 != len(section_targets):
        raise DeltaProtocolError("git diff omitted a patch section")
    return metadata


def _stream_git_diff(
    repo: Path,
    base_commit: str,
    resolved_head: Optional[str],
    path_filter: list[str],
    *,
    metrics: Optional[dict] = None,
) -> tuple[list[dict], list[dict], str]:
    args = []
    if resolved_head:
        args.append(f"--attr-source={resolved_head}")
    args.extend([
        "diff",
        "--raw",
        "-z",
        "--patch",
        "--no-abbrev",
        "--unified=0",
        "--inter-hunk-context=0",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--find-renames",
        "--diff-algorithm=myers",
        "--indent-heuristic",
        "--ignore-submodules=none",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base_commit,
    ])
    if resolved_head:
        args.append(resolved_head)
    args.append("--")
    args.extend(path_filter)
    process = _popen_git(repo, args)
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise DeltaProtocolError("cannot open git diff pipes")
    reader = _BufferedGitOutput(process.stdout, metrics=metrics)
    try:
        changes = _read_raw_changes(reader)
        metadata = _stream_patch_metadata(reader, changes, metrics=metrics)
        stderr = process.stderr.read().decode("utf-8", "replace")
        returncode = process.wait()
        process.stdout.close()
        process.stderr.close()
    except Exception:
        process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()
        raise
    if returncode != 0:
        raise DeltaProtocolError(
            f"git diff failed: {stderr.strip() or returncode}"
        )
    return changes, metadata, reader.digest.hexdigest()


def _check_diff_attributes(
    repo: Path,
    changes: Iterable[dict],
    *,
    source: Optional[str],
) -> dict[str, str]:
    paths = sorted({
        path
        for change in changes
        for path in (change["path"], change.get("old_path"))
        if path is not None
    })
    if not paths:
        return {}
    args = ["check-attr", "-z", "--stdin"]
    if source:
        args.extend(["--source", source])
    args.append("diff")
    raw = bytes(_run_git(
        repo,
        args,
        binary=True,
        input_data=b"\0".join(
            path.encode("utf-8", "surrogateescape") for path in paths
        ) + b"\0",
    ))
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    if len(tokens) % 3:
        raise DeltaProtocolError("git check-attr returned truncated output")
    attributes = {}
    for index in range(0, len(tokens), 3):
        path = _normalize_path(tokens[index].decode("utf-8", "surrogateescape"))
        if tokens[index + 1] != b"diff":
            raise DeltaProtocolError("git check-attr returned an unexpected attribute")
        value = tokens[index + 2].decode("utf-8", "strict")
        if path in attributes:
            raise DeltaProtocolError("git check-attr returned a duplicate path")
        attributes[path] = value
    if set(attributes) != set(paths):
        raise DeltaProtocolError("git check-attr omitted a changed path")
    return attributes


def _unsafe_diff_attribute(change: dict, attributes: dict[str, str]) -> bool:
    values = {
        attributes.get(path, "unspecified")
        for path in (change["path"], change.get("old_path"))
        if path is not None
    }
    return any(value not in {"set", "unspecified"} for value in values)


def _scan_untracked_file(
    repo: Path,
    path: str,
    *,
    unsafe_attribute: bool,
    metrics: Optional[dict],
) -> tuple[Optional[dict], list[dict], list[str]]:
    candidate = repo / Path(path)
    if candidate.is_symlink():
        summary = _stream_file_summary(candidate, metrics=metrics)
        return summary, [], []
    if not candidate.is_file():
        return None, [], []
    digest = hashlib.sha256()
    size = 0
    newline_count = 0
    last_byte = b""
    contains_nul = False
    entity_metadata = _new_patch_metadata(path)
    pending = bytearray()
    if unsafe_attribute:
        _disable_entity_accumulation(entity_metadata)
    else:
        _note_accumulated_entities(metrics, len(entity_metadata["entities"]))
    with candidate.open("rb") as handle:
        while True:
            chunk = handle.read(BLOB_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            _note_buffered_blob(metrics, len(chunk))
            digest.update(chunk)
            size += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
            chunk_contains_nul = b"\0" in chunk
            contains_nul = contains_nul or chunk_contains_nul
            if chunk_contains_nul:
                _disable_entity_accumulation(entity_metadata)
                pending.clear()
            if entity_metadata["entities_complete"]:
                pending.extend(chunk)
                while True:
                    newline = pending.find(b"\n")
                    if newline < 0:
                        break
                    _scan_entity_line(
                        entity_metadata,
                        bytes(pending[:newline]),
                        metrics=metrics,
                    )
                    del pending[:newline + 1]
                    if not entity_metadata["entities_complete"]:
                        pending.clear()
                        break
                if len(pending) > ENTITY_LINE_MAX_BYTES:
                    _disable_entity_accumulation(entity_metadata)
                    pending.clear()
    if entity_metadata["entities_complete"] and pending:
        _scan_entity_line(entity_metadata, bytes(pending), metrics=metrics)
    summary = {"sha256": digest.hexdigest(), "bytes": size}
    if unsafe_attribute or contains_nul:
        return summary, [], []
    lines = newline_count + int(size > 0 and last_byte != b"\n")
    ranges = (
        [{
            "old_start": 0,
            "old_lines": 0,
            "new_start": 1,
            "new_lines": lines,
        }]
        if lines
        else []
    )
    entities = (
        sorted(entity_metadata["entities"])
        if entity_metadata["entities_complete"]
        else []
    )
    return summary, ranges, entities


def _search_scopes(path: str) -> list[str]:
    parts = PurePosixPath(path).parts
    scopes = set()
    for end in range(1, len(parts)):
        scopes.add("/".join(parts[:end]))
    if parts:
        stem = PurePosixPath(path).with_suffix("").as_posix()
        scopes.add(stem)
        suffix = PurePosixPath(path).suffix.lower().lstrip(".")
        if suffix:
            scopes.add(f"format:{suffix}")
    return sorted(scopes)


def _search_plan(changes: Iterable[dict]) -> dict:
    paths = set()
    entities = set()
    scopes = set()
    deleted_paths = set()
    renamed_paths = []
    queries = set()
    for change in changes:
        path = change["path"]
        paths.add(path)
        if change["status"] == "D":
            deleted_paths.add(path)
        if change["status"] == "R":
            renamed_paths.append({"from": change["old_path"], "to": path})
        for entity in change["entity_ids"]:
            entities.add(entity)
            queries.add(("entity", entity))
        for scope in change["search_scopes"]:
            scopes.add(scope)
            queries.add(("scope", scope))
        queries.add(("path", path))
        if change.get("old_path"):
            queries.add(("path", change["old_path"]))
    return {
        "paths": sorted(paths),
        "deleted_paths": sorted(deleted_paths),
        "renamed_paths": sorted(renamed_paths, key=lambda item: (item["from"], item["to"])),
        "entity_ids": sorted(entities),
        "scopes": sorted(scopes),
        "queries": [
            {"kind": kind, "value": value}
            for kind, value in sorted(queries)
        ],
    }


def _capture_payload(
    repo: Path,
    *,
    base_commit: str,
    resolved_head: Optional[str],
    repository_head: str,
    branch: str,
    source_id: Optional[str] = None,
    frame: Optional[int] = None,
    tile: Optional[str] = None,
    include_untracked: bool,
    path_filter: list[str],
    capture_metrics: dict,
) -> tuple[dict, str]:
    changes, patch_metadata, patch_digest = _stream_git_diff(
        repo,
        base_commit,
        resolved_head,
        path_filter,
        metrics=capture_metrics,
    )
    for change, metadata_value in zip(changes, patch_metadata):
        change["_patch_metadata"] = metadata_value
    seen_paths = {change["path"] for change in changes}

    if include_untracked and resolved_head is None:
        untracked_args = ["ls-files", "--others", "--exclude-standard", "-z"]
        if path_filter:
            untracked_args.extend(["--", *path_filter])
        raw = bytes(_run_git(repo, untracked_args, binary=True))
        for token in raw.split(b"\0"):
            if not token:
                continue
            path = _normalize_path(token.decode("utf-8", "surrogateescape"))
            if path not in seen_paths:
                changes.append({"status": "A", "path": path, "_untracked": True})
                seen_paths.add(path)
    attributes = _check_diff_attributes(
        repo,
        changes,
        source=resolved_head,
    )
    enriched = []
    if changes:
        with _GitBlobBatch(repo, metrics=capture_metrics) as blobs:
            for change in changes:
                path = change["path"]
                untracked = bool(change.pop("_untracked", False))
                metadata_value = change.pop("_patch_metadata", None)
                unsafe_attribute = _unsafe_diff_attribute(change, attributes)
                before = (
                    blobs.summary(
                        base_commit,
                        change.get("old_path", path),
                    )
                    if change["status"] != "A"
                    else None
                )
                if untracked:
                    after, line_ranges, entity_ids = _scan_untracked_file(
                        repo,
                        path,
                        unsafe_attribute=unsafe_attribute,
                        metrics=capture_metrics,
                    )
                else:
                    after = (
                        blobs.summary(resolved_head, path)
                        if resolved_head and change["status"] != "D"
                        else (
                            _stream_file_summary(
                                repo / Path(path),
                                metrics=capture_metrics,
                            )
                            if change["status"] != "D"
                            else None
                        )
                    )
                    if metadata_value is None:
                        raise DeltaProtocolError(
                            f"{path}: missing streamed patch metadata"
                        )
                    unsafe_patch = (
                        unsafe_attribute
                        or metadata_value["binary"]
                        or not metadata_value["coordinates_complete"]
                    )
                    line_ranges = (
                        []
                        if unsafe_patch
                        else metadata_value["line_ranges"]
                    )
                    entity_ids = (
                        sorted(metadata_value["entities"])
                        if (
                            not unsafe_patch
                            and metadata_value["entities_complete"]
                        )
                        else []
                    )
                record = {
                    **change,
                    "before": before,
                    "after": after,
                    "line_ranges": line_ranges,
                    "entity_ids": entity_ids,
                    "search_scopes": _search_scopes(path),
                }
                enriched.append(record)
    enriched.sort(key=lambda item: (item["path"], item.get("old_path", ""), item["status"]))

    source = {
        "id": source_id or branch or "detached-worktree",
        "branch": branch or None,
    }
    if frame is not None:
        source["frame"] = frame
    if tile is not None:
        source["tile"] = str(tile)

    payload = {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "repository": {
            "base_commit": base_commit,
            "head_commit": repository_head,
            "includes_worktree": resolved_head is None,
            "path_filter": path_filter,
            "line_coordinates": LINE_COORDINATES,
        },
        "source": source,
        "changes": enriched,
        "search_plan": _search_plan(enriched),
    }
    return payload, patch_digest


def _publish_capture_metrics(
    metrics: Optional[dict],
    capture_metrics: dict,
) -> None:
    if metrics is not None:
        metrics.clear()
        metrics.update(capture_metrics)


def capture_worktree(
    repo: Path,
    base: str,
    *,
    head: Optional[str] = None,
    source_id: Optional[str] = None,
    frame: Optional[int] = None,
    tile: Optional[str] = None,
    include_untracked: bool = True,
    paths: Optional[Iterable[str]] = None,
    metrics: Optional[dict] = None,
) -> dict:
    """Capture a deterministic semantic manifest for one worktree diff."""
    repo = repo.resolve()
    if not (repo / ".git").exists():
        probe = str(_run_git(repo, ["rev-parse", "--git-dir"], check=False)).strip()
        if not probe:
            raise DeltaProtocolError(f"{repo} is not a git worktree")
    if frame is not None and (
        isinstance(frame, bool)
        or not isinstance(frame, int)
        or frame < 0
    ):
        raise DeltaProtocolError("frame must be non-negative")
    requested_base = _resolve_commit(repo, base)
    resolved_head = _resolve_commit(repo, head) if head else None
    base_commit = (
        _merge_base(repo, requested_base, resolved_head)
        if resolved_head
        else requested_base
    )
    path_filter = (
        sorted({_normalize_path(path) for path in paths})
        if paths is not None
        else []
    )
    capture_metrics = {
        "blob_stream_chunk_bytes": BLOB_STREAM_CHUNK_BYTES,
        "max_buffered_blob_bytes": 0,
        "patch_line_max_bytes": PATCH_LINE_MAX_BYTES,
        "max_buffered_patch_bytes": 0,
        "max_accumulated_entity_ids": 0,
        "worktree_capture_max_attempts": WORKTREE_CAPTURE_MAX_ATTEMPTS,
        "worktree_capture_attempts": 0,
    }

    def capture_attempt() -> tuple[dict, str]:
        repository_head = resolved_head or _resolve_commit(repo, "HEAD")
        branch = str(_run_git(repo, ["branch", "--show-current"])).strip()
        return _capture_payload(
            repo,
            base_commit=base_commit,
            resolved_head=resolved_head,
            repository_head=repository_head,
            branch=branch,
            source_id=source_id,
            frame=frame,
            tile=tile,
            include_untracked=include_untracked,
            path_filter=path_filter,
            capture_metrics=capture_metrics,
        )

    if resolved_head is not None:
        capture_metrics["worktree_capture_attempts"] = 1
        payload, _ = capture_attempt()
    else:
        previous: Optional[tuple[dict, str]] = None
        payload = None
        for attempt in range(1, WORKTREE_CAPTURE_MAX_ATTEMPTS + 1):
            capture_metrics["worktree_capture_attempts"] = attempt
            try:
                candidate = capture_attempt()
            except OSError:
                candidate = None
            if candidate is not None and previous is not None:
                if candidate == previous:
                    payload = candidate[0]
                    break
            previous = candidate
        if payload is None:
            _publish_capture_metrics(metrics, capture_metrics)
            raise DeltaProtocolError(
                "worktree changed during capture after "
                f"{WORKTREE_CAPTURE_MAX_ATTEMPTS} attempts"
            )

    _publish_capture_metrics(metrics, capture_metrics)
    return validate_manifest(_with_id(payload, "manifest_id"))


def _require_list_of_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise DeltaProtocolError(f"{field} must be a list of non-empty strings")
    return value


def _range_indexes(line_range: dict) -> tuple[int, int]:
    old_index = (
        line_range["old_start"]
        if line_range["old_lines"] == 0
        else line_range["old_start"] - 1
    )
    new_index = (
        line_range["new_start"]
        if line_range["new_lines"] == 0
        else line_range["new_start"] - 1
    )
    return old_index, new_index


def _validate_line_ranges(line_ranges: object, field: str) -> list[dict]:
    if not isinstance(line_ranges, list):
        raise DeltaProtocolError(f"{field} must be an array")
    delta = 0
    previous_old_end: Optional[int] = None
    previous_new_end: Optional[int] = None
    for range_index, line_range in enumerate(line_ranges):
        item_field = f"{field}[{range_index}]"
        if (
            not isinstance(line_range, dict)
            or set(line_range)
            != {"old_start", "old_lines", "new_start", "new_lines"}
            or any(
                isinstance(line_range[value], bool)
                or not isinstance(line_range[value], int)
                or line_range[value] < 0
                for value in line_range
            )
            or (
                line_range["old_lines"] > 0
                and line_range["old_start"] == 0
            )
            or (
                line_range["new_lines"] > 0
                and line_range["new_start"] == 0
            )
            or (
                line_range["old_lines"] == 0
                and line_range["new_lines"] == 0
            )
        ):
            raise DeltaProtocolError(f"{item_field} is invalid")
        old_index, new_index = _range_indexes(line_range)
        if new_index != old_index + delta:
            raise DeltaProtocolError(
                f"{item_field} mixes incompatible diff coordinates"
            )
        if (
            previous_old_end is not None
            and (
                old_index <= previous_old_end
                or new_index <= previous_new_end
            )
        ):
            raise DeltaProtocolError(
                f"{field} is not canonical zero-context hunk order"
            )
        previous_old_end = old_index + line_range["old_lines"]
        previous_new_end = new_index + line_range["new_lines"]
        delta += line_range["new_lines"] - line_range["old_lines"]
    return line_ranges


def validate_manifest(manifest: dict) -> dict:
    """Validate a manifest strictly and return it unchanged."""
    if not isinstance(manifest, dict):
        raise DeltaProtocolError("manifest must be an object")
    if manifest.get("schema") != SCHEMA:
        raise DeltaProtocolError(f"unsupported schema {manifest.get('schema')!r}")
    producer = manifest.get("producer")
    if (
        not isinstance(producer, dict)
        or producer.get("name") != "twin-dreamcatcher"
        or not isinstance(producer.get("version"), str)
    ):
        raise DeltaProtocolError("producer is invalid")
    repository = manifest.get("repository")
    required_repository_fields = {
        "base_commit",
        "head_commit",
        "includes_worktree",
        "path_filter",
    }
    if (
        not isinstance(repository, dict)
        or not required_repository_fields.issubset(repository)
        or set(repository) - required_repository_fields - {"line_coordinates"}
    ):
        raise DeltaProtocolError("repository must be an object")
    for field in ("base_commit", "head_commit"):
        if not COMMIT_PATTERN.fullmatch(str(repository.get(field, ""))):
            raise DeltaProtocolError(f"repository.{field} is invalid")
    if not isinstance(repository.get("includes_worktree"), bool):
        raise DeltaProtocolError("repository.includes_worktree must be boolean")
    if repository.get("line_coordinates", LINE_COORDINATES) != LINE_COORDINATES:
        raise DeltaProtocolError(
            "repository.line_coordinates is unsupported"
        )
    path_filter = repository.get("path_filter")
    if (
        not isinstance(path_filter, list)
        or any(not isinstance(path, str) for path in path_filter)
    ):
        raise DeltaProtocolError("repository.path_filter must be an array")
    normalized_filter = sorted({_normalize_path(path) for path in path_filter})
    if path_filter != normalized_filter:
        raise DeltaProtocolError(
            "repository.path_filter must be unique and sorted"
        )
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("id"), str):
        raise DeltaProtocolError("source.id is required")
    if set(source) - {"id", "branch", "frame", "tile"}:
        raise DeltaProtocolError("source contains unsupported fields")
    if source.get("branch") is not None and not isinstance(source["branch"], str):
        raise DeltaProtocolError("source.branch must be a string or null")
    if "frame" in source and (
        isinstance(source["frame"], bool)
        or not isinstance(source["frame"], int)
        or source["frame"] < 0
    ):
        raise DeltaProtocolError("source.frame must be a non-negative integer")
    if "tile" in source and (
        not isinstance(source["tile"], str) or not source["tile"]
    ):
        raise DeltaProtocolError("source.tile must be a non-empty string")
    changes = manifest.get("changes")
    if not isinstance(changes, list):
        raise DeltaProtocolError("changes must be an array")
    seen = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise DeltaProtocolError(f"changes[{index}] must be an object")
        status = change.get("status")
        if status not in STATUSES:
            raise DeltaProtocolError(f"changes[{index}].status is invalid")
        allowed = {
            "status",
            "path",
            "old_path",
            "similarity",
            "before",
            "after",
            "line_ranges",
            "entity_ids",
            "search_scopes",
        }
        if set(change) - allowed:
            raise DeltaProtocolError(f"changes[{index}] contains unsupported fields")
        path = _normalize_path(change.get("path"))
        if path in seen:
            raise DeltaProtocolError(f"duplicate changed path {path}")
        seen.add(path)
        if status in {"R", "C"}:
            _normalize_path(change.get("old_path"))
        elif "old_path" in change:
            raise DeltaProtocolError(
                f"changes[{index}].old_path is only valid for rename/copy"
            )
        for side in ("before", "after"):
            summary = change.get(side)
            if summary is None:
                continue
            if not isinstance(summary, dict):
                raise DeltaProtocolError(f"changes[{index}].{side} must be an object")
            if not HASH_PATTERN.fullmatch(str(summary.get("sha256", ""))):
                raise DeltaProtocolError(f"changes[{index}].{side}.sha256 is invalid")
            if (
                isinstance(summary.get("bytes"), bool)
                or not isinstance(summary.get("bytes"), int)
                or summary["bytes"] < 0
            ):
                raise DeltaProtocolError(f"changes[{index}].{side}.bytes is invalid")
        if status == "A" and (change.get("before") is not None or change.get("after") is None):
            raise DeltaProtocolError(f"changes[{index}] has invalid add blobs")
        if status == "D" and (change.get("before") is None or change.get("after") is not None):
            raise DeltaProtocolError(f"changes[{index}] has invalid delete blobs")
        if status not in {"A", "D"} and (
            change.get("before") is None or change.get("after") is None
        ):
            raise DeltaProtocolError(f"changes[{index}] requires before and after blobs")
        _require_list_of_strings(change.get("entity_ids"), f"changes[{index}].entity_ids")
        _require_list_of_strings(
            change.get("search_scopes"), f"changes[{index}].search_scopes"
        )
        _validate_line_ranges(
            change.get("line_ranges"),
            f"changes[{index}].line_ranges",
        )
    if changes != sorted(
        changes,
        key=lambda item: (item["path"], item.get("old_path", ""), item["status"]),
    ):
        raise DeltaProtocolError("changes must be deterministically sorted")
    plan = manifest.get("search_plan")
    if not isinstance(plan, dict):
        raise DeltaProtocolError("search_plan must be an object")
    if plan != _search_plan(changes):
        raise DeltaProtocolError("search_plan does not match changed records")
    payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    expected_id = _content_id(payload)
    if manifest.get("manifest_id") != expected_id:
        raise DeltaProtocolError("manifest_id does not match canonical payload")
    return manifest


def _repository_semantics(
    manifest: dict,
    *,
    conservative_paths: set[str],
) -> dict:
    repository = manifest["repository"]
    legacy = "line_coordinates" not in repository
    changes = []
    for change in manifest["changes"]:
        normalized = change
        if (
            legacy
            and change["path"] in conservative_paths
            and not change["line_ranges"]
            and change["entity_ids"] == [f"path:{change['path']}"]
        ):
            normalized = {**change, "entity_ids": []}
        changes.append(normalized)
    return {
        "repository": {
            "base_commit": repository["base_commit"],
            "head_commit": repository["head_commit"],
            "includes_worktree": repository["includes_worktree"],
            "path_filter": repository["path_filter"],
        },
        "source": manifest["source"],
        "changes": changes,
        "search_plan": _search_plan(changes),
    }


def verify_manifest_repository(manifest: dict, repo: Path) -> dict:
    """Prove manifest hashes match its declared base/head or live worktree."""
    manifest = validate_manifest(manifest)
    repo = repo.resolve()
    repository = manifest["repository"]
    base_commit = _resolve_commit(repo, repository["base_commit"])
    head_commit = _resolve_commit(repo, repository["head_commit"])
    source = manifest["source"]
    expected = capture_worktree(
        repo,
        base_commit,
        head=None if repository["includes_worktree"] else head_commit,
        source_id=source["id"],
        frame=source.get("frame"),
        tile=source.get("tile"),
        include_untracked=repository["includes_worktree"],
        paths=repository["path_filter"] or None,
    )
    conservative_paths = {
        change["path"]
        for change in expected["changes"]
        if not change["line_ranges"] and not change["entity_ids"]
    }
    if _repository_semantics(
        expected,
        conservative_paths=conservative_paths,
    ) != _repository_semantics(
        manifest,
        conservative_paths=conservative_paths,
    ):
        raise DeltaProtocolError(
            "manifest does not cover the exact declared repository diff"
        )
    return manifest


def verify_manifest_tree(manifest: dict, root: Path) -> dict:
    """Prove every post-diff blob matches a materialized non-git tree."""
    manifest = validate_manifest(manifest)
    root = root.resolve()
    for change in manifest["changes"]:
        candidate = root / Path(change["path"])
        try:
            candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise DeltaProtocolError(
                f"{change['path']}: path escapes materialized tree"
            ) from exc
        after = _stream_file_summary(candidate)
        if after != change["after"]:
            raise DeltaProtocolError(
                f"{change['path']}: materialized blob does not match manifest"
            )
    return manifest


def load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeltaProtocolError(f"cannot read {path}: {exc}") from exc
    return validate_manifest(value)


def write_manifest(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _base_intervals(line_ranges: list[dict]) -> list[tuple[int, int]]:
    """Map hunks to a shared-base coordinate system.

    Base lines use even coordinates. Pure insertions use the odd coordinate
    between two base lines, so two inserts at one anchor conflict without
    falsely colliding with an edit to either neighboring line.
    """
    intervals = []
    for line_range in line_ranges:
        old_start = line_range["old_start"]
        old_lines = line_range["old_lines"]
        if old_lines == 0:
            anchor = old_start * 2 + 1
            intervals.append((anchor, anchor))
        else:
            intervals.append((
                old_start * 2,
                (old_start + old_lines - 1) * 2,
            ))
    return intervals


def _ranges_overlap(left: list[dict], right: list[dict]) -> bool:
    if not left or not right:
        return True
    for left_start, left_end in _base_intervals(left):
        for right_start, right_end in _base_intervals(right):
            if left_start <= right_end and right_start <= left_end:
                return True
    return False


def _manifest_order(manifest: dict) -> tuple:
    source = manifest["source"]
    frame = source.get("frame")
    return (
        frame
        if isinstance(frame, int) and not isinstance(frame, bool)
        else sys.maxsize,
        str(source.get("tile") or ""),
        str(source.get("id") or ""),
        manifest["manifest_id"],
    )


def _validate_search_plan(plan: object) -> dict:
    if not isinstance(plan, dict) or set(plan) != {
        "paths",
        "deleted_paths",
        "renamed_paths",
        "entity_ids",
        "scopes",
        "queries",
    }:
        raise DeltaProtocolError("batch search_plan is invalid")
    for field in ("paths", "deleted_paths"):
        values = plan[field]
        if (
            not isinstance(values, list)
            or values != sorted(set(values))
            or any(_normalize_path(value) != value for value in values)
        ):
            raise DeltaProtocolError(f"batch search_plan.{field} is invalid")
    for field in ("entity_ids", "scopes"):
        values = plan[field]
        if (
            not isinstance(values, list)
            or values != sorted(set(values))
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise DeltaProtocolError(f"batch search_plan.{field} is invalid")
    renamed = plan["renamed_paths"]
    if not isinstance(renamed, list):
        raise DeltaProtocolError("batch search_plan.renamed_paths is invalid")
    rename_pairs = []
    for item in renamed:
        if not isinstance(item, dict) or set(item) != {"from", "to"}:
            raise DeltaProtocolError("batch renamed path is invalid")
        rename_pairs.append((
            _normalize_path(item["from"]),
            _normalize_path(item["to"]),
        ))
    if rename_pairs != sorted(set(rename_pairs)):
        raise DeltaProtocolError("batch renamed paths are not sorted and unique")
    queries = plan["queries"]
    if not isinstance(queries, list):
        raise DeltaProtocolError("batch search_plan.queries is invalid")
    query_pairs = []
    for query in queries:
        if (
            not isinstance(query, dict)
            or set(query) != {"kind", "value"}
            or query["kind"] not in {"entity", "path", "scope"}
            or not isinstance(query["value"], str)
            or not query["value"]
        ):
            raise DeltaProtocolError("batch search query is invalid")
        if query["kind"] == "path":
            _normalize_path(query["value"])
        query_pairs.append((query["kind"], query["value"]))
    if query_pairs != sorted(set(query_pairs)):
        raise DeltaProtocolError("batch search queries are not sorted and unique")
    return plan


def validate_batch(batch: dict) -> dict:
    """Strictly validate a deterministic batch artifact."""
    if not isinstance(batch, dict) or set(batch) != {
        "schema",
        "producer",
        "base_commit",
        "ready",
        "ordered_manifest_ids",
        "sources",
        "collisions",
        "conflicts",
        "search_plan",
        "batch_id",
    }:
        raise DeltaProtocolError("batch has unsupported fields")
    if batch["schema"] != BATCH_SCHEMA:
        raise DeltaProtocolError("unsupported batch schema")
    producer = batch["producer"]
    if (
        not isinstance(producer, dict)
        or set(producer) != {"name", "version"}
        or producer["name"] != "twin-dreamcatcher"
        or not isinstance(producer["version"], str)
        or not producer["version"]
    ):
        raise DeltaProtocolError("batch producer is invalid")
    if not COMMIT_PATTERN.fullmatch(str(batch["base_commit"])):
        raise DeltaProtocolError("batch base_commit is invalid")
    if not isinstance(batch["ready"], bool):
        raise DeltaProtocolError("batch ready must be boolean")
    manifest_ids = batch["ordered_manifest_ids"]
    if (
        not isinstance(manifest_ids, list)
        or not manifest_ids
        or len(manifest_ids) != len(set(manifest_ids))
        or any(
            not isinstance(manifest_id, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_id)
            for manifest_id in manifest_ids
        )
    ):
        raise DeltaProtocolError("batch ordered_manifest_ids are invalid")
    sources = batch["sources"]
    if not isinstance(sources, list) or len(sources) != len(manifest_ids):
        raise DeltaProtocolError("batch sources are invalid")
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) - {"id", "branch", "frame", "tile"}
            or not isinstance(source.get("id"), str)
            or not source["id"]
            or (
                source.get("branch") is not None
                and not isinstance(source.get("branch"), str)
            )
            or (
                "frame" in source
                and (
                    not isinstance(source["frame"], int)
                    or isinstance(source["frame"], bool)
                    or source["frame"] < 0
                )
            )
            or (
                "tile" in source
                and (
                    not isinstance(source["tile"], str)
                    or not source["tile"]
                )
            )
        ):
            raise DeltaProtocolError("batch source is invalid")

    def validate_collisions(value: object, field: str) -> list[dict]:
        if not isinstance(value, list):
            raise DeltaProtocolError(f"batch {field} must be an array")
        paths = []
        for collision in value:
            if (
                not isinstance(collision, dict)
                or set(collision) != {"path", "kind", "manifest_ids"}
                or collision["kind"]
                not in {"identical", "disjoint-hunks", "conflict"}
            ):
                raise DeltaProtocolError(f"batch {field} record is invalid")
            path = _normalize_path(collision["path"])
            ids = collision["manifest_ids"]
            if (
                not isinstance(ids, list)
                or len(ids) < 2
                or ids != sorted(set(ids))
                or any(manifest_id not in manifest_ids for manifest_id in ids)
            ):
                raise DeltaProtocolError(
                    f"batch {field} manifest IDs are invalid"
                )
            paths.append(path)
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise DeltaProtocolError(f"batch {field} is not sorted and unique")
        return value

    collisions = validate_collisions(batch["collisions"], "collisions")
    conflicts = validate_collisions(batch["conflicts"], "conflicts")
    expected_conflicts = [
        collision for collision in collisions
        if collision["kind"] == "conflict"
    ]
    if conflicts != expected_conflicts or batch["ready"] != (not conflicts):
        raise DeltaProtocolError("batch ready/conflicts fields disagree")
    _validate_search_plan(batch["search_plan"])
    payload = {key: value for key, value in batch.items() if key != "batch_id"}
    if batch["batch_id"] != _content_id(payload):
        raise DeltaProtocolError("batch_id does not match canonical payload")
    return batch


def batch_manifests(manifests: Iterable[dict]) -> dict:
    """Fan in worktree manifests and classify path collisions deterministically."""
    validated = sorted(
        (validate_manifest(dict(manifest)) for manifest in manifests),
        key=_manifest_order,
    )
    if not validated:
        raise DeltaProtocolError("at least one manifest is required")
    manifest_ids = [manifest["manifest_id"] for manifest in validated]
    if len(manifest_ids) != len(set(manifest_ids)):
        raise DeltaProtocolError("batch contains duplicate manifests")
    bases = {manifest["repository"]["base_commit"] for manifest in validated}
    if len(bases) != 1:
        raise DeltaProtocolError("parallel manifests must share one base commit")

    by_path: dict[str, list[tuple[dict, dict, str]]] = {}
    for manifest in validated:
        for change in manifest["changes"]:
            by_path.setdefault(change["path"], []).append(
                (manifest, change, "target")
            )
            if change["status"] == "R":
                by_path.setdefault(change["old_path"], []).append(
                    (manifest, change, "rename-source")
                )

    collisions = []
    conflicts = []
    for path, entries in sorted(by_path.items()):
        if len(entries) < 2:
            continue
        ids = sorted({
            manifest["manifest_id"] for manifest, _, _ in entries
        })
        semantic_changes = {
            (
                change["status"],
                change["path"],
                change.get("old_path"),
                change["after"]["sha256"] if change.get("after") else None,
            )
            for _, change, _ in entries
        }
        roles = {role for _, _, role in entries}
        statuses = {change["status"] for _, change, _ in entries}
        if len(semantic_changes) == 1:
            kind = "identical"
            ready = True
        elif "rename-source" in roles:
            kind = "conflict"
            ready = False
        elif statuses <= {"M"} and all(
            not _ranges_overlap(left[1]["line_ranges"], right[1]["line_ranges"])
            for index, left in enumerate(entries)
            for right in entries[index + 1:]
        ):
            kind = "disjoint-hunks"
            ready = True
        else:
            kind = "conflict"
            ready = False
        record = {
            "path": path,
            "kind": kind,
            "manifest_ids": ids,
        }
        collisions.append(record)
        if not ready:
            conflicts.append(record)

    plans = [manifest["search_plan"] for manifest in validated]
    merged_plan = {
        "paths": sorted({value for plan in plans for value in plan["paths"]}),
        "deleted_paths": sorted({
            value for plan in plans for value in plan["deleted_paths"]
        }),
        "renamed_paths": sorted(
            {
                (item["from"], item["to"])
                for plan in plans
                for item in plan.get("renamed_paths", [])
            }
        ),
        "entity_ids": sorted({
            value for plan in plans for value in plan["entity_ids"]
        }),
        "scopes": sorted({value for plan in plans for value in plan["scopes"]}),
        "queries": sorted(
            {
                (item["kind"], item["value"])
                for plan in plans
                for item in plan.get("queries", [])
            }
        ),
    }
    merged_plan["renamed_paths"] = [
        {"from": old, "to": new} for old, new in merged_plan["renamed_paths"]
    ]
    merged_plan["queries"] = [
        {"kind": kind, "value": value} for kind, value in merged_plan["queries"]
    ]
    payload = {
        "schema": BATCH_SCHEMA,
        "producer": PRODUCER,
        "base_commit": next(iter(bases)),
        "ready": not conflicts,
        "ordered_manifest_ids": [
            manifest["manifest_id"] for manifest in validated
        ],
        "sources": [manifest["source"] for manifest in validated],
        "collisions": collisions,
        "conflicts": conflicts,
        "search_plan": merged_plan,
    }
    return validate_batch(_with_id(payload, "batch_id"))


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Capture and reduce Dreamcatcher git-worktree deltas"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("repo")
    capture.add_argument("--base", required=True)
    capture.add_argument("--head")
    capture.add_argument("--source-id")
    capture.add_argument("--frame", type=int)
    capture.add_argument("--tile")
    capture.add_argument("--path", action="append", dest="paths")
    capture.add_argument("--no-untracked", action="store_true")
    capture.add_argument("--output")

    validate = sub.add_parser("validate")
    validate.add_argument("manifest")

    batch = sub.add_parser("batch")
    batch.add_argument("manifests", nargs="+")
    batch.add_argument("--output")

    args = parser.parse_args()
    try:
        if args.command == "capture":
            value = capture_worktree(
                Path(args.repo),
                args.base,
                head=args.head,
                source_id=args.source_id,
                frame=args.frame,
                tile=args.tile,
                include_untracked=not args.no_untracked,
                paths=args.paths,
            )
            if args.output:
                write_manifest(Path(args.output), value)
            else:
                print(json.dumps(value, indent=2, sort_keys=True))
        elif args.command == "validate":
            value = load_manifest(Path(args.manifest))
            print(json.dumps({
                "ok": True,
                "manifest_id": value["manifest_id"],
                "changes": len(value["changes"]),
            }, indent=2))
        else:
            value = batch_manifests(
                load_manifest(Path(path)) for path in args.manifests
            )
            if args.output:
                write_manifest(Path(args.output), value)
            else:
                print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except DeltaProtocolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli())
