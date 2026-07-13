#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile a verified local closure or pinned legacy source into a world pack."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Set, Tuple

from world_pack_compiler import (
    COMPILER_IMPLEMENTATION_SHA256,
    CompilationError,
    LegacyCompilationError,
    canonical_json_v2,
    compile_legacy_v1,
    compile_world_pack,
    load_trusted_profile,
    parse_json_v2,
)
from world_pack_compiler.core import _safe_path

BUILD_REPORT_PATH = "build-report.json"


class CLIError(ValueError):
    """Raised for a safe deterministic CLI refusal."""


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_STAGING_PREFIX = ".world-pack-staging-"
_STAGING_RANDOM_BYTES = 16
_STAGING_CREATE_ATTEMPTS = 128


def _lstat_mode(path: Path) -> Optional[int]:
    try:
        return path.lstat().st_mode
    except FileNotFoundError:
        return None


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        mode = _lstat_mode(current)
        if mode is not None and stat.S_ISLNK(mode):
            return True
    return False


def _require_secure_filesystem_primitives() -> None:
    missing = []
    for name in ("O_DIRECTORY", "O_NOFOLLOW"):
        if not getattr(os, name, 0):
            missing.append(name)
    for name in ("open", "mkdir", "stat", "rename", "unlink", "rmdir"):
        function = getattr(os, name, None)
        if function is None or function not in os.supports_dir_fd:
            missing.append(name + "(dir_fd)")
    if os.stat not in os.supports_follow_symlinks:
        missing.append("stat(follow_symlinks)")
    if os.listdir not in os.supports_fd:
        missing.append("listdir(fd)")
    for name in ("fchmod", "fsync", "fstat", "geteuid"):
        if not hasattr(os, name):
            missing.append(name)
    if missing:
        raise CLIError(
            "secure output publication primitives unavailable: {}".format(
                ", ".join(sorted(missing))
            )
        )


def _identity(value: os.stat_result) -> Tuple[int, int]:
    return value.st_dev, value.st_ino


def _assert_trusted_directory(value: os.stat_result, location: str) -> None:
    if not stat.S_ISDIR(value.st_mode):
        raise CLIError(
            "{} must be an existing regular directory".format(location)
        )
    if value.st_uid not in (0, os.geteuid()):
        raise CLIError("{} is not owned by a trusted principal".format(location))
    if value.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise CLIError("{} is writable by an untrusted principal".format(location))


def _open_trusted_directory(path: Path) -> int:
    absolute = path.absolute()
    if absolute.anchor != os.sep:
        raise CLIError("output path must use an absolute POSIX path")
    descriptor = os.open(os.sep, _DIRECTORY_FLAGS)
    try:
        _assert_trusted_directory(os.fstat(descriptor), "output parent")
        for part in absolute.parts[1:]:
            if part in ("", ".", ".."):
                raise CLIError("output parent path is unsafe")
            try:
                linked = os.stat(
                    part, dir_fd=descriptor, follow_symlinks=False
                )
            except FileNotFoundError as exc:
                raise CLIError(
                    "output parent must be an existing regular directory"
                ) from exc
            if stat.S_ISLNK(linked.st_mode):
                raise CLIError("output path contains a symlink")
            if not stat.S_ISDIR(linked.st_mode):
                raise CLIError(
                    "output parent must be an existing regular directory"
                )
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                opened = os.fstat(child)
                if _identity(linked) != _identity(opened):
                    raise CLIError("output parent changed during validation")
                _assert_trusted_directory(opened, "output parent")
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _require_parent_identity(path: Path, descriptor: int) -> None:
    held = os.fstat(descriptor)
    _assert_trusted_directory(held, "output parent")
    current_descriptor = _open_trusted_directory(path)
    try:
        current = os.fstat(current_descriptor)
        if _identity(current) != _identity(held):
            raise CLIError("output parent changed during publication")
    finally:
        os.close(current_descriptor)


def _validate_output_entry(parent_descriptor: int, name: str) -> None:
    try:
        linked = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except FileNotFoundError:
        return
    if stat.S_ISLNK(linked.st_mode):
        raise CLIError("output path contains a symlink")
    if not stat.S_ISDIR(linked.st_mode):
        raise CLIError("output must be a regular directory")
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        if _identity(linked) != _identity(opened):
            raise CLIError("output directory changed during validation")
        _assert_trusted_directory(opened, "output directory")
        if os.listdir(descriptor):
            raise CLIError("output directory must be empty")
    finally:
        os.close(descriptor)


def _validate_output(output: Path) -> None:
    _require_secure_filesystem_primitives()
    if not output.name or output.name in (".", ".."):
        raise CLIError("output must name a directory below its parent")
    parent_descriptor = _open_trusted_directory(output.parent)
    try:
        _validate_output_entry(parent_descriptor, output.name)
        _require_parent_identity(output.parent, parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _load_closure(path: Path, maximum: int) -> Mapping[str, object]:
    if _has_symlink_component(path) or path.is_symlink() or not path.is_file():
        raise CLIError("closure must be a regular non-symlink file")
    size = path.stat().st_size
    if size < 1 or size > maximum:
        raise CLIError("closure file size is outside trusted limits")
    value = parse_json_v2(
        path.read_bytes(), require_stored=True, max_bytes=maximum
    )
    if not isinstance(value, dict):
        raise CLIError("closure root must be an object")
    return value


def _compare_expected(
    label: str, expected: Optional[str], actual: str
) -> None:
    if expected is not None and expected != actual:
        raise CLIError(
            "{} mismatch: expected {}, computed {}".format(
                label, expected, actual
            )
        )


def _require_entry_identity(
    parent_descriptor: int,
    name: str,
    held_descriptor: int,
    expected: Tuple[int, int],
) -> None:
    held = os.fstat(held_descriptor)
    if not stat.S_ISDIR(held.st_mode) or _identity(held) != expected:
        raise CLIError("staging directory identity changed")
    try:
        linked = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except FileNotFoundError as exc:
        raise CLIError("staging directory identity changed") from exc
    if not stat.S_ISDIR(linked.st_mode) or _identity(linked) != expected:
        raise CLIError("staging directory identity changed")
    descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _identity(opened) != expected
            or _identity(linked) != _identity(opened)
        ):
            raise CLIError("staging directory identity changed")
    finally:
        os.close(descriptor)


def _create_private_staging(
    parent_descriptor: int,
) -> Tuple[str, int, Tuple[int, int]]:
    for _ in range(_STAGING_CREATE_ATTEMPTS):
        name = _STAGING_PREFIX + secrets.token_hex(_STAGING_RANDOM_BYTES)
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        descriptor = None
        try:
            descriptor = os.open(
                name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor
            )
            opened = os.fstat(descriptor)
            linked = os.stat(
                name, dir_fd=parent_descriptor, follow_symlinks=False
            )
            if (
                not stat.S_ISDIR(opened.st_mode)
                or _identity(opened) != _identity(linked)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) != 0o700
            ):
                raise CLIError("private staging directory creation was unsafe")
            return name, descriptor, _identity(opened)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.rmdir(name, dir_fd=parent_descriptor)
            except OSError:
                pass
            raise
    raise CLIError("unable to allocate a private random staging directory")


def _open_staging_directory(
    root_descriptor: int,
    parts: Sequence[str],
    *,
    create: bool,
) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            linked = os.stat(
                part, dir_fd=descriptor, follow_symlinks=False
            )
            if not stat.S_ISDIR(linked.st_mode):
                raise CLIError("staging tree contains an unsafe directory entry")
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            try:
                opened = os.fstat(child)
                if (
                    _identity(linked) != _identity(opened)
                    or opened.st_uid != os.geteuid()
                    or opened.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                ):
                    raise CLIError(
                        "staging tree directory identity changed"
                    )
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write to compiler output")
        remaining = remaining[written:]


def _write_staging_file(
    staging_descriptor: int,
    relative: str,
    data: bytes,
    directories: Set[Tuple[str, ...]],
) -> None:
    _safe_path(relative, "compiler-output")
    parts = relative.split("/")
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise CLIError("compiler returned an unsafe output path")
    parent_parts = tuple(parts[:-1])
    for length in range(len(parent_parts) + 1):
        directories.add(parent_parts[:length])
    parent_descriptor = _open_staging_directory(
        staging_descriptor, parent_parts, create=True
    )
    try:
        descriptor = os.open(
            parts[-1],
            _FILE_FLAGS,
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            _write_all(descriptor, data)
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def _finalize_staging_directories(
    staging_descriptor: int,
    directories: Set[Tuple[str, ...]],
) -> None:
    for parts in sorted(
        directories, key=lambda item: (len(item), item), reverse=True
    ):
        descriptor = _open_staging_directory(
            staging_descriptor, parts, create=False
        )
        try:
            os.fchmod(descriptor, 0o755)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _clear_directory(descriptor: int) -> None:
    for name in os.listdir(descriptor):
        try:
            linked = os.stat(
                name, dir_fd=descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(linked.st_mode):
            try:
                child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError:
                continue
            try:
                if _identity(os.fstat(child)) != _identity(linked):
                    continue
                _clear_directory(child)
            finally:
                os.close(child)
            try:
                current = os.stat(
                    name, dir_fd=descriptor, follow_symlinks=False
                )
                if (
                    stat.S_ISDIR(current.st_mode)
                    and _identity(current) == _identity(linked)
                ):
                    os.rmdir(name, dir_fd=descriptor)
            except OSError:
                pass
        else:
            try:
                os.unlink(name, dir_fd=descriptor)
            except OSError:
                pass
    try:
        os.fsync(descriptor)
    except OSError:
        pass


def _cleanup_original_staging(
    parent_descriptor: int,
    staging_descriptor: int,
    staging_identity: Tuple[int, int],
    linked_name: str,
) -> None:
    try:
        _clear_directory(staging_descriptor)
    except OSError:
        return
    try:
        linked = os.stat(
            linked_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            stat.S_ISDIR(linked.st_mode)
            and _identity(linked) == staging_identity
        ):
            os.rmdir(linked_name, dir_fd=parent_descriptor)
    except OSError:
        pass


def _write_atomic(
    output: Path,
    files: Mapping[str, bytes],
    report: Mapping[str, object],
    *,
    _event_hook: Optional[Callable[[str, Path], None]] = None,
) -> None:
    _require_secure_filesystem_primitives()
    if not output.name or output.name in (".", ".."):
        raise CLIError("output must name a directory below its parent")
    if BUILD_REPORT_PATH in files:
        raise CLIError("compiler output conflicts with the build report")
    parent_descriptor = _open_trusted_directory(output.parent)
    staging_descriptor = None
    staging_name = ""
    staging_identity = (-1, -1)
    published = False
    try:
        _validate_output_entry(parent_descriptor, output.name)
        _require_parent_identity(output.parent, parent_descriptor)
        staging_name, staging_descriptor, staging_identity = (
            _create_private_staging(parent_descriptor)
        )
        if _event_hook is not None:
            _event_hook(
                "staging-created", output.parent / staging_name
            )
        directories: Set[Tuple[str, ...]] = {()}
        for relative, data in sorted(files.items()):
            _write_staging_file(
                staging_descriptor, relative, data, directories
            )
        _write_staging_file(
            staging_descriptor,
            BUILD_REPORT_PATH,
            canonical_json_v2(report, stored=True),
            directories,
        )
        _finalize_staging_directories(staging_descriptor, directories)

        _require_parent_identity(output.parent, parent_descriptor)
        _validate_output_entry(parent_descriptor, output.name)
        _require_entry_identity(
            parent_descriptor,
            staging_name,
            staging_descriptor,
            staging_identity,
        )
        os.rename(
            staging_name,
            output.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        published = True
        _require_entry_identity(
            parent_descriptor,
            output.name,
            staging_descriptor,
            staging_identity,
        )
        os.fsync(parent_descriptor)
        _require_parent_identity(output.parent, parent_descriptor)
    except Exception:
        if staging_descriptor is not None:
            _cleanup_original_staging(
                parent_descriptor,
                staging_descriptor,
                staging_identity,
                output.name if published else staging_name,
            )
        raise
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        os.close(parent_descriptor)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--closure", type=Path)
    source.add_argument("--legacy-v1", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-profile-sha256")
    parser.add_argument("--expect-compiler-sha256")
    parser.add_argument("--expect-source-closure-sha256")
    parser.add_argument("--expect-pack-root")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    try:
        output = arguments.output.absolute()
        _validate_output(output)
        profile = load_trusted_profile()
        profile_sha = "sha256:" + __import__("hashlib").sha256(
            canonical_json_v2(profile, stored=True)
        ).hexdigest()
        _compare_expected(
            "profile digest", arguments.expect_profile_sha256, profile_sha
        )
        _compare_expected(
            "compiler implementation digest",
            arguments.expect_compiler_sha256,
            COMPILER_IMPLEMENTATION_SHA256,
        )
        if arguments.legacy_v1:
            result = compile_legacy_v1()
            if arguments.expect_source_closure_sha256 is not None:
                raise CLIError(
                    "--expect-source-closure-sha256 is not valid for legacy-v1"
                )
        else:
            maximum = profile["limits"]["maxClosureBytes"]
            closure = _load_closure(arguments.closure.absolute(), maximum)
            _compare_expected(
                "source closure digest",
                arguments.expect_source_closure_sha256,
                str(closure.get("sourceClosureSha256", "")),
            )
            result = compile_world_pack(closure, profile)
        _compare_expected("pack root", arguments.expect_pack_root, result.root)
        _write_atomic(output, result.files, result.report)
    except (
        CLIError,
        CompilationError,
        LegacyCompilationError,
        OSError,
        ValueError,
    ) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
    print(canonical_json_v2(result.report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
