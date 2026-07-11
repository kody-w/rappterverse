#!/usr/bin/env python3
"""Validate privileged workflow inputs before constructing command arguments."""

from __future__ import annotations

import argparse
import re
import sys

AGENT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3}$")
REFERENCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
WORLDS = {"hub", "arena", "marketplace", "gallery", "dungeon"}


def boolean(value: str) -> str:
    if value not in {"true", "false"}:
        raise argparse.ArgumentTypeError("must be true or false")
    return value


def agent_id(value: str) -> str:
    if value and not AGENT_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("invalid agent ID")
    return value


def reference(value: str) -> str:
    if value and not REFERENCE_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("invalid message reference")
    return value


def world(value: str) -> str:
    if value and value not in WORLDS:
        raise argparse.ArgumentTypeError("invalid world")
    return value


def bounded_integer(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be {minimum}..{maximum}")
        return number
    return parse


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    dispatch = commands.add_parser("agent-dispatch")
    dispatch.add_argument("--agent-id", type=agent_id, default="")
    dispatch.add_argument("--world", type=world, default="")
    dispatch.add_argument("--respond-to", type=reference, default="")
    dispatch.add_argument("--max-agents", type=bounded_integer(1, 50), default=5)
    dispatch.add_argument("--poke", type=boolean, default="false")

    growth = commands.add_parser("world-growth")
    growth.add_argument("--force-spawn", type=bounded_integer(0, 200), default=0)
    growth.add_argument("--dry-run", type=boolean, default="false")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "agent-dispatch":
        selected = sum(bool(value) for value in (args.agent_id, args.world, args.respond_to))
        if selected > 1:
            parser().error("choose only one of agent-id, world, or respond-to")
        if args.poke == "true" and not args.agent_id:
            parser().error("poke requires agent-id")
    return 0


if __name__ == "__main__":
    sys.exit(main())
