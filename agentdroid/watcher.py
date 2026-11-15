"""Headless vs. live watch controller (floating scrcpy phone overlay)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def has_gui_display() -> bool:
    """Return True if the host environment has an active GUI display for scrcpy."""
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class LiveWatcher:
    """Silent background (--headless) vs. floating iOS-Simulator-style phone window (--watch)."""

    def __init__(
        self,
        serial: str,
        *,
        watch: bool = False,
        interactive_control: bool = False,
        always_on_top: bool = True,
        window_width: int = 412,
        window_height: int = 892,
        borderless: bool = False,
        window_title: str | None = None,
        window_x: int | None = None,
        window_y: int | None = None,
    ) -> None:
        self.serial = serial
        self.watch = watch
        self.interactive_control = interactive_control
        self.always_on_top = always_on_top
        self.window_width = window_width
        self.window_height = window_height
        self.borderless = borderless
        self.window_title = window_title
        self.window_x = window_x
        self.window_y = window_y
        self._scrcpy_proc: subprocess.Popen | None = None

    def start(self) -> dict[str, str | None]:
        """Open the floating overlay if --watch is enabled; no-op in --headless mode."""
        if not self.watch:
            return {"mode": "headless", "viewer": None}

        scrcpy_bin = shutil.which("scrcpy")
        if not (has_gui_display() and scrcpy_bin):
            print(
                "[agentdroid:watch] No display or scrcpy found; continuing without a viewer.",
                file=sys.stderr,
            )
            return {"mode": "watch", "viewer": "none"}

        title = self.window_title or f"AgentDroid · Android Simulator ({self.serial})"
        cmd = [scrcpy_bin, "-s", self.serial, "--window-title", title, "--stay-awake", "--no-audio"]
        if self.always_on_top:
            cmd.append("--always-on-top")
        if self.window_width > 0:
            cmd.extend(["--window-width", str(self.window_width)])
        if self.window_height > 0:
            cmd.extend(["--window-height", str(self.window_height)])
        if self.window_x is not None:
            cmd.extend(["--window-x", str(self.window_x)])
        if self.window_y is not None:
            cmd.extend(["--window-y", str(self.window_y)])
        if self.borderless:
            cmd.append("--window-borderless")
        if not self.interactive_control:
            cmd.append("--no-control")

        try:
            self._scrcpy_proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as exc:
            print(f"[agentdroid:watch] Could not start scrcpy overlay: {exc}", file=sys.stderr)
            return {"mode": "watch", "viewer": "none"}
        print(
            f"[agentdroid:watch] Live mobile simulator overlay opened "
            f"({self.window_width}x{self.window_height}, always-on-top, PID {self._scrcpy_proc.pid})",
            file=sys.stderr,
        )
        return {"mode": "watch", "viewer": "scrcpy_overlay"}

    def stop(self) -> None:
        proc = self._scrcpy_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._scrcpy_proc = None
