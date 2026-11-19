"""Headless vs. live watch controller (floating scrcpy phone overlay)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def has_gui_display() -> bool:
    """Return True if the host environment has an active GUI display for scrcpy."""
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def detect_dock_coordinates(
    target_width: int = 412,
    target_height: int = 892,
) -> tuple[int, int, int, int]:
    """Calculate side-by-side docking coordinates on the right edge of the monitor."""
    # 1. Wayland / Hyprland (active on Omarchy / modern desktop)
    if shutil.which("hyprctl"):
        try:
            res = subprocess.run(
                ["hyprctl", "monitors", "-j"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                mons = json.loads(res.stdout)
                if mons:
                    focused = next((m for m in mons if m.get("focused")), mons[0])
                    scale = float(focused.get("scale", 1.0))
                    sw = int(focused["width"] / scale)
                    sh = int(focused["height"] / scale)
                    h = min(target_height, sh - 60)
                    w = int(h * (412 / 892))
                    x = sw - w - 24
                    y = 30
                    return w, h, x, y
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            logger.debug("hyprctl monitor detection skipped: %s", exc)

    # 2. X11 / xrandr fallback
    if shutil.which("xrandr"):
        try:
            res = subprocess.run(
                ["xrandr", "--current"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            for line in res.stdout.splitlines():
                if " current " in line:
                    parts = line.split(" current ")[1].split(",")[0].split(" x ")
                    sw, sh = int(parts[0]), int(parts[1])
                    h = min(target_height, sh - 80)
                    w = int(h * (412 / 892))
                    x = sw - w - 24
                    y = 30
                    return w, h, x, y
        except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
            logger.debug("xrandr monitor detection skipped: %s", exc)

    return target_width, target_height, 1480, 40


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

        if self.window_x is None or self.window_y is None:
            w, h, x, y = detect_dock_coordinates(self.window_width, self.window_height)
            self.window_width = w
            self.window_height = h
            if self.window_x is None:
                self.window_x = x
            if self.window_y is None:
                self.window_y = y

        title = self.window_title or f"📱 AgentDroid · Mobile Simulator ({self.serial})"
        cmd = [scrcpy_bin, "-s", self.serial, "--window-title", title, "--no-audio"]
        if self.interactive_control:
            cmd.append("--stay-awake")
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
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            # If running on Linux tiling window managers (Hyprland, Sway, i3), request floating mode
            import threading
            threading.Thread(
                target=self._try_enable_floating,
                args=(title, self.window_width, self.window_height),
                daemon=True,
            ).start()
        except OSError as exc:
            print(f"[agentdroid:watch] Could not start scrcpy overlay: {exc}", file=sys.stderr)
            return {"mode": "watch", "viewer": "none"}
        print(
            f"[agentdroid:watch] Live mobile simulator overlay opened "
            f"({self.window_width}x{self.window_height}, always-on-top, PID {self._scrcpy_proc.pid})",
            file=sys.stderr,
        )
        return {"mode": "watch", "viewer": "scrcpy_overlay"}

    def _try_enable_floating(self, title: str, width: int, height: int) -> None:
        """Attempt to enforce floating and target dimensions on Linux tiling WMs (Hyprland, Sway, i3)."""
        import time

        try:
            for _ in range(5):
                time.sleep(0.35)
                # Hyprland
                if shutil.which("hyprctl"):
                    for selector in (f"title:{title}", "class:scrcpy", "initialTitle:scrcpy"):
                        subprocess.run(
                            ["hyprctl", "dispatch", "setfloating", selector],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                        subprocess.run(
                            ["hyprctl", "dispatch", "pin", selector],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                        subprocess.run(
                            ["hyprctl", "dispatch", "resizewindowpixel", f"exact {width} {height}", selector],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    break
                # Sway
                if shutil.which("swaymsg"):
                    subprocess.run(
                        ["swaymsg", f'[app_id="scrcpy"] floating enable, sticky enable, resize set {width} {height}'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    subprocess.run(
                        ["swaymsg", f'[title="{title}"] floating enable, sticky enable, resize set {width} {height}'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    break
                # i3
                if shutil.which("i3-msg"):
                    subprocess.run(
                        ["i3-msg", f'[class="(?i)scrcpy"] floating enable, sticky enable, resize set {width} {height}'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    break
                # X11 / XWayland wmctrl
                if shutil.which("wmctrl"):
                    subprocess.run(
                        ["wmctrl", "-r", title, "-b", "add,above"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    break
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("Floating WM hint skipped: %s", exc)

    def stop(self, force: bool = False) -> None:
        if not force and (self.watch or os.environ.get("AGENTDROID_KEEP_WATCH") == "1"):
            return
        proc = self._scrcpy_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                except OSError as exc:
                    logger.debug("Failed killing scrcpy process: %s", exc)
        self._scrcpy_proc = None
