"""Output formatting helpers for the AgentDroid CLI."""

from __future__ import annotations

import json
import sys
from typing import Any


def _print_output(data: dict[str, Any], *, as_json: bool) -> None:
    """Render a structured AgentDroid pipeline report as JSON or compact human text."""
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    ok = data.get("ok", True)
    status_icon = "✅" if ok else "✖"
    mode = data.get("mode", "headless")
    device = data.get("device", "")
    dur = data.get("duration_sec", 0.0)
    print(f"{status_icon} AgentDroid [{mode}] on {device} ({dur}s)")

    for pf in data.get("pushed_files") or []:
        print(f"  📤 Pushed:    {pf.get('local')} -> {pf.get('remote')}")

    for apk in data.get("installed_apks") or []:
        print(
            f"  📦 Installed: {apk.get('package') or apk.get('source')} "
            f"(permissions granted: {apk.get('permissions_granted')}, appops: {apk.get('appops_granted')})"
        )

    launched = data.get("launched_app")
    if isinstance(launched, dict) and launched.get("package"):
        print(f"  🚀 Launched:  {launched.get('component') or launched.get('package')}")

    for u in data.get("opened_urls") or []:
        print(f"  🌐 Opened:    {u.get('uri')}")

    for plf in data.get("pulled_files") or []:
        print(f"  📥 Pulled:    {plf.get('remote')} -> {plf.get('local')}")

    if data.get("clipboard") is not None:
        print(f"  📎 Clipboard: {data['clipboard']}")

    if data.get("notifications") is not None:
        notifs = data["notifications"]
        print(f"  🔔 Notifications ({len(notifs)}):")
        for n in notifs[:10]:
            print(f"     [{n.get('package')}] {n.get('title')}: {n.get('text')}")

    crashes = data.get("crashes")
    if isinstance(crashes, dict) and crashes.get("has_crashes"):
        print(
            f"  💥 Crashes detected! fatal={len(crashes.get('fatal_exceptions', []))}, "
            f"anr={len(crashes.get('anrs', []))}"
        )

    if data.get("screenshot"):
        print(f"  📸 Screenshot: {data['screenshot']}")

    ui_sum = data.get("ui_summary")
    if isinstance(ui_sum, dict):
        fg = ui_sum.get("foreground", {}).get("component") or "unknown"
        print(
            f"  🌲 UI Summary ({ui_sum.get('backend')}, fg={fg}): "
            f"{ui_sum.get('element_count')} interactive/labelled elements"
        )
        for el in (ui_sum.get("elements") or [])[:15]:
            print(f"     [{el['id']}] {el['label']} ({el['class']}) @{el['center']}")

    for err in data.get("errors") or []:
        print(f"  ❌ Error: {err}", file=sys.stderr)
