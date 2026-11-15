"""Security Guardrails for AgentDroid Web and Cloud Deployments.

Protects cloud-hosted AgentDroid instances from malicious usage, SSRF attacks,
path traversal, destructive shell commands, and DoS abuse when exposed over HTTP.
In local CLI mode, full developer freedom is preserved.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
import os
from pathlib import Path
import re
import socket
import time
from typing import Any
import urllib.parse

# Blocked cloud metadata & link-local networks
BLOCKED_NETWORKS = [
    ip_network("127.0.0.0/8"),       # Loopback
    ip_network("169.254.0.0/16"),     # Link-local & Cloud Metadata (AWS, GCP, Azure, Hetzner, DO)
    ip_network("10.0.0.0/8"),         # RFC 1918 Private class A
    ip_network("172.16.0.0/12"),      # RFC 1918 Private class B
    ip_network("192.168.0.0/16"),     # RFC 1918 Private class C
    ip_network("::1/128"),            # IPv6 loopback
    ip_network("fc00::/7"),           # IPv6 unique local
    ip_network("fe80::/10"),          # IPv6 link-local
]

# Sensitive host path needles that web requests must never access
SENSITIVE_HOST_PATTERNS = [
    r"\.env($|\.)",
    r"\.ssh($|/)",
    r"\.git($|/)",
    r"\.netrc",
    r"\.bash_history",
    r"/etc/shadow",
    r"/etc/passwd",
    r"/etc/sudoers",
    r"/proc/",
    r"/sys/",
    r"/dev/",
    r"\.\./",
    r"/\.\.",
]

# Destructive shell command patterns
DANGEROUS_SHELL_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{\s*:\|:&\s*\};:",     # Fork bomb
    r"\breboot\b",
    r"\bshutdown\b",
    r"\bpoweroff\b",
    r"\bsetenforce\s+0\b",
    r"\bmount\s+-[o\s]*remount",
    r"\bam\s+broadcast\s+-[aA]\s+android\.intent\.action\.MASTER_CLEAR",
    r"\bwipe\s+data\b",
    r"/system/bin/sh\s+-i",
    r"\bnc\s+-[le]",
    r"\b/dev/tcp/",
    r"\bcurl\b.*\|\s*bash",
    r"\bwget\b.*\|\s*sh",
]

# Allowed URL schemes in web mode
ALLOWED_URL_SCHEMES = {"http", "https", "market", "geo", "tel"}


class SecurityError(Exception):
    """Raised when an action violates AgentDroid web security guardrails."""

    def __init__(self, message: str, violation_type: str = "forbidden"):
        super().__init__(message)
        self.violation_type = violation_type


class RateLimiter:
    """Sliding-window in-memory rate limiter per client identifier (IP / key)."""

    def __init__(self, max_requests: int = 60, window_sec: float = 60.0):
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._history: dict[str, list[float]] = {}

    def allow(self, client_id: str) -> bool:
        now = time.monotonic()
        history = self._history.setdefault(client_id, [])
        cutoff = now - self.window_sec
        # Evict old timestamps
        history = [ts for ts in history if ts > cutoff]
        self._history[client_id] = history

        if len(history) >= self.max_requests:
            return False

        history.append(now)
        return True


class SecurityGuardrails:
    """Configurable security policy for web-based AgentDroid environments."""

    def __init__(
        self,
        enabled: bool = True,
        allow_private_networks: bool = False,
        allow_shell: bool = False,
        max_file_size_bytes: int = 100 * 1024 * 1024, # 100 MB
        rate_limit_rpm: int = 60,
    ) -> None:
        self.enabled = enabled
        self.allow_private_networks = allow_private_networks
        self.allow_shell = allow_shell
        self.max_file_size_bytes = max_file_size_bytes
        self.rate_limiter = RateLimiter(max_requests=rate_limit_rpm, window_sec=60.0)

    @classmethod
    def from_env(cls) -> SecurityGuardrails:
        """Create guardrails from environment variables."""
        mode = os.environ.get("AGENTDROID_SECURITY_MODE", "web").lower().strip()
        if mode in ("0", "off", "disabled", "false"):
            return cls(enabled=False)

        allow_priv = os.environ.get("AGENTDROID_ALLOW_PRIVATE_NETWORKS", "false").lower() in ("1", "true")
        allow_sh = os.environ.get("AGENTDROID_ALLOW_WEB_SHELL", "false").lower() in ("1", "true")
        rpm = int(os.environ.get("AGENTDROID_RATE_LIMIT_RPM", "60"))

        return cls(
            enabled=True,
            allow_private_networks=allow_priv,
            allow_shell=allow_sh,
            rate_limit_rpm=rpm,
        )

    def validate_rate_limit(self, client_id: str) -> None:
        if not self.enabled:
            return
        if not self.rate_limiter.allow(client_id):
            raise SecurityError(
                f"Rate limit exceeded: maximum {self.rate_limiter.max_requests} requests per minute",
                violation_type="rate_limit_exceeded",
            )

    def validate_url(self, raw_url: str) -> None:
        """Protect against SSRF and cloud metadata access."""
        if not self.enabled:
            return

        parsed = urllib.parse.urlparse(raw_url.strip())
        scheme = parsed.scheme.lower()
        if not scheme:
            raise SecurityError("URL must include an explicit scheme (http/https)", violation_type="invalid_scheme")

        if scheme not in ALLOWED_URL_SCHEMES:
            raise SecurityError(
                f"URL scheme {scheme!r} is forbidden by security guardrails (allowed: http, https, market, geo, tel)",
                violation_type="blocked_scheme",
            )

        if scheme in ("http", "https"):
            hostname = parsed.hostname or ""
            if not hostname:
                raise SecurityError("URL has empty host", violation_type="empty_host")

            # Check explicit cloud metadata domain names
            if hostname.lower() in ("metadata.google.internal", "instance-data", "metadata"):
                raise SecurityError("Access to cloud metadata endpoints is blocked", violation_type="ssrf_blocked")

            # Resolve host IP to protect against SSRF & DNS rebinding
            if not self.allow_private_networks:
                try:
                    addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
                    for family, _, _, _, sockaddr in addr_info:
                        ip_str = sockaddr[0]
                        ip_obj = ip_address(ip_str)
                        for net in BLOCKED_NETWORKS:
                            if ip_obj in net:
                                raise SecurityError(
                                    f"Access to private/metadata IP {ip_str} ({hostname}) is blocked",
                                    violation_type="ssrf_blocked",
                                )
                except socket.gaierror:
                    # DNS failure will fail on device anyway, allow it or block
                    pass

    def validate_host_path(self, path_str: str) -> None:
        """Prevent directory traversal and unauthorized host filesystem inspection."""
        if not self.enabled:
            return

        clean = str(path_str).replace("\\", "/")
        for pattern in SENSITIVE_HOST_PATTERNS:
            if re.search(pattern, clean, re.IGNORECASE):
                raise SecurityError(
                    f"Access to path matching {pattern} is blocked by security guardrails",
                    violation_type="path_traversal",
                )

    def validate_shell_command(self, cmd_str: str) -> None:
        """Block destructive root shell commands in web-based operations."""
        if not self.enabled:
            return

        if not self.allow_shell:
            raise SecurityError(
                "Direct shell execution is disabled in web security mode. Use semantic UI actions instead.",
                violation_type="shell_disabled",
            )

        for pattern in DANGEROUS_SHELL_PATTERNS:
            if re.search(pattern, cmd_str, re.IGNORECASE):
                raise SecurityError(
                    f"Command contains prohibited destructive pattern ({pattern})",
                    violation_type="dangerous_command",
                )

    def validate_pipeline_payload(self, body: dict[str, Any]) -> None:
        """Comprehensive verification of an incoming compound pipeline request."""
        if not self.enabled:
            return

        # 1. URL validation
        for u in body.get("open_urls") or []:
            if isinstance(u, str):
                self.validate_url(u)
        if "open_url" in body and isinstance(body["open_url"], str):
            self.validate_url(body["open_url"])

        # 2. Path validation
        for pf in body.get("push_files") or []:
            if isinstance(pf, str):
                self.validate_host_path(pf.split(":", 1)[0])
        for pl in body.get("pull_files") or []:
            if isinstance(pl, str) and ":" in pl:
                self.validate_host_path(pl.split(":", 1)[1])

        # 3. Shell commands validation
        for cmd in (body.get("pre_shell") or []) + (body.get("post_shell") or []):
            if isinstance(cmd, str):
                self.validate_shell_command(cmd)

        # 4. App sources validation
        for apk in body.get("install") or body.get("install_apks") or []:
            if isinstance(apk, str) and (apk.startswith("http://") or apk.startswith("https://")):
                self.validate_url(apk)
            elif isinstance(apk, str) and not apk.startswith("fdroid:"):
                self.validate_host_path(apk)
