"""Security policies, safe-mode shell allowlisting, and APK integrity verification."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
from typing import Any
import urllib.parse
import urllib.request
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER_DIR = REPO_ROOT / "packages" / "artemis-accessibility-helper"
HELPER_APK_NAME = "ArtemisAccessibilityHelper.apk"
HELPER_MANIFEST_NAME = "helper_manifest.json"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_INLINE_SHA256_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})@(.+)$")
_SHELL_METACHARS = (";", "&&", "||", "|", "`", "$(", "${", ">", "<", "\n", "\r")


def is_safe_mode_enabled(explicit: bool | None = None) -> bool:
    """Return True when safe mode is enabled explicitly or via AGENTDROID_SAFE_MODE."""
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get("AGENTDROID_SAFE_MODE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def parse_shell_allowlist(
    explicit: list[str] | tuple[str, ...] | str | None = None,
) -> tuple[str, ...]:
    """Normalize shell allowlist entries from explicit args or AGENTDROID_SHELL_ALLOWLIST."""
    raw_items: list[str] = []
    if explicit is None:
        env_val = os.environ.get("AGENTDROID_SHELL_ALLOWLIST", "")
        if env_val.strip():
            raw_items.extend(re.split(r"[,\n]+", env_val))
    elif isinstance(explicit, str):
        raw_items.extend(re.split(r"[,\n]+", explicit))
    else:
        for item in explicit:
            raw_items.extend(re.split(r"[,\n]+", str(item)))

    cleaned: list[str] = []
    for entry in raw_items:
        norm = entry.strip()
        if norm and norm not in cleaned:
            cleaned.append(norm)
    return tuple(cleaned)


def validate_shell_command(
    command: str,
    *,
    safe_mode: bool,
    allowlist: tuple[str, ...] | list[str] = (),
) -> str:
    """Enforce safe-mode shell restrictions and prefix allowlisting without shell injection."""
    if not safe_mode:
        return command

    cmd = command.strip()
    if not cmd:
        raise PermissionError("Empty shell command rejected in --safe mode.")

    entries = parse_shell_allowlist(allowlist)
    if not entries:
        raise PermissionError(
            f"Shell command {cmd!r} blocked in --safe mode. "
            "Pass --shell-allowlist (or AGENTDROID_SHELL_ALLOWLIST) to permit specific commands."
        )

    for meta in _SHELL_METACHARS:
        if meta in cmd:
            raise PermissionError(
                f"Shell command {cmd!r} rejected in --safe mode: forbidden shell operator {meta!r}."
            )

    try:
        cmd_tokens = shlex.split(cmd)
    except ValueError as exc:
        raise PermissionError(
            f"Shell command {cmd!r} rejected in --safe mode: malformed quoting ({exc})."
        ) from exc

    if not cmd_tokens:
        raise PermissionError("Empty shell command rejected in --safe mode.")

    for rule in entries:
        try:
            rule_tokens = shlex.split(rule)
        except ValueError:
            continue
        if rule_tokens and cmd_tokens[: len(rule_tokens)] == rule_tokens:
            return cmd

    raise PermissionError(
        f"Shell command {cmd!r} is not permitted by --safe allowlist {list(entries)!r}."
    )


def sha256_file(path: Path) -> str:
    """Compute lowercase hexadecimal SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_file_sha256(path: Path, expected_sha256: str) -> str:
    """Verify a file matches expected_sha256 (64 hex chars), raising ValueError on mismatch."""
    expected = expected_sha256.strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        raise ValueError(f"Invalid SHA-256 hex digest: {expected_sha256!r}")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(
            f"SHA-256 checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )
    return actual


def verify_bundled_helper_apk(
    repo_root: Path | None = None,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Verify the bundled ArtemisAccessibilityHelper.apk against helper_manifest.json."""
    root = repo_root or REPO_ROOT
    helper_dir = root / "packages" / "artemis-accessibility-helper"
    apk_path = helper_dir / HELPER_APK_NAME
    manifest_path = helper_dir / HELPER_MANIFEST_NAME

    result: dict[str, Any] = {
        "ok": False,
        "apk_path": str(apk_path),
        "manifest_path": str(manifest_path),
        "expected_sha256": None,
        "actual_sha256": None,
        "error": None,
    }

    try:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Helper manifest not found: {manifest_path}")
        if not apk_path.is_file():
            raise FileNotFoundError(f"Bundled helper APK not found: {apk_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = str(manifest.get("sha256") or "").strip().lower()
        result["expected_sha256"] = expected
        actual = verify_file_sha256(apk_path, expected)
        result["actual_sha256"] = actual
        result["ok"] = True
        return result
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["error"] = str(exc)
        if strict:
            raise
        return result


def parse_apk_source_checksum(source: str) -> tuple[str, str | None]:
    """Extract optional inline 'sha256:<64hex>@<source>' checksum prefix."""
    trimmed = source.strip()
    match = _INLINE_SHA256_RE.match(trimmed)
    if match:
        return match.group(2).strip(), match.group(1).lower()
    return trimmed, None


def validate_apk_url(url: str) -> str:
    """Validate that an APK download URL uses HTTPS and has a valid host."""
    parsed = urllib.parse.urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise ValueError(
            f"Refusing insecure APK URL {url!r}: only https:// downloads are allowed."
        )
    if not parsed.netloc:
        raise ValueError(f"Invalid APK URL (missing host): {url!r}")
    return url.strip()


def cache_path_for_apk_url(cache_dir: Path, url: str) -> Path:
    """Derive a collision-resistant, path-traversal-safe cache path keyed by URL digest."""
    parsed = urllib.parse.urlparse(url)
    raw_name = Path(parsed.path).name or "download.apk"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", raw_name).lstrip(".") or "download.apk"
    if not safe_name.lower().endswith(".apk"):
        safe_name = f"{safe_name}.apk"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{url_hash}_{safe_name}"


def validate_apk_archive(path: Path) -> None:
    """Verify that a downloaded file is a valid APK (ZIP archive with AndroidManifest.xml)."""
    if not path.is_file() or path.stat().st_size < 1024:
        raise ValueError(f"Downloaded APK {path.name} is empty or truncated.")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "AndroidManifest.xml" not in zf.namelist():
                raise ValueError(
                    f"Downloaded file {path.name} is not a valid APK (missing AndroidManifest.xml)."
                )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Downloaded file {path.name} is not a valid APK archive: {exc}") from exc


def download_verified_apk(
    url: str,
    cache_dir: Path,
    *,
    expected_sha256: str | None = None,
    require_checksum: bool = False,
    timeout: float = 60.0,
) -> tuple[Path, str]:
    """Download an APK over HTTPS into a URL-hashed cache and verify archive & SHA-256."""
    clean_url = validate_apk_url(url)
    expected = expected_sha256.strip().lower() if expected_sha256 else None
    if expected is not None and not _SHA256_RE.fullmatch(expected):
        raise ValueError(f"Invalid expected SHA-256 hex digest: {expected_sha256!r}")
    if require_checksum and expected is None:
        raise PermissionError(
            f"Refusing unverified remote APK download {clean_url!r} in --safe mode. "
            "Supply --sha256 <hex> or use 'sha256:<hex>@https://...'."
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_apk = cache_path_for_apk_url(cache_dir, clean_url)
    sidecar = Path(f"{cached_apk}.sha256")

    if cached_apk.is_file():
        try:
            validate_apk_archive(cached_apk)
            actual = sha256_file(cached_apk)
            if expected is not None:
                if actual == expected:
                    return cached_apk, actual
            elif sidecar.is_file():
                recorded = sidecar.read_text(encoding="utf-8").strip().lower()
                if _SHA256_RE.fullmatch(recorded) and actual == recorded:
                    return cached_apk, actual
        except (OSError, ValueError):
            pass
        cached_apk.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)

    tmp_part = cache_dir / f".{cached_apk.name}.{os.getpid()}.part"
    req = urllib.request.Request(
        clean_url,
        headers={"User-Agent": "agentdroid/0.3.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp_part.open("wb") as out_fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out_fh.write(chunk)
        validate_apk_archive(tmp_part)
        actual = verify_file_sha256(tmp_part, expected) if expected is not None else sha256_file(tmp_part)
        tmp_part.replace(cached_apk)
        sidecar.write_text(f"{actual}\n", encoding="utf-8")
        return cached_apk, actual
    except Exception:
        tmp_part.unlink(missing_ok=True)
        raise
