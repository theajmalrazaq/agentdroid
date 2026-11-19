"""Tests covering security hardening, APK integrity, safe mode, and audit invariants."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from agentdroid.adb import AdbDevice
from agentdroid.cli import build_parser, cmd_device, cmd_pipeline
from agentdroid.mcp import McpServer
from agentdroid.pipeline import CompoundPipeline, PipelineSpec
from agentdroid.security import (
    cache_path_for_apk_url,
    download_verified_apk,
    parse_apk_source_checksum,
    validate_apk_url,
    validate_shell_command,
    verify_bundled_helper_apk,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_valid_apk_bytes(extra: bytes = b"payload") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("AndroidManifest.xml", b"<manifest/>" + (b"x" * 1200) + extra)
    return buf.getvalue()


class TestLegalConfigAndRepoInvariants(unittest.TestCase):
    def test_license_notice_and_google_disclaimer_exist(self) -> None:
        license_file = REPO_ROOT / "LICENSE"
        notice_file = REPO_ROOT / "NOTICE"
        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertTrue(license_file.is_file())
        self.assertTrue(notice_file.is_file())
        self.assertIn("Apache License", license_file.read_text(encoding="utf-8"))
        notice_text = notice_file.read_text(encoding="utf-8")
        self.assertIn("google/artemis", notice_text)
        self.assertIn("NOT affiliated with", notice_text)
        self.assertIn("not affiliated with", readme_text.lower())

    def test_phantom_server_removed_and_zero_cloud_disclosed(self) -> None:
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        install_sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

        self.assertNotIn("AGENTDROID_API_KEY", env_example)
        self.assertNotIn("AGENTDROID_CORS_ORIGIN", env_example)
        self.assertNotIn("AGENTDROID_RATE_LIMIT_RPM", env_example)
        self.assertNotIn("docker compose logs redroid server", readme_text)
        self.assertIn("api.typesafe.ai", readme_text)
        self.assertIn("TYPESAFE_API_KEY", readme_text)
        self.assertNotIn("central server", install_sh.lower())

        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["up", "--with-server"])

    def test_dns_and_android_version_aligned(self) -> None:
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (REPO_ROOT / "docker" / "redroid" / "Dockerfile").read_text(encoding="utf-8")
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertNotIn("192.168.1.1", compose)
        self.assertIn("REDROID_DNS:-1.1.1.1", compose)
        self.assertIn("redroid/redroid:11.0.0-latest", compose)
        self.assertIn("redroid/redroid:11.0.0-latest", dockerfile)
        self.assertIn("redroid/redroid:11.0.0-latest", env_example)

    def test_installer_pinned_opt_in_and_valid_syntax(self) -> None:
        install_sh = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("AGENTDROID_REF:-v0.3.0", install_sh)
        self.assertIn("--yes", install_sh)
        self.assertIn("--with-agent-configs", install_sh)
        self.assertIn("--with-shell-rc", install_sh)
        self.assertIn("--with-kernel-modules", install_sh)

        for script in ("install.sh", "scripts/provision-device.sh", "bin/agentdroid"):
            proc = subprocess.run(["bash", "-n", str(REPO_ROOT / script)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"bash -n failed for {script}: {proc.stderr}")

    def test_adb_has_no_subprocess_module_mock_sniffing(self) -> None:
        adb_src = (REPO_ROOT / "agentdroid" / "adb.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run.__module__", adb_src)

        adb = AdbDevice(serial="127.0.0.1:5555", use_rust=False)
        self.assertFalse(adb._use_rust_adb())


class TestSecurityAndApkVerification(unittest.TestCase):
    def test_verify_bundled_helper_apk_matches_manifest(self) -> None:
        res = verify_bundled_helper_apk(REPO_ROOT, strict=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["actual_sha256"], res["expected_sha256"])

    def test_verify_bundled_helper_apk_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper_dir = root / "packages" / "artemis-accessibility-helper"
            helper_dir.mkdir(parents=True)
            (helper_dir / "ArtemisAccessibilityHelper.apk").write_bytes(b"tampered")
            (helper_dir / "helper_manifest.json").write_text(
                json.dumps({"sha256": "0" * 64}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                verify_bundled_helper_apk(root, strict=True)
            non_strict = verify_bundled_helper_apk(root, strict=False)
            self.assertFalse(non_strict["ok"])

    def test_apk_url_validation_and_cache_isolation(self) -> None:
        with self.assertRaises(ValueError):
            validate_apk_url("http://example.com/app.apk")
        with self.assertRaises(ValueError):
            validate_apk_url("file:///tmp/app.apk")
        self.assertEqual(validate_apk_url("https://example.com/app.apk"), "https://example.com/app.apk")

        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            p1 = cache_path_for_apk_url(cdir, "https://a.example.com/app.apk")
            p2 = cache_path_for_apk_url(cdir, "https://b.example.com/app.apk")
            self.assertNotEqual(p1, p2)
            self.assertEqual(p1.parent, cdir)

        src, digest = parse_apk_source_checksum("sha256:" + ("a" * 64) + "@https://example.com/a.apk")
        self.assertEqual(src, "https://example.com/a.apk")
        self.assertEqual(digest, "a" * 64)

    def test_download_verified_apk_enforces_https_checksum_and_safe_cache(self) -> None:
        apk_bytes = _make_valid_apk_bytes(b"v1")
        apk_sha = hashlib.sha256(apk_bytes).hexdigest()

        class _FakeResp:
            def __init__(self, payload: bytes) -> None:
                self._buf = io.BytesIO(payload)

            def read(self, n: int = -1) -> bytes:
                return self._buf.read(n)

            def __enter__(self) -> _FakeResp:
                return self

            def __exit__(self, *args: object) -> bool:
                return False

        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            # Plain HTTP refused before any network call
            with self.assertRaises(ValueError):
                download_verified_apk("http://example.com/app.apk", cdir)

            # Safe mode requires checksum
            with self.assertRaises(PermissionError):
                download_verified_apk("https://example.com/app.apk", cdir, require_checksum=True)

            # Mismatched checksum fails and cleans up .part files
            with patch("urllib.request.urlopen", return_value=_FakeResp(apk_bytes)):
                with self.assertRaises(ValueError):
                    download_verified_apk(
                        "https://example.com/app.apk",
                        cdir,
                        expected_sha256="f" * 64,
                    )
            self.assertEqual(list(cdir.glob("*.part")), [])

            # Valid checksum downloads, caches with sidecar, and reuses cache on 2nd call
            with patch("urllib.request.urlopen", return_value=_FakeResp(apk_bytes)) as mock_open:
                path1, d1 = download_verified_apk(
                    "https://example.com/app.apk",
                    cdir,
                    expected_sha256=apk_sha,
                    require_checksum=True,
                )
                self.assertEqual(d1, apk_sha)
                self.assertTrue(path1.is_file())
                path2, d2 = download_verified_apk(
                    "https://example.com/app.apk",
                    cdir,
                    expected_sha256=apk_sha,
                    require_checksum=True,
                )
                self.assertEqual(path1, path2)
                self.assertEqual(d2, apk_sha)
                self.assertEqual(mock_open.call_count, 1)

    def test_safe_mode_shell_allowlist_and_injection_blocking(self) -> None:
        # Unsafe mode passes through
        self.assertEqual(validate_shell_command("rm -rf /tmp/x", safe_mode=False), "rm -rf /tmp/x")

        # Safe mode without allowlist blocks everything
        with self.assertRaises(PermissionError):
            validate_shell_command("pm list packages", safe_mode=True)

        # Safe mode with allowlist allows exact prefix matches
        self.assertEqual(
            validate_shell_command(
                "pm list packages -3",
                safe_mode=True,
                allowlist=("pm list packages",),
            ),
            "pm list packages -3",
        )

        # Blocks non-allowlisted commands
        with self.assertRaises(PermissionError):
            validate_shell_command("id", safe_mode=True, allowlist=("pm list packages",))

        # Blocks shell injection attempts even with allowlisted prefix
        for injected in (
            "pm list packages; id",
            "pm list packages && id",
            "pm list packages || id",
            "pm list packages | cat",
            "pm list packages $(id)",
            "pm list packages `id`",
            "pm list packages > /sdcard/out",
        ):
            with self.assertRaises(PermissionError):
                validate_shell_command(injected, safe_mode=True, allowlist=("pm list packages",))

    def test_safe_mode_enforced_in_pipeline_mcp_and_cli(self) -> None:
        # 1. Pipeline blocks pre_shell in safe_mode
        spec = PipelineSpec(
            serial="127.0.0.1:5555",
            auto_provision=False,
            check_crashes=False,
            dump_ui=False,
            safe_mode=True,
            pre_shell=["id"],
        )
        pipe = CompoundPipeline(spec)
        pipe.adb.connect = MagicMock(return_value=True)
        report = pipe.run()
        self.assertFalse(report["ok"])
        self.assertTrue(any("--safe" in e for e in report["errors"]))

        # 2. MCP server in safe_mode cannot be bypassed by workflow arguments
        server = McpServer(serial="127.0.0.1:5555", safe_mode=True)
        with patch.object(AdbDevice, "connect", return_value=True):
            resp = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {
                        "name": "mobile_run_workflow",
                        "arguments": {
                            "auto_provision": False,
                            "check_crashes": False,
                            "dump_ui": False,
                            "safe_mode": False,
                            "shell_allowlist": ["id"],
                            "pre_shell": ["id"],
                        },
                    },
                }
            )
        assert resp is not None
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertFalse(payload["ok"])
        self.assertTrue(any("--safe" in e for e in payload["errors"]))

        # 3. CLI `device shell --safe` blocks arbitrary commands cleanly
        parser = build_parser()
        args = parser.parse_args(["device", "shell", "id", "--safe", "-j"])
        with patch.object(AdbDevice, "connect", return_value=True), patch.object(
            AdbDevice, "shell", side_effect=AssertionError("shell must not execute in --safe mode")
        ):
            rc = cmd_device(args)
        self.assertEqual(rc, 1)

    def test_cmd_pipeline_no_longer_raises_name_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfile = Path(tmp) / "flow.json"
            pfile.write_text(
                json.dumps({"serial": "127.0.0.1:5555", "auto_provision": False, "dump_ui": False}),
                encoding="utf-8",
            )
            parser = build_parser()
            args = parser.parse_args(["pipeline", str(pfile), "--headless", "-j"])
            with patch.dict("os.environ", {"AGENTDROID_NO_DAEMON": "1"}), patch.object(
                CompoundPipeline, "run", return_value={"ok": True, "mode": "headless", "device": "127.0.0.1:5555"}
            ):
                rc = cmd_pipeline(args)
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
