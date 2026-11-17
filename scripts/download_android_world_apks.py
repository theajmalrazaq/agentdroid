#!/usr/bin/env python3
"""Download and cache official Google AndroidWorld benchmark APKs."""

import os
from pathlib import Path
import subprocess
import sys
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
APKS_DIR = REPO_ROOT / "packages" / "android-world-apks"
GCS_BASE = "https://storage.googleapis.com/gresearch/android_world"

# Core APKs required for AndroidWorld benchmark tasks
ANDROID_WORLD_APKS = [
    ("audio_recorder", "com.dimowner.audiorecorder_926.apk", "com.dimowner.audiorecorder"),
    ("markor", "net.gsantner.markor_146.apk", "net.gsantner.markor"),
    ("simple_calendar", "com.simplemobiletools.calendar.pro_238.apk", "com.simplemobiletools.calendar.pro"),
    ("tasks", "org.tasks_130605.apk", "org.tasks"),
    ("simple_draw", "com.simplemobiletools.draw.pro_79.apk", "com.simplemobiletools.draw.pro"),
    ("simple_gallery", "com.simplemobiletools.gallery.pro_396.apk", "com.simplemobiletools.gallery.pro"),
    ("simple_sms", "com.simplemobiletools.smsmessenger_85.apk", "com.simplemobiletools.smsmessenger"),
    ("broccoli_recipes", "com.flauschcode.broccoli_1020600.apk", "com.flauschcode.broccoli"),
    ("pro_expense", "com.arduia.expense_11.apk", "com.arduia.expense"),
    ("retro_music", "code.name.monkey.retromusic_10603.apk", "code.name.monkey.retromusic"),
    ("open_tracks", "de.dennisguse.opentracks_5705.apk", "de.dennisguse.opentracks"),
    ("clipper", "clipper.apk", "ca.zgrs.clipper"),
    ("androidworld_helper", "androidworld.apk", "com.google.android.apps.androidworld"),
]


def download_apks() -> dict[str, Path]:
    APKS_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: dict[str, Path] = {}
    for name, apk_filename, pkg in ANDROID_WORLD_APKS:
        dest = APKS_DIR / apk_filename
        if not dest.is_file() or dest.stat().st_size < 1000:
            url = f"{GCS_BASE}/{apk_filename}"
            print(f"Downloading {name} ({apk_filename}) from {url}...")
            try:
                urllib.request.urlretrieve(url, dest)
                print(f"  -> Saved {dest.name} ({round(dest.stat().st_size / 1024 / 1024, 2)} MB)")
            except Exception as e:
                print(f"  -> ERROR downloading {apk_filename}: {e}", file=sys.stderr)
                continue
        else:
            print(f"Cached {name} ({dest.name}, {round(dest.stat().st_size / 1024 / 1024, 2)} MB)")
        downloaded[pkg] = dest
    return downloaded


def install_all(serial: str = "127.0.0.1:5555") -> None:
    apks = download_apks()
    from agentdroid.adb import AdbDevice
    adb = AdbDevice(serial=serial)
    if not adb.connect(timeout=10.0):
        print(f"Failed to connect to ADB device {serial}", file=sys.stderr)
        return

    installed = adb.list_third_party_packages()
    print(f"\nInstalling missing APKs onto {serial}...")
    for pkg, path in apks.items():
        if pkg in installed:
            print(f"  Already installed: {pkg}")
            continue
        print(f"  Installing {pkg} ({path.name})...")
        res = adb.install_apk(str(path), grant_permissions=True)
        print(f"    -> package: {getattr(res, 'package', res)}, duration: {getattr(res, 'duration_sec', 0)}s")


if __name__ == "__main__":
    serial = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:5555"
    install_all(serial)
