from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from shuvagent.config import load_config
from shuvagent.control import ControlServer, send_control_command
from shuvagent.env_loader import load_env_file
from shuvagent.paths import default_local_env_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        return asyncio.run(_run(args.config))
    if args.command == "control":
        return asyncio.run(_control(args.verb, args.config))
    if args.command in {"start", "stop", "status"}:
        return asyncio.run(_control(args.command, args.config))
    parser.error(f"unknown command {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shuvagent")
    parser.add_argument("--config", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="run the foreground shuvagent process")
    control = subparsers.add_parser("control", help="send a control command")
    control.add_argument("verb", choices=["start", "stop", "status"])
    subparsers.add_parser("start", help="alias for control start")
    subparsers.add_parser("stop", help="alias for control stop")
    subparsers.add_parser("status", help="alias for control status")
    return parser


async def _run(config_path: Path | None) -> int:
    config = load_config(config_path)
    loaded = load_env_file(default_local_env_path())
    server = ControlServer(config.control.socket)
    await server.start()
    print(f"[shuvagent] Loaded {loaded} env var(s) from {default_local_env_path()}")
    print(f"[shuvagent] Control socket: {config.control.socket}")
    print("[shuvagent] Ready.")
    try:
        await server.serve_forever()
    finally:
        await server.stop()
    return 0


async def _control(verb: str, config_path: Path | None) -> int:
    config = load_config(config_path)
    response = await send_control_command(config.control.socket, verb)
    print(response)
    return 0 if response.startswith("OK ") else 1
