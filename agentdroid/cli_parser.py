"""Argument parser and action normalization for the AgentDroid CLI."""

from __future__ import annotations

import argparse
from typing import Any

from agentdroid.cli_ai import cmd_ai
from agentdroid.cli_commands import (
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
from agentdroid.pipeline import parse_do_step

KNOWN_SUBCOMMANDS = {
    "setup",
    "init",
    "run",
    "watch",
    "up",
    "down",
    "provision",
    "app",
    "device",
    "ui",
    "pipeline",
    "doctor",
    "mcp",
    "daemon",
    "ai",
    "-h",
    "--help",
    "--version",
}


class _OrderedUIAction(argparse.Action):
    """Custom argparse Action to preserve the exact interleaving order of UI action flags."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if not hasattr(namespace, "ordered_ui_actions"):
            namespace.ordered_ui_actions = []
        namespace.ordered_ui_actions.append((self.dest, values))

        current = getattr(namespace, self.dest, None) or []
        setattr(namespace, self.dest, current + [values])


def _parse_ui_actions(args: argparse.Namespace) -> list[dict[str, Any]]:
    ordered = getattr(args, "ordered_ui_actions", None)
    if ordered:
        actions: list[dict[str, Any]] = []
        for dest, val in ordered:
            if dest == "do_steps":
                actions.append(parse_do_step(val))
            elif dest == "click_targets":
                actions.append({"type": "click", "selector": val})
            elif dest == "fill_targets":
                if "=" in val:
                    sel, txt = val.split("=", 1)
                    actions.append({"type": "fill", "selector": sel.strip(), "text": txt})
                else:
                    actions.append({"type": "type", "text": val})
            elif dest == "scroll_dirs":
                actions.append({"type": "scroll", "direction": val})
            elif dest == "scroll_to_targets":
                actions.append({"type": "scroll_to", "text": val})
            elif dest == "tap":
                parts = [p.strip() for p in val.split(",")]
                if len(parts) != 2:
                    raise ValueError(f"--tap requires 'x,y' coordinates, got {val!r}")
                actions.append({"type": "tap", "x": float(parts[0]), "y": float(parts[1])})
            elif dest == "type_text":
                actions.append({"type": "type", "text": val})
            elif dest == "swipe":
                parts = [p.strip() for p in val.split(",")]
                if len(parts) not in (4, 5):
                    raise ValueError(f"--swipe requires 'x1,y1,x2,y2[,duration_ms]', got {val!r}")
                actions.append(
                    {
                        "type": "swipe",
                        "x1": float(parts[0]),
                        "y1": float(parts[1]),
                        "x2": float(parts[2]),
                        "y2": float(parts[3]),
                        "duration": int(parts[4]) if len(parts) == 5 else 300,
                    }
                )
            elif dest == "key":
                actions.append({"type": "key", "key": val})
        return actions

    # Fallback if ordered_ui_actions is absent (e.g. manually constructed Namespace in unit tests)
    actions = []
    for raw_do in getattr(args, "do_steps", None) or []:
        actions.append(parse_do_step(raw_do))
    for sel in getattr(args, "click_targets", None) or []:
        actions.append({"type": "click", "selector": sel})
    for fill_spec in getattr(args, "fill_targets", None) or []:
        if "=" in fill_spec:
            sel, txt = fill_spec.split("=", 1)
            actions.append({"type": "fill", "selector": sel.strip(), "text": txt})
        else:
            actions.append({"type": "type", "text": fill_spec})
    for dir_spec in getattr(args, "scroll_dirs", None) or []:
        actions.append({"type": "scroll", "direction": dir_spec})
    for scroll_needle in getattr(args, "scroll_to_targets", None) or []:
        actions.append({"type": "scroll_to", "text": scroll_needle})
    for coord in getattr(args, "tap", None) or []:
        parts = [p.strip() for p in coord.split(",")]
        if len(parts) != 2:
            raise ValueError(f"--tap requires 'x,y' coordinates, got {coord!r}")
        actions.append({"type": "tap", "x": float(parts[0]), "y": float(parts[1])})
    for text in getattr(args, "type_text", None) or []:
        actions.append({"type": "type", "text": text})
    for sw in getattr(args, "swipe", None) or []:
        parts = [p.strip() for p in sw.split(",")]
        if len(parts) not in (4, 5):
            raise ValueError(f"--swipe requires 'x1,y1,x2,y2[,duration_ms]', got {sw!r}")
        actions.append(
            {
                "type": "swipe",
                "x1": float(parts[0]),
                "y1": float(parts[1]),
                "x2": float(parts[2]),
                "y2": float(parts[3]),
                "duration": int(parts[4]) if len(parts) == 5 else 300,
            }
        )
    for k in getattr(args, "key", None) or []:
        actions.append({"type": "key", "key": k})
    return actions


def _add_safe_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--safe",
        action="store_true",
        help=(
            "Enable safe mode (also via AGENTDROID_SAFE_MODE=1): blocks arbitrary root shell "
            "execution unless matched by --shell-allowlist and requires SHA-256 checksums for remote APKs."
        ),
    )
    p.add_argument(
        "--shell-allowlist",
        action="append",
        metavar="CMD_PREFIX",
        help="Allow a specific shell command prefix in --safe mode (repeatable, e.g. 'pm list packages').",
    )


def _add_run_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("-s", "--serial", help="Target Android device serial (default: 127.0.0.1:5555).")
    p.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run silently in background without opening GUI windows (default).",
    )
    p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Show live what the AI agent is doing via a floating mobile simulator overlay window.",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Allow mouse/keyboard input inside the watch window.",
    )
    p.add_argument(
        "--window-width",
        type=int,
        default=412,
        help="Width of the floating simulator watch window (default: 412).",
    )
    p.add_argument(
        "--window-height",
        type=int,
        default=892,
        help="Height of the floating simulator watch window (default: 892).",
    )
    p.add_argument(
        "--no-always-on-top",
        action="store_true",
        help="Do not keep the simulator watch window floating on top.",
    )
    p.add_argument(
        "--borderless",
        action="store_true",
        help="Display the simulator window borderless.",
    )
    p.add_argument(
        "--no-provision",
        action="store_true",
        help="Skip automatic silent device provisioning check before running.",
    )
    _add_safe_arguments(p)

    # App installation & permissions (local path, HTTPS URL, or fdroid:<query_or_pkg>)
    p.add_argument(
        "-i",
        "--install",
        action="append",
        metavar="SOURCE",
        help="Install app before running: local APK path, HTTPS URL (or 'sha256:<hex>@https://...'), or 'fdroid:<query_or_pkg>' (repeatable).",
    )
    p.add_argument(
        "--no-grant",
        action="store_true",
        help="Do not auto-grant runtime permissions and special appops after installing APKs.",
    )
    p.add_argument(
        "--grant",
        action="append",
        metavar="PACKAGE",
        help="Grant all runtime permissions and special appops to PACKAGE (repeatable).",
    )
    p.add_argument(
        "--clear-data",
        action="append",
        metavar="PACKAGE",
        help="Clear app data for PACKAGE before launching (repeatable).",
    )
    p.add_argument(
        "--clear",
        dest="clear_installed",
        action="store_true",
        help="Clear app data of the installed/target package before launching.",
    )
    p.add_argument(
        "--launch",
        nargs="?",
        const="auto",
        metavar="PACKAGE",
        help="Launch the installed app (or specified PACKAGE/component) before running UI steps.",
    )
    p.add_argument(
        "--launch-installed",
        action="store_true",
        help="Launch the first APK installed via --install.",
    )
    p.add_argument(
        "--stop-after",
        action="store_true",
        help="Force-stop the target package when execution finishes.",
    )

    # General-purpose device I/O (files, URLs, clipboard, notifications)
    p.add_argument(
        "--push",
        action="append",
        metavar="LOCAL[:REMOTE]",
        help="Push file/folder to device before running (default remote: /sdcard/Download/, repeatable).",
    )
    p.add_argument(
        "--pull",
        action="append",
        metavar="REMOTE[:LOCAL]",
        help="Pull file/folder from device after running (default local: ./artifacts/, repeatable).",
    )
    p.add_argument(
        "--open-url",
        action="append",
        metavar="URI",
        help="Open web URL or deep link (https://, tg://, mailto:, geo:, etc.) before UI steps (repeatable).",
    )
    p.add_argument(
        "--set-clipboard",
        metavar="TEXT",
        help="Set Android clipboard text before running.",
    )
    p.add_argument(
        "--get-clipboard",
        action="store_true",
        help="Read and return Android clipboard text after running.",
    )
    p.add_argument(
        "--notifications",
        action="store_true",
        help="Read and return active device notifications (OTP codes, messages, status) in output.",
    )

    # Compound Semantic & Coordinate UI actions
    p.add_argument(
        "-d",
        "--do",
        dest="do_steps",
        action=_OrderedUIAction,
        metavar="VERB:ARG",
        help="Execute semantic action step in order (e.g. 'click:Login', 'fill:Email=user@test.com', 'scroll-to:Submit', 'key:HOME', 'sleep:1', repeatable).",
    )
    p.add_argument(
        "--click",
        dest="click_targets",
        action=_OrderedUIAction,
        metavar="TEXT_OR_ID",
        help="Click/tap element by text, description, or #index (repeatable).",
    )
    p.add_argument(
        "--fill",
        dest="fill_targets",
        action=_OrderedUIAction,
        metavar="SELECTOR=TEXT",
        help="Fill input field matching SELECTOR with TEXT (repeatable).",
    )
    p.add_argument(
        "--scroll",
        dest="scroll_dirs",
        action=_OrderedUIAction,
        metavar="DIRECTION",
        help="Scroll screen direction: 'down', 'up', 'left', 'right' (repeatable).",
    )
    p.add_argument(
        "--scroll-to",
        dest="scroll_to_targets",
        action=_OrderedUIAction,
        metavar="TEXT",
        help="Scroll down until TEXT is visible on screen (repeatable).",
    )
    p.add_argument(
        "--pre-shell",
        action="append",
        metavar="CMD",
        help="Run root ADB shell command before UI steps (repeatable; restricted in --safe mode).",
    )
    p.add_argument(
        "--tap",
        action=_OrderedUIAction,
        metavar="X,Y",
        help="Tap coordinates X,Y (repeatable).",
    )
    p.add_argument(
        "--type",
        dest="type_text",
        action=_OrderedUIAction,
        metavar="TEXT",
        help="Type text into focused field (repeatable).",
    )
    p.add_argument(
        "--swipe",
        action=_OrderedUIAction,
        metavar="X1,Y1,X2,Y2[,MS]",
        help="Swipe coordinates (repeatable).",
    )
    p.add_argument(
        "--key",
        action=_OrderedUIAction,
        metavar="KEY",
        help="Send global key action (HOME, BACK, ENTER, RECENTS, TAB, repeatable).",
    )
    p.add_argument(
        "--wait-text",
        action="append",
        metavar="TEXT",
        help="Wait until TEXT appears on screen before UI steps (repeatable).",
    )
    p.add_argument(
        "--post-shell",
        action="append",
        metavar="CMD",
        help="Run root ADB shell command after UI steps (repeatable; restricted in --safe mode).",
    )
    p.add_argument(
        "--assert-text",
        action="append",
        metavar="TEXT",
        help="Verify TEXT is visible on screen after execution (repeatable).",
    )
    p.add_argument(
        "-a",
        "--locked-app",
        metavar="PACKAGE",
        help="Open URLs in this specific Android package.",
    )

    # Diagnostics & outputs
    p.add_argument(
        "--no-check-crashes",
        action="store_true",
        help="Disable automatic logcat crash & ANR inspection.",
    )
    p.add_argument(
        "-l",
        "--collect-logs",
        action="store_true",
        help="Include tail of device logcat in the final output.",
    )
    p.add_argument(
        "--log-lines",
        type=int,
        default=60,
        help="Number of logcat lines to collect when --collect-logs is set (default: 60).",
    )
    p.add_argument(
        "--screenshot",
        metavar="PATH",
        help="Capture final PNG screenshot to PATH.",
    )
    p.add_argument(
        "--dump-ui",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include compact token-efficient UI element hierarchy in output (default: True).",
    )
    p.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit single compact JSON object (ideal for AI coding agents).",
    )
    p.set_defaults(func=cmd_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentdroid",
        description=(
            "AgentDroid: Silent General-Purpose Android Environment for AI Agents (Redroid).\n"
            "Drive Android locally via MCP or compound CLI calls — installing apps, opening URLs,\n"
            "pushing/pulling files, reading notifications/clipboard, and executing multi-step UI workflows\n"
            "with silent --headless background mode and live --watch visual mode."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="agentdroid 0.3.0")
    subparsers = parser.add_subparsers(dest="subcommand")

    # --- setup / init ---
    for setup_name in ("setup", "init"):
        setup_p = subparsers.add_parser(
            setup_name,
            help="Install local CLI link, optionally mount AI agent skills/rules/MCP, and boot the silent Android container.",
        )
        setup_p.add_argument("--no-start", action="store_true", help="Configure CLI without starting Docker containers.")
        setup_p.add_argument("--no-agents", action="store_true", help="Do not modify global AI coding assistant configs.")
        setup_p.add_argument("--agents-only", action="store_true", help="Only install/update AI agent skills & rules.")
        setup_p.add_argument("--build", action="store_true", help="Build Docker images when starting stack.")
        setup_p.add_argument("-w", "--watch", action="store_true", help="Open live viewer after starting stack.")
        setup_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
        setup_p.set_defaults(func=cmd_setup)

    # --- run ---
    run_p = subparsers.add_parser(
        "run",
        help="Execute a compound multi-step Android workflow (install apps, push/pull files, open URLs, read notifications/output) in one call.",
    )
    _add_run_arguments(run_p)

    # --- watch ---
    watch_p = subparsers.add_parser(
        "watch",
        help="Watch live what the AI agent is doing (opens scrcpy with --watch, or streams background JSONL with --headless).",
    )
    watch_p.add_argument("-s", "--serial", help="Target Android device serial (default: 127.0.0.1:5555).")
    watch_p.add_argument(
        "--headless",
        action="store_true",
        help="Stream agent events & foreground changes in background as JSONL without opening any GUI window.",
    )
    watch_p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        default=True,
        help="Open live visual viewer (scrcpy) + terminal action telemetry (default).",
    )
    watch_p.add_argument("--interactive", action="store_true", help="Allow mouse/keyboard input inside the scrcpy watch window.")
    watch_p.add_argument("--window-width", type=int, default=412, help="Width of the floating simulator watch window (default: 412).")
    watch_p.add_argument("--window-height", type=int, default=892, help="Height of the floating simulator watch window (default: 892).")
    watch_p.add_argument("--no-always-on-top", action="store_true", help="Do not keep the simulator watch window floating on top.")
    watch_p.add_argument("--borderless", action="store_true", help="Display the mobile simulator window borderless.")
    watch_p.set_defaults(func=cmd_watch)

    # --- up ---
    up_p = subparsers.add_parser(
        "up",
        help="Start the headless Redroid Docker Compose container and silently provision the device.",
    )
    up_p.add_argument("-s", "--serial", help="ADB serial (default: 127.0.0.1:5555).")
    up_p.add_argument("--image", help="Override Redroid Docker image tag.")
    up_p.add_argument("--build", action="store_true", help="Rebuild Docker images before starting.")
    up_p.add_argument("--headless", action="store_true", default=True, help="Run silently in background (default).")
    up_p.add_argument("-w", "--watch", action="store_true", help="Open live scrcpy viewer once booted.")
    up_p.add_argument("--window-width", type=int, default=412, help="Width of the simulator watch window.")
    up_p.add_argument("--window-height", type=int, default=892, help="Height of the simulator watch window.")
    up_p.add_argument("--no-always-on-top", action="store_true", help="Do not keep simulator window on top.")
    up_p.add_argument("--borderless", action="store_true", help="Display simulator window borderless.")
    up_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    up_p.set_defaults(func=cmd_up)

    # --- down ---
    down_p = subparsers.add_parser("down", help="Stop the Redroid Docker Compose container.")
    down_p.add_argument("-v", "--volumes", action="store_true", help="Also remove persistent data volumes.")
    down_p.set_defaults(func=cmd_down)

    # --- provision ---
    prov_p = subparsers.add_parser(
        "provision",
        help="Configure an Android/Redroid device for silent AI agent usage (root ADB, animations=0, audio muted, accessibility helper enabled).",
    )
    prov_p.add_argument("-s", "--serial", help="Target Android device serial.")
    prov_p.add_argument("--force", action="store_true", help="Re-apply all settings even if already provisioned.")
    prov_p.add_argument("-j", "--json", action="store_true", help="Print JSON result.")
    prov_p.set_defaults(func=cmd_provision)

    # --- app ---
    app_p = subparsers.add_parser(
        "app",
        help="Search F-Droid, install APKs (from file, HTTPS URL, or F-Droid), auto-grant permissions, and manage apps.",
    )
    app_p.add_argument(
        "app_action",
        choices=["search", "install", "grant", "launch", "stop", "clear", "list"],
    )
    app_p.add_argument(
        "target",
        nargs="?",
        default="",
        help="Search query, APK path, HTTPS URL, 'sha256:<hex>@https://...', 'fdroid:<query>', or Android package name.",
    )
    app_p.add_argument("-s", "--serial", help="Target Android device serial.")
    app_p.add_argument("--sha256", help="Expected 64-char hex SHA-256 checksum for APK verification.")
    app_p.add_argument("--launch", action="store_true", help="Launch app immediately after install.")
    app_p.add_argument("--clear", action="store_true", help="Clear app data on install.")
    app_p.add_argument("--no-grant", action="store_true", help="Skip auto-granting runtime permissions.")
    _add_safe_arguments(app_p)
    app_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    app_p.set_defaults(func=cmd_app)

    # --- device ---
    dev_p = subparsers.add_parser(
        "device",
        help="General-purpose device operations: push/pull files, open URLs/deep links, clipboard, notifications, root shell.",
    )
    dev_sub = dev_p.add_subparsers(dest="device_action", required=True)

    push_p = dev_sub.add_parser("push", help="Push local file/folder onto the Android device.")
    push_p.add_argument("src", help="Local path.")
    push_p.add_argument("dest", nargs="?", default="/sdcard/Download/", help="Remote path (default: /sdcard/Download/).")
    push_p.add_argument("-s", "--serial")
    push_p.add_argument("-j", "--json", action="store_true")

    pull_p = dev_sub.add_parser("pull", help="Pull remote file/folder from the Android device to workspace.")
    pull_p.add_argument("src", help="Remote path on Android.")
    pull_p.add_argument("dest", nargs="?", default="./artifacts/", help="Local destination (default: ./artifacts/).")
    pull_p.add_argument("-s", "--serial")
    pull_p.add_argument("-j", "--json", action="store_true")

    open_p = dev_sub.add_parser("open", help="Open a web URL or deep link URI on the device.")
    open_p.add_argument("uri", help="URL or URI (e.g. https://example.com, tg://..., geo:...).")
    open_p.add_argument("-p", "--package", help="Optional package to handle the URI.")
    open_p.add_argument("-s", "--serial")
    open_p.add_argument("-j", "--json", action="store_true")

    clip_p = dev_sub.add_parser("clipboard", help="Get or set the Android device clipboard.")
    clip_p.add_argument("text", nargs="?", default=None, help="Text to set on clipboard (omit to read clipboard).")
    clip_p.add_argument("-s", "--serial")
    clip_p.add_argument("-j", "--json", action="store_true")

    notif_p = dev_sub.add_parser("notifications", help="Read active device notifications (OTP codes, messages, etc.).")
    notif_p.add_argument("--all", action="store_true", help="Include system notifications.")
    notif_p.add_argument("-s", "--serial")
    notif_p.add_argument("-j", "--json", action="store_true")

    sh_p = dev_sub.add_parser("shell", help="Execute an ADB shell command on the device (restricted in --safe mode).")
    sh_p.add_argument("command", help="Shell command string.")
    sh_p.add_argument("-s", "--serial")
    _add_safe_arguments(sh_p)
    sh_p.add_argument("-j", "--json", action="store_true")

    clean_p = dev_sub.add_parser("clean", help="Force-stop background 3rd-party apps and reclaim kernel caches to reduce CPU/RAM.")
    clean_p.add_argument("-s", "--serial")
    clean_p.add_argument("-j", "--json", action="store_true")

    dev_p.set_defaults(func=cmd_device)

    # --- ui ---
    ui_p = subparsers.add_parser(
        "ui",
        help="Direct sub-second UI hierarchy dump & gestures via the on-device accessibility helper.",
    )
    ui_sub = ui_p.add_subparsers(dest="ui_action", required=True)

    dump_p = ui_sub.add_parser("dump", help="Dump compact, token-efficient visible UI elements.")
    dump_p.add_argument("-s", "--serial", help="Target device serial.")
    dump_p.add_argument("--max-elements", type=int, default=60)
    dump_p.add_argument("--include-ime", action="store_true", help="Include soft-keyboard keys in UI dump.")
    dump_p.add_argument("-j", "--json", action="store_true")

    tap_p = ui_sub.add_parser("tap", help="Tap screen coordinates.")
    tap_p.add_argument("x", type=float)
    tap_p.add_argument("y", type=float)
    tap_p.add_argument("-s", "--serial")
    tap_p.add_argument("-j", "--json", action="store_true")

    type_p = ui_sub.add_parser("type", help="Input text into focused field.")
    type_p.add_argument("text")
    type_p.add_argument("--append", action="store_true")
    type_p.add_argument("-s", "--serial")
    type_p.add_argument("-j", "--json", action="store_true")

    swipe_p = ui_sub.add_parser("swipe", help="Swipe from (x1,y1) to (x2,y2).")
    swipe_p.add_argument("x1", type=float)
    swipe_p.add_argument("y1", type=float)
    swipe_p.add_argument("x2", type=float)
    swipe_p.add_argument("y2", type=float)
    swipe_p.add_argument("duration", nargs="?", type=int, default=300)
    swipe_p.add_argument("-s", "--serial")
    swipe_p.add_argument("-j", "--json", action="store_true")

    key_p = ui_sub.add_parser("key", help="Send global action / key (HOME, BACK, RECENTS, ENTER).")
    key_p.add_argument("keycode")
    key_p.add_argument("-s", "--serial")
    key_p.add_argument("-j", "--json", action="store_true")

    shot_p = ui_sub.add_parser("screenshot", help="Save PNG screenshot.")
    shot_p.add_argument("output")
    shot_p.add_argument("-s", "--serial")
    shot_p.add_argument("-j", "--json", action="store_true")

    ui_p.set_defaults(func=cmd_ui)

    # --- pipeline ---
    pipe_p = subparsers.add_parser("pipeline", help="Run a multi-step JSON workflow specification in one call.")
    pipe_p.add_argument("file", help="Path to JSON pipeline file.")
    pipe_p.add_argument("-s", "--serial", help="Override target device serial.")
    pipe_p.add_argument("--headless", action="store_true", help="Force silent background mode.")
    pipe_p.add_argument("-w", "--watch", action="store_true", help="Force live visual watch mode.")
    _add_safe_arguments(pipe_p)
    pipe_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    pipe_p.set_defaults(func=cmd_pipeline)

    # --- doctor ---
    doc_p = subparsers.add_parser("doctor", help="Check Redroid, ADB root, silent settings, helper APK SHA-256, and helper health.")
    doc_p.add_argument("-s", "--serial", help="Target Android device serial.")
    doc_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    doc_p.set_defaults(func=cmd_doctor)

    # --- mcp ---
    mcp_p = subparsers.add_parser(
        "mcp",
        help="Run or install Model Context Protocol (MCP) stdio server for Claude Code, Codex, Antigravity, and Cursor.",
    )
    mcp_p.add_argument("-s", "--serial", help="Target device serial.")
    mcp_p.add_argument(
        "--install",
        action="store_true",
        help="Configure MCP in Claude Code, Codex, Antigravity, and Cursor config files.",
    )
    mcp_p.add_argument(
        "--target",
        choices=["all", "claude", "codex", "antigravity", "cursor"],
        default="all",
        help="Target AI assistant to configure (default: all).",
    )
    _add_safe_arguments(mcp_p)
    mcp_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    mcp_p.set_defaults(func=cmd_mcp)

    # --- daemon ---
    daemon_p = subparsers.add_parser(
        "daemon",
        help="Manage the persistent warm local Unix-socket daemon (eliminates CLI startup overhead).",
    )
    daemon_p.add_argument("action", choices=["start", "stop", "status", "serve"], help="Daemon lifecycle action.")
    daemon_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    daemon_p.set_defaults(func=cmd_daemon)

    # --- ai ---
    ai_p = subparsers.add_parser(
        "ai",
        help="Optional cloud autonomous loop calling TypeSafe AI (api.typesafe.ai; requires TYPESAFE_API_KEY).",
    )
    ai_p.add_argument("prompt", help="Natural language goal or task prompt.")
    ai_p.add_argument("-s", "--serial", help="Target Android device serial (default: 127.0.0.1:5555).")
    ai_p.add_argument("-w", "--watch", action="store_true", help="Launch live visual viewer (scrcpy) during execution.")
    ai_p.add_argument("--interactive", action="store_true", help="Allow mouse/keyboard input inside watch window.")
    ai_p.add_argument("--window-width", type=int, default=412, help="Width of the floating watch window (default: 412).")
    ai_p.add_argument("--window-height", type=int, default=892, help="Height of the floating watch window (default: 892).")
    ai_p.add_argument("--no-always-on-top", action="store_true", help="Do not keep the watch window on top.")
    ai_p.add_argument("--borderless", action="store_true", help="Run watch window without borders.")
    ai_p.add_argument("--max-steps", type=int, default=10, help="Maximum autonomous decision steps (default: 10).")
    ai_p.add_argument("--launch", metavar="PACKAGE", help="Launch Android package before starting the loop.")
    ai_p.add_argument("--stop-after", action="store_true", help="Force-stop launched app after execution finishes.")
    ai_p.add_argument("--clear-data", action="append", metavar="PACKAGE", help="Clear package data before starting (repeatable).")
    ai_p.add_argument("--key", help="TypeSafe AI API key for api.typesafe.ai (defaults to TYPESAFE_API_KEY env var).")
    ai_p.add_argument("--model", default="jev-latest", help="TypeSafe model identifier (default: jev-latest).")
    ai_p.add_argument("-j", "--json", action="store_true", help="Emit JSON execution report.")
    ai_p.set_defaults(func=cmd_ai)

    return parser


def normalize_argv(argv: list[str]) -> list[str]:
    """Allow `agentdroid --install ... --do "click:Login"` without typing `run` explicitly."""
    if len(argv) > 1 and argv[1] not in KNOWN_SUBCOMMANDS:
        return [argv[0], "run", *argv[1:]]
    return list(argv)
