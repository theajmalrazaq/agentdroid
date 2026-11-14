#!/usr/bin/env bash
set -euo pipefail

REDROID_ADDR="${REDROID_ADDR:-redroid:5555}"
AUTO_PROVISION="${AUTO_PROVISION:-true}"

echo "[agentdroid:artemis] Starting ADB server..."
adb start-server >/dev/null 2>&1 || true

if [[ "${AUTO_PROVISION}" == "true" && -n "${REDROID_ADDR}" ]]; then
    echo "[agentdroid:artemis] Launching background silent device provisioner for ${REDROID_ADDR}..."
    (
        /app/scripts/provision-device.sh "${REDROID_ADDR}" || \
            echo "[agentdroid:artemis] WARNING: Initial device provisioning returned non-zero; will retry on task execution."
    ) &
fi

exec "$@"
