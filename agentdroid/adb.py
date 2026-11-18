"""ADB device controller for general-purpose AI agent Android usage.

Supports silent provisioning, on-demand app search & installation (local path, URL, or F-Droid),
auto-permission granting, deep-link/URL opening, file push/pull with media scanning,
notification reading, clipboard sync, root shell execution, and crash/log collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from typing import Any
import urllib.parse
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVISION_SCRIPT = REPO_ROOT / "scripts" / "provision-device.sh"
BUNDLED_HELPER_APK = (
    REPO_ROOT / "packages" / "artemis-accessibility-helper" / "ArtemisAccessibilityHelper.apk"
)

SPECIAL_APPOPS = (
    "SYSTEM_ALERT_WINDOW",
    "MANAGE_EXTERNAL_STORAGE",
    "WRITE_SETTINGS",
    "GET_USAGE_STATS",
    "PACKAGE_USAGE_STATS",
    "POST_NOTIFICATIONS",
    "ACCESS_RESTRICTED_SETTINGS",
    "REQUEST_INSTALL_PACKAGES",
    "SCHEDULE_EXACT_ALARM",
)


def probe_adbd_tcp(host: str, port: int, timeout: float = 0.35) -> bool:
    """Return True if an ADB daemon on host:port actively replies CNXN or AUTH.

    Prevents the host adb server daemon from blocking inside `adb connect` when a
    port-forwarder (such as docker-proxy during container startup) accepts TCP
    connections before `adbd` inside the container is listening.
    """
    payload = b"host::\x00"
    hdr = struct.pack(
        "<6I",
        0x4E584E43,  # CNXN
        0x01000001,
        256 * 1024,
        len(payload),
        sum(payload) & 0xFFFFFFFF,
        0x4E584E43 ^ 0xFFFFFFFF,
    )
    sock: socket.socket | None = None
    try:
        sock = socket.create_connection((host.strip("[]"), port), timeout=timeout)
        sock.settimeout(timeout)
        sock.sendall(hdr + payload)
        resp = sock.recv(24)
        return len(resp) >= 4 and resp[:4] in (b"CNXN", b"AUTH")
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


@dataclass
class InstalledAppInfo:
    """Metadata returned when an APK is installed on the device."""

    source: str
    local_path: str
    package: str | None
    main_activity: str | None
    permissions_granted: int = 0
    appops_granted: int = 0
    duration_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "local_path": self.local_path,
            "package": self.package,
            "main_activity": self.main_activity,
            "permissions_granted": self.permissions_granted,
            "appops_granted": self.appops_granted,
            "duration_sec": round(self.duration_sec, 2),
        }


@dataclass
class CrashReport:
    """Crash and ANR summary collected from Android logcat buffers."""

    has_crashes: bool = False
    fatal_exceptions: list[str] = field(default_factory=list)
    anrs: list[str] = field(default_factory=list)
    native_tombstones: list[str] = field(default_factory=list)
    raw_crash_log: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_crashes": self.has_crashes,
            "fatal_exceptions": self.fatal_exceptions,
            "anrs": self.anrs,
            "native_tombstones": self.native_tombstones,
            "raw_crash_log": self.raw_crash_log[:4000] if self.raw_crash_log else "",
        }


class AdbDevice:
    """High-level ADB controller turning Android into a general-purpose silent environment for AI agents."""

    def __init__(
        self,
        serial: str | None = None,
        adb_bin: str | None = None,
    ) -> None:
        self.adb_bin = adb_bin or os.environ.get("ADB_BIN") or shutil.which("adb") or "adb"
        self._adb_bin_explicit = adb_bin is not None or "ADB_BIN" in os.environ
        self._display_size: tuple[int, int] | None = None
        self.serial = (
            serial
            or os.environ.get("ADB_DEVICE_SERIAL")
            or os.environ.get("REDROID_ADDR")
            or self._detect_first_device()
            or "127.0.0.1:5555"
        )

    def _use_rust_adb(self) -> bool:
        if self._adb_bin_explicit and self.adb_bin != "adb":
            return False
        return (
            getattr(self.run_adb, "__func__", None) is AdbDevice.run_adb
            and subprocess.run.__module__ == "subprocess"
        )

    def _detect_first_device(self) -> str | None:
        if not self._adb_bin_explicit and subprocess.run.__module__ == "subprocess":
            try:
                from agentdroid import rust_bridge

                ok, out = rust_bridge.adb_devices()
                if ok:
                    for line in out.splitlines():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "device":
                            return parts[0]
            except Exception:
                pass
        try:
            proc = subprocess.run(
                [self.adb_bin, "devices"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            for line in (proc.stdout or "").splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    return parts[0]
        except Exception:
            pass
        return None

    def run_adb(
        self,
        args: list[str],
        *,
        timeout: float = 60.0,
        binary: bool = False,
    ) -> subprocess.CompletedProcess:
        cmd = [self.adb_bin, "-s", self.serial, *args]
        try:
            return subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=not binary,
                timeout=timeout,
                check=False,
            )
        except Exception as e:
            empty_out: Any = b"" if binary else ""
            return subprocess.CompletedProcess(
                cmd, returncode=127, stdout=empty_out, stderr=str(e)
            )

    def shell(self, command: str, *, timeout: float = 30.0) -> str:
        if self._use_rust_adb():
            try:
                from agentdroid import rust_bridge

                ok, out = rust_bridge.adb_shell(
                    self.serial, command, timeout_ms=int(max(1.0, timeout) * 1000)
                )
                if ok:
                    return out.strip()
            except Exception:
                pass
        res = self.run_adb(["shell", command], timeout=timeout)
        return (res.stdout or "").strip()

    def is_connected(self) -> bool:
        """Quick non-blocking check if device state is 'device'."""
        if self._use_rust_adb():
            try:
                from agentdroid import rust_bridge

                ok, state_str = rust_bridge.adb_state(self.serial)
                if ok:
                    return state_str.strip() == "device"
            except Exception:
                pass
        try:
            state = self.run_adb(["get-state"], timeout=3.0)
            return state.returncode == 0 and (state.stdout or "").strip() == "device"
        except Exception:
            return False

    def connect(self, timeout: float = 30.0) -> bool:
        """Connect to TCP ADB device if needed and verify online state."""
        if self.is_connected():
            return True
        try:
            subprocess.run(
                [self.adb_bin, "start-server"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=10.0,
                check=False,
            )
        except Exception:
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_connected():
                return True
            if ":" in self.serial:
                host, _, port_s = self.serial.rpartition(":")
                if host and port_s.isdigit():
                    if not probe_adbd_tcp(host, int(port_s), timeout=0.35):
                        time.sleep(0.15)
                        continue
                try:
                    c_proc = subprocess.run(
                        [self.adb_bin, "connect", self.serial],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=4.0,
                        check=False,
                    )
                    if "already connected" in (c_proc.stdout or "") and not self.is_connected():
                        subprocess.run(
                            [self.adb_bin, "disconnect", self.serial],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            timeout=3.0,
                            check=False,
                        )
                        continue
                except Exception:
                    return False
            if self.is_connected():
                return True
            time.sleep(0.2)
        return False

    def ensure_root(self) -> bool:
        """Elevate adbd to root on Redroid (ro.secure=0)."""
        uid = self.shell("id -u", timeout=5.0)
        if uid == "0":
            return True
        self.run_adb(["root"], timeout=10.0)
        if ":" in self.serial:
            time.sleep(0.5)
            self.connect(timeout=10.0)
        return self.shell("id -u", timeout=5.0) == "0"

    def wait_for_boot(self, timeout: float = 90.0) -> bool:
        """Wait until sys.boot_completed=1 and package manager is responsive."""
        if not self.connect(timeout=min(timeout, 25.0)):
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            out = self.shell(
                'boot=$(getprop sys.boot_completed); '
                'if [ "$boot" = "1" ]; then echo BOOT=1; pm path android; fi',
                timeout=5.0,
            )
            if "BOOT=1" in out and "package:" in out:
                return True
            if not out and not self.is_connected():
                if ":" in self.serial:
                    subprocess.run(
                        [self.adb_bin, "disconnect", self.serial],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        timeout=3.0,
                        check=False,
                    )
                self.connect(timeout=max(1.0, min(5.0, deadline - time.monotonic())))
                continue
            time.sleep(0.15)
        return False

    def is_provisioned_silent(self) -> bool:
        """Fast check whether animations are disabled and Artemis Helper is enabled."""
        out = self.shell(
            'printf "%s\\n%s\\n%s\\n" '
            '"$(settings get global window_animation_scale)" '
            '"$(settings get secure enabled_accessibility_services)" '
            '"$(settings get secure accessibility_enabled)"',
            timeout=5.0,
        )
        lines = out.splitlines()
        anim = lines[0].strip() if len(lines) > 0 else ""
        svcs = lines[1].strip() if len(lines) > 1 else ""
        acc_on = lines[2].strip() if len(lines) > 2 else ""
        return (
            anim in ("0", "0.0")
            and "com.artemis.helper/.ArtemisAccessibilityService" in svcs
            and acc_on == "1"
        )

    def provision_silent(self, *, force: bool = False, quiet: bool = True) -> dict[str, Any]:
        """Configure device for silent, zero-popup AI agent operation."""
        if not force and self.connect(timeout=5.0) and self.is_provisioned_silent():
            return {
                "provisioned": True,
                "action": "already_provisioned",
                "serial": self.serial,
            }

        if PROVISION_SCRIPT.is_file():
            env = os.environ.copy()
            env["QUIET"] = "1" if quiet else "0"
            env["ADB_BIN"] = self.adb_bin
            if "AGENTDROID_HELPER_TOKEN" not in env:
                for candidate in (
                    Path(tempfile.gettempdir()) / "agentdroid" / "helper-token" / "session.token",
                    Path.home() / ".cache" / "agentdroid" / "helper-token" / "session.token",
                    Path(tempfile.gettempdir()) / "artemis" / "helper-token" / "session.token",
                    Path.home() / ".cache" / "artemis" / "helper-token" / "session.token",
                ):
                    try:
                        if candidate.is_file():
                            tok = candidate.read_text(encoding="utf-8").strip()
                            if tok:
                                env["AGENTDROID_HELPER_TOKEN"] = tok
                                break
                    except OSError:
                        pass
            res = subprocess.run(
                ["bash", str(PROVISION_SCRIPT), self.serial],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=150.0,
                check=False,
            )
            if res.returncode == 0:
                return {
                    "provisioned": True,
                    "action": "provisioned_via_script",
                    "serial": self.serial,
                }

        if not self.wait_for_boot(timeout=90.0):
            return {
                "provisioned": False,
                "action": "boot_timeout",
                "serial": self.serial,
            }
        self.ensure_root()
        self.shell(
            "settings put global window_animation_scale 0.0; "
            "settings put global transition_animation_scale 0.0; "
            "settings put global animator_duration_scale 0.0; "
            "settings put global device_provisioned 1; "
            "settings put secure user_setup_complete 1; "
            "settings put global stay_on_while_plugged_in 7; "
            "settings put system screen_off_timeout 2147483647; "
            "settings put global hide_error_dialogs 1; "
            "settings put global package_verifier_enable 0; "
            "settings put global verifier_verify_adb_installs 0; "
            "settings put global heads_up_notifications_enabled 0; "
            "locksettings set-disabled true >/dev/null 2>&1 || true; "
            "wm dismiss-keyguard >/dev/null 2>&1 || true; "
            "cmd audio set-ringer-mode SILENT >/dev/null 2>&1 || true"
        )
        if BUNDLED_HELPER_APK.is_file():
            self.run_adb(["install", "-r", "-g", str(BUNDLED_HELPER_APK)], timeout=60.0)
        self.shell(
            "settings put secure enabled_accessibility_services "
            "com.artemis.helper/.ArtemisAccessibilityService; "
            "settings put secure accessibility_enabled 1"
        )
        return {
            "provisioned": True,
            "action": "provisioned_inline",
            "serial": self.serial,
        }

    # ------------------------------------------------------------------ #
    # App Discovery, Installation & Permissions
    # ------------------------------------------------------------------ #

    def list_third_party_packages(self) -> set[str]:
        out = self.shell("pm list packages -3")
        pkgs: set[str] = set()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkgs.add(line.split(":", 1)[1].strip())
        return pkgs

    def is_package_installed(self, package: str) -> bool:
        """Fast check whether a package is already installed on device."""
        if not package or not self.connect(timeout=5.0):
            return False
        out = self.shell(f"pm path {package}", timeout=4.0)
        return out.startswith("package:")

    def search_fdroid_apps(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Search the public F-Droid repository API so AI agents can find & install tools on the fly."""
        encoded = urllib.parse.quote(query.strip())
        url = f"https://search.f-droid.org/api/search_apps?q={encoded}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        apps = data.get("apps", []) if isinstance(data, dict) else []
        results: list[dict[str, Any]] = []
        for item in apps[:limit]:
            if not isinstance(item, dict):
                continue
            pkg_url = str(item.get("url") or "")
            pkg_name = pkg_url.rstrip("/").rsplit("/", 1)[-1] if "/packages/" in pkg_url else None
            results.append(
                {
                    "name": item.get("name"),
                    "package": pkg_name,
                    "summary": item.get("summary"),
                    "url": pkg_url,
                }
            )
        return results

    def resolve_fdroid_apk_url(self, package_or_query: str) -> tuple[str, str]:
        """Resolve a package ID or search query to a direct F-Droid APK download URL."""
        pkg = package_or_query.strip()
        if "." not in pkg or " " in pkg:
            hits = self.search_fdroid_apps(pkg, limit=1)
            if not hits or not hits[0].get("package"):
                raise LookupError(f"No app found in F-Droid matching {package_or_query!r}")
            pkg = str(hits[0]["package"])

        api_url = f"https://f-droid.org/api/v1/packages/{urllib.parse.quote(pkg)}"
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
        packages = meta.get("packages") or []
        ver_code = meta.get("suggestedVersionCode") or (
            packages[0].get("versionCode") if packages else None
        )
        if not ver_code:
            raise LookupError(f"Could not determine APK versionCode for F-Droid package {pkg!r}")
        # Use high-speed European/global mirror (cached, fast CDN) or fallback to official
        apk_url = f"https://mirror.cyberbits.eu/fdroid/repo/{pkg}_{ver_code}.apk"
        return pkg, apk_url

    def _extract_package_from_apk(self, apk_path: Path) -> str | None:
        for tool, args in (
            ("aapt2", ["dump", "packagename", str(apk_path)]),
            ("aapt", ["dump", "badging", str(apk_path)]),
            ("apkanalyzer", ["manifest", "application-id", str(apk_path)]),
        ):
            bin_path = shutil.which(tool)
            if not bin_path:
                continue
            try:
                proc = subprocess.run(
                    [bin_path, *args],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                    check=False,
                )
                out = (proc.stdout or "").strip()
                if not out:
                    continue
                if tool in ("aapt2", "apkanalyzer"):
                    return out.splitlines()[0].strip()
                match = re.search(r"package:\s+name='([^']+)'", out)
                if match:
                    return match.group(1)
            except Exception:
                continue
        return None

    def resolve_main_activity(self, package: str) -> str | None:
        out = self.shell(
            f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {package}"
        )
        for line in reversed(out.splitlines()):
            line = line.strip()
            if "/" in line and not line.startswith("priority="):
                return line
        return None

    def grant_all_permissions(self, package: str) -> tuple[int, int]:
        """Grant all requested runtime permissions and special appops to a package."""
        dumpsys = self.shell(f"dumpsys package {package}", timeout=20.0)
        perms: set[str] = set()
        for match in re.finditer(r"(android\.permission\.[A-Z0-9_]+)", dumpsys):
            perms.add(match.group(1))

        granted_perms = 0
        if perms:
            grant_cmds = [f"pm grant {package} {p} >/dev/null 2>&1 || true" for p in sorted(perms)]
            self.shell("; ".join(grant_cmds), timeout=30.0)
            granted_perms = len(perms)

        appop_cmds = [
            f"appops set {package} {op} allow >/dev/null 2>&1 || true" for op in SPECIAL_APPOPS
        ]
        self.shell("; ".join(appop_cmds), timeout=15.0)
        return granted_perms, len(SPECIAL_APPOPS)

    def install_apk(
        self,
        apk_source: str | Path,
        *,
        grant_permissions: bool = True,
        clear_data: bool = False,
        package_hint: str | None = None,
    ) -> InstalledAppInfo:
        """Install an APK from a local path, HTTP(S) URL, or 'fdroid:<query_or_pkg>' and auto-grant permissions."""
        started = time.monotonic()
        temp_file: str | None = None
        apk_source_str = str(apk_source).strip()
        resolved_source = apk_source_str
        cache_dir = Path.home() / ".cache" / "agentdroid" / "apks"
        cache_dir.mkdir(parents=True, exist_ok=True)

        if apk_source_str.startswith("fdroid:"):
            query = apk_source_str.split(":", 1)[1].strip()
            # Fast path: skip download/install if app is already installed
            if "." in query and self.is_package_installed(query):
                main_activity = self.resolve_main_activity(query)
                return InstalledAppInfo(
                    source=apk_source,
                    local_path="cached-device",
                    package=query,
                    main_activity=main_activity,
                    permissions_granted=0,
                    appops_granted=0,
                    duration_sec=round(time.monotonic() - started, 3),
                )
            pkg_id, resolved_source = self.resolve_fdroid_apk_url(query)
            package_hint = package_hint or pkg_id

        if package_hint and self.is_package_installed(package_hint):
            main_activity = self.resolve_main_activity(package_hint)
            return InstalledAppInfo(
                source=apk_source,
                local_path="cached-device",
                package=package_hint,
                main_activity=main_activity,
                permissions_granted=0,
                appops_granted=0,
                duration_sec=round(time.monotonic() - started, 3),
            )

        try:
            if resolved_source.startswith(("http://", "https://")):
                url_name = Path(urllib.parse.urlparse(resolved_source).path).name or "download.apk"
                cached_apk = cache_dir / url_name
                if cached_apk.is_file() and cached_apk.stat().st_size > 1024:
                    apk_path = cached_apk
                else:
                    tmp_part = cache_dir / f"{url_name}.part"
                    urllib.request.urlretrieve(resolved_source, str(tmp_part))
                    tmp_part.rename(cached_apk)
                    apk_path = cached_apk
            else:
                apk_path = Path(resolved_source).expanduser().resolve()
                if not apk_path.is_file():
                    # If not a local file and looks like a package/search term, try F-Droid resolution
                    if not resolved_source.endswith(".apk"):
                        pkg_id, fdroid_url = self.resolve_fdroid_apk_url(resolved_source)
                        package_hint = package_hint or pkg_id
                        url_name = Path(urllib.parse.urlparse(fdroid_url).path).name or f"{pkg_id}.apk"
                        cached_apk = cache_dir / url_name
                        if cached_apk.is_file() and cached_apk.stat().st_size > 1024:
                            apk_path = cached_apk
                        else:
                            tmp_part = cache_dir / f"{url_name}.part"
                            urllib.request.urlretrieve(fdroid_url, str(tmp_part))
                            tmp_part.rename(cached_apk)
                            apk_path = cached_apk
                    else:
                        raise FileNotFoundError(f"APK file not found: {apk_source}")

            before_pkgs = self.list_third_party_packages()
            pkg = package_hint or self._extract_package_from_apk(apk_path)

            install_flags = ["install", "-r", "-t"]
            if grant_permissions:
                install_flags.append("-g")
            install_flags.append(str(apk_path))

            res = self.run_adb(install_flags, timeout=180.0)
            output = f"{res.stdout or ''}\n{res.stderr or ''}".strip()
            if res.returncode != 0 or "Success" not in output:
                raise RuntimeError(f"Failed to install APK '{apk_source}': {output}")

            if not pkg:
                after_pkgs = self.list_third_party_packages()
                diff = after_pkgs - before_pkgs
                if len(diff) == 1:
                    pkg = next(iter(diff))
                else:
                    recent = self.shell("pm list packages -3 -f | tail -n 1")
                    if "=" in recent:
                        pkg = recent.rsplit("=", 1)[-1].strip()

            perms_count = 0
            appops_count = 0
            main_activity = None
            if pkg:
                if clear_data:
                    self.clear_app_data(pkg)
                if grant_permissions:
                    perms_count, appops_count = self.grant_all_permissions(pkg)
                main_activity = self.resolve_main_activity(pkg)

            return InstalledAppInfo(
                source=apk_source,
                local_path=str(apk_path),
                package=pkg,
                main_activity=main_activity,
                permissions_granted=perms_count,
                appops_granted=appops_count,
                duration_sec=time.monotonic() - started,
            )
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

    def clear_app_data(self, package: str) -> bool:
        out = self.shell(f"pm clear {package}")
        return "Success" in out

    def launch_app(self, package_or_component: str, *, wait: bool = True) -> dict[str, Any]:
        """Launch an app by package name or component (pkg/.Activity)."""
        if "/" in package_or_component:
            component = package_or_component
            pkg = package_or_component.split("/", 1)[0]
        else:
            pkg = package_or_component
            component = self.resolve_main_activity(pkg)

        if component:
            flag = "-W " if wait else ""
            out = self.shell(f"am start {flag}-n {component}")
            return {
                "launched": "Error:" not in out,
                "package": pkg,
                "component": component,
                "output": out,
            }

        out = self.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        return {
            "launched": "Events injected: 1" in out,
            "package": pkg,
            "component": None,
            "output": out,
        }

    def stop_app(self, package: str) -> None:
        self.shell(f"am force-stop {package}")

    def trim_background_apps(self, keep_packages: set[str] | None = None) -> list[str]:
        """Force-stop background 3rd-party apps and reclaim kernel memory to keep CPU/RAM near zero."""
        keep = set(keep_packages or set())
        keep.update({
            "com.android.systemui",
            "com.android.launcher3",
            "com.android.inputmethod.latin",
            "com.artemis.helper",
        })
        third_party = self.list_third_party_packages()
        stopped: list[str] = []
        for pkg in sorted(third_party):
            if pkg not in keep:
                self.shell(f"am force-stop {pkg}")
                stopped.append(pkg)
        self.shell("echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true")
        return stopped

    # ------------------------------------------------------------------ #
    # General-Purpose Device Operations (URLs, Files, Clipboard, Notifications)
    # ------------------------------------------------------------------ #

    def open_url(self, url_or_uri: str, *, package: str | None = None) -> dict[str, Any]:
        """Open any web URL, deep-link URI, or local device file (auto-detecting MIME types)."""
        pkg_arg = f" -p {package}" if package else ""
        uri = url_or_uri.strip()
        mime_arg = ""

        if uri.startswith("/") or uri.startswith("file://"):
            if uri.startswith("/"):
                uri = f"file://{uri}"
            clean = uri.split("?")[0].lower()
            if clean.endswith((".md", ".markdown")):
                mime_arg = " -t 'text/markdown'"
            elif clean.endswith((".txt", ".log", ".json", ".xml", ".yaml", ".yml", ".conf")):
                mime_arg = " -t 'text/plain'"
            elif clean.endswith(".pdf"):
                mime_arg = " -t 'application/pdf'"
            elif clean.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                mime_arg = " -t 'image/*'"

        out = self.shell(
            f"am start -W -a android.intent.action.VIEW -d '{uri}'{mime_arg}{pkg_arg}"
        )
        return {
            "opened": "Error:" not in out,
            "uri": uri,
            "package": package,
            "output": out,
        }

    def push_file(
        self,
        local_path: str | Path,
        remote_path: str = "/sdcard/Download/",
        *,
        media_scan: bool = True,
    ) -> dict[str, Any]:
        """Push a file or folder from the AI agent workspace onto the Android device."""
        src = Path(local_path).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"Local path to push does not exist: {local_path}")
        dest = remote_path
        if dest.endswith("/"):
            dest = f"{dest}{src.name}"
        res = self.run_adb(["push", str(src), dest], timeout=120.0)
        if res.returncode != 0:
            raise RuntimeError(f"adb push failed: {res.stderr or res.stdout}")
        if media_scan:
            self.shell(
                f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{dest}' >/dev/null 2>&1 || true"
            )
        return {"local": str(src), "remote": dest, "ok": True}

    def pull_file(
        self,
        remote_path: str,
        local_path: str | Path = "./artifacts/",
    ) -> dict[str, Any]:
        """Pull a file or folder from the Android device into the AI agent workspace."""
        dest = Path(local_path).expanduser().resolve()
        if str(local_path).endswith("/") or dest.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / Path(remote_path.rstrip("/")).name
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
        res = self.run_adb(["pull", remote_path, str(dest)], timeout=120.0)
        if res.returncode != 0:
            raise RuntimeError(f"adb pull failed: {res.stderr or res.stdout}")
        return {"remote": remote_path, "local": str(dest), "ok": True}

    def get_clipboard(self) -> str:
        """Read current text from Android clipboard across all Android versions (10 - 16)."""
        # 1. Try cmd clipboard (Android 12+)
        out = self.shell("cmd clipboard get-primary-clip 2>/dev/null")
        if out and "No shell command" not in out:
            return out.strip()

        # 2. Try Artemis Accessibility Helper
        try:
            from agentdroid.helper import AccessibilityHelperClient
            helper = AccessibilityHelperClient(self)
            res = helper.action("get_clipboard")
            if res.get("success") and res.get("clipboard") is not None:
                val = str(res["clipboard"]).strip()
                if val:
                    return val
        except Exception:
            pass

        # 3. Read synchronized device file buffer fallback
        buf = self.shell("cat /sdcard/.agentdroid_clip 2>/dev/null")
        if buf and "No such file" not in buf:
            return buf.strip()

        return ""

    def set_clipboard(self, text: str) -> bool:
        """Set text onto the Android clipboard across all Android versions (10 - 16)."""
        safe = text.replace("'", "'\\''")
        # 1. Try cmd clipboard (Android 12+)
        cmd_out = self.shell(f"cmd clipboard set-primary-clip '{safe}' 2>/dev/null")
        if "No shell command" not in cmd_out and "Error" not in cmd_out:
            self.shell(f"echo -n '{safe}' > /sdcard/.agentdroid_clip 2>/dev/null || true")
            return True

        # 2. Try Artemis Accessibility Helper
        try:
            from agentdroid.helper import AccessibilityHelperClient
            helper = AccessibilityHelperClient(self)
            res = helper.action("clipboard", text=text)
            if res.get("success"):
                self.shell(f"echo -n '{safe}' > /sdcard/.agentdroid_clip 2>/dev/null || true")
                return True
        except Exception:
            pass

        # 3. Always write to synchronized device file buffer
        self.shell(f"echo -n '{safe}' > /sdcard/.agentdroid_clip 2>/dev/null || true")
        return True

    def get_notifications(self, *, include_system: bool = False) -> list[dict[str, Any]]:
        """Extract active notifications (useful for reading 2FA/OTP codes, messages, background tasks)."""
        raw = self.shell("dumpsys notification --noredact", timeout=15.0)
        notifications: list[dict[str, Any]] = []
        blocks = re.split(r"NotificationRecord\(", raw)
        for blk in blocks[1:]:
            pkg_m = re.search(r"pkg=([a-zA-Z0-9_.]+)", blk)
            pkg = pkg_m.group(1) if pkg_m else ""
            if not include_system and pkg in ("android", "com.android.systemui", "com.artemis.helper"):
                continue
            title_m = re.search(r"android\.title=(?:String\s*\()?(.*?)(?:\)\s*$|\n)", blk)
            text_m = re.search(r"android\.text=(?:String\s*\()?(.*?)(?:\)\s*$|\n)", blk)
            big_m = re.search(r"android\.bigText=(?:String\s*\()?(.*?)(?:\)\s*$|\n)", blk)
            title = (title_m.group(1).strip() if title_m else "").strip()
            text = (big_m.group(1).strip() if big_m else (text_m.group(1).strip() if text_m else "")).strip()
            if title in ("null", "") and text in ("null", ""):
                continue
            notifications.append(
                {
                    "package": pkg,
                    "title": None if title == "null" else title,
                    "text": None if text == "null" else text,
                }
            )
        return notifications[:30]

    def get_display_size(self, *, refresh: bool = False) -> tuple[int, int]:
        """Return cached or live device screen (width, height) in pixels."""
        if self._display_size is not None and not refresh:
            return self._display_size
        out = self.shell("wm size 2>/dev/null || true", timeout=4.0)
        matches = re.findall(r"(\d+)\s*x\s*(\d+)", out)
        if matches:
            w, h = map(int, matches[-1])
            if w > 0 and h > 0:
                self._display_size = (w, h)
                return self._display_size
        return (1080, 2400)

    def set_display_size_hint(self, width: int, height: int) -> None:
        if width > 0 and height > 0:
            self._display_size = (width, height)

    def foreground_app(self) -> dict[str, str | None]:
        """Return the currently visible foreground package and activity."""
        out = self.shell("dumpsys window displays | grep -E 'mCurrentFocus|mFocusedApp'")
        match = re.search(r"([a-zA-Z0-9_.]+/[a-zA-Z0-9_.$]+)", out)
        if match:
            comp = match.group(1)
            pkg, act = comp.split("/", 1)
            return {"package": pkg, "activity": act, "component": comp}
        return {"package": None, "activity": None, "component": None}

    def screenshot(self, output_path: str | Path) -> str:
        """Capture a PNG screenshot from the device directly to output_path."""
        dest = Path(output_path).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        res = self.run_adb(["exec-out", "screencap", "-p"], binary=True, timeout=15.0)
        if res.returncode != 0 or not res.stdout:
            raise RuntimeError("screencap failed or returned empty data")
        dest.write_bytes(res.stdout)
        return str(dest)

    def clear_logs(self) -> None:
        res = self.run_adb(["logcat", "-b", "all", "-c"], timeout=10.0)
        if res.returncode != 0:
            self.run_adb(["logcat", "-c"], timeout=10.0)

    def collect_crashes(self, package_filter: str | None = None) -> CrashReport:
        """Inspect logcat crash buffer and ANR traces."""
        if self._use_rust_adb():
            combined = self.shell(
                "logcat -d -b crash 2>/dev/null; "
                "printf '\\n__AGENTDROID_ANR_SEP__\\n'; "
                "logcat -d -b system,events -s ActivityManager:E am_anr:* 2>/dev/null",
                timeout=10.0,
            )
            if "__AGENTDROID_ANR_SEP__" in combined:
                raw_crash, raw_anr = combined.split("__AGENTDROID_ANR_SEP__", 1)
                raw_crash = raw_crash.strip()
                raw_anr = raw_anr.strip()
            else:
                raw_crash = combined.strip()
                raw_anr = ""
        else:
            crash_res = self.run_adb(["logcat", "-d", "-b", "crash"], timeout=10.0)
            raw_crash = (crash_res.stdout or "").strip()
            anr_res = self.run_adb(
                ["logcat", "-d", "-b", "system,events", "-s", "ActivityManager:E", "am_anr:*"],
                timeout=10.0,
            )
            raw_anr = (anr_res.stdout or "").strip()

        fatal_exceptions: list[str] = []
        native_tombstones: list[str] = []
        for line in raw_crash.splitlines():
            if package_filter and package_filter not in line and "FATAL EXCEPTION" not in line:
                continue
            if "FATAL EXCEPTION" in line or "AndroidRuntime: Process:" in line or " Caused by:" in line:
                fatal_exceptions.append(line.strip())
            elif "Fatal signal" in line or "backtrace:" in line:
                native_tombstones.append(line.strip())

        anrs: list[str] = []
        for line in raw_anr.splitlines():
            if "ANR in " in line or "am_anr" in line:
                if not package_filter or package_filter in line:
                    anrs.append(line.strip())

        has_crashes = bool(fatal_exceptions or native_tombstones or anrs)
        if package_filter and raw_crash and package_filter not in raw_crash:
            has_crashes = bool(anrs)
            fatal_exceptions = []
            native_tombstones = []

        return CrashReport(
            has_crashes=has_crashes,
            fatal_exceptions=fatal_exceptions[:25],
            anrs=anrs[:15],
            native_tombstones=native_tombstones[:25],
            raw_crash_log=raw_crash,
        )

    def collect_logcat_tail(
        self,
        *,
        lines: int = 80,
        package_filter: str | None = None,
        errors_only: bool = True,
    ) -> list[str]:
        """Return a token-efficient tail of relevant logcat lines."""
        priority = "*:E" if errors_only else "*:I"
        res = self.run_adb(["logcat", "-d", "-t", str(lines * 3), priority], timeout=10.0)
        output_lines = (res.stdout or "").splitlines()
        if package_filter:
            pid = self.shell(f"pidof -s {package_filter}")
            filtered = [
                ln
                for ln in output_lines
                if package_filter in ln or (pid and f" {pid} " in ln)
            ]
            if filtered:
                output_lines = filtered
        return [ln.strip() for ln in output_lines[-lines:] if ln.strip()]
