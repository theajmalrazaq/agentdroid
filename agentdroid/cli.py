"""Entrypoint for the AgentDroid (`agentdroid`) command-line interface."""

from __future__ import annotations

import sys

from agentdroid.cli_ai import cmd_ai
from agentdroid.cli_commands import (
    REPO_ROOT,
    _run_doctor_checks,
    cmd_app,
    cmd_daemon,
    cmd_device,
    cmd_doctor,
    cmd_down,
    cmd_mcp,
    cmd_pipeline,
    cmd_provision,
    cmd_run,
    cmd_setup,
    cmd_ui,
    cmd_up,
    cmd_watch,
)
from agentdroid.cli_output import _print_output
from agentdroid.cli_parser import (
    KNOWN_SUBCOMMANDS,
    _add_run_arguments,
    _OrderedUIAction,
    _parse_ui_actions,
    build_parser,
    normalize_argv,
)

__all__ = [
    "KNOWN_SUBCOMMANDS",
    "REPO_ROOT",
    "_OrderedUIAction",
    "_add_run_arguments",
    "_parse_ui_actions",
    "_print_output",
    "_run_doctor_checks",
    "build_parser",
    "cmd_ai",
    "cmd_app",
    "cmd_daemon",
    "cmd_device",
    "cmd_doctor",
    "cmd_down",
    "cmd_mcp",
    "cmd_pipeline",
    "cmd_provision",
    "cmd_run",
    "cmd_setup",
    "cmd_ui",
    "cmd_up",
    "cmd_watch",
    "main",
    "normalize_argv",
]


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv if argv is None else [sys.argv[0], *argv]
    norm = normalize_argv(raw_argv)
    parser = build_parser()
    if len(norm) == 1:
        parser.print_help()
        return 0
    args = parser.parse_args(norm[1:])
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    res = func(args)
    return int(res) if res is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
