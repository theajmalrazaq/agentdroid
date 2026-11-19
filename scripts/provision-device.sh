#!/usr/bin/env bash
# ==============================================================================
# AgentDroid Silent Device Provisioner
# ==============================================================================
# Configures a Redroid / Android device for silent, zero-popup AI agent usage:
#   1. Connects over ADB and elevates to root (ro.secure=0)
#   2. Waits for full Android boot completion & package manager readiness
#   3. Disables animations, setup wizards, lockscreen, error popups & play protect
#   4. Mutes all audio streams for silent background execution
#   5. Pre-installs & enables the Artemis Accessibility Helper APK
#   6. Auto-grants runtime permissions to installed third-party apps
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ADB_BIN="${ADB_BIN:-adb}"
SERIAL="${1:-${ADB_DEVICE_SERIAL:-${REDROID_ADDR:-127.0.0.1:5555}}}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-120}"
QUIET="${QUIET:-0}"

HELPER_PACKAGE="com.artemis.helper"
HELPER_SERVICE="${HELPER_PACKAGE}/.ArtemisAccessibilityService"
HELPER_RECEIVER="${HELPER_PACKAGE}/.TokenReceiver"
HELPER_ACTION="${HELPER_PACKAGE}.SET_TOKEN"
BUNDLED_APK="${REPO_ROOT}/packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk"
BUNDLED_APK_MANIFEST="${REPO_ROOT}/packages/artemis-accessibility-helper/helper_manifest.json"
DEVICE_FALLBACK_APK="/vendor/etc/artemis/ArtemisAccessibilityHelper.apk"
BUNDLED_INPUT_DEX="${REPO_ROOT}/packages/agentdroid-input-daemon/agentdroid-input.dex"
DEVICE_VENDOR_INPUT_DEX="/vendor/etc/artemis/agentdroid-input.dex"
DEVICE_TMP_INPUT_DEX="/data/local/tmp/agentdroid-input.dex"
DEVICE_INPUT_TOKEN="/data/local/tmp/.agentdroid_input_token"
INPUT_DAEMON_PORT="${AGENTDROID_INPUT_PORT:-18889}"
BUNDLED_FAST_DUMP_DEX="${REPO_ROOT}/packages/agentdroid-fast-dump/agentdroid-fast-dump.dex"
DEVICE_TMP_FAST_DUMP_DEX="/data/local/tmp/agentdroid-fast-dump.dex"
FAST_DUMP_PORT="${AGENTDROID_FAST_DUMP_PORT:-18890}"

log() {
    if [[ "${QUIET}" != "1" ]]; then
        echo "[agentdroid:provision] $*" >&2
    fi
}

adb_s() {
    "${ADB_BIN}" -s "${SERIAL}" "$@"
}

adbd_tcp_ready() {
    if [[ "${SERIAL}" != *:* ]]; then
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        PYTHONPATH="${REPO_ROOT}" python3 -c '
import sys
from agentdroid.adb import probe_adbd_tcp
h, _, p = sys.argv[1].rpartition(":")
sys.exit(0 if (not p.isdigit() or probe_adbd_tcp(h, int(p), 0.35)) else 1)
' "${SERIAL}" >/dev/null 2>&1
        return $?
    fi
    return 0
}

# 1. Connect to TCP device if SERIAL looks like host:port
if [[ "${SERIAL}" == *:* ]]; then
    log "Connecting to ADB target ${SERIAL}..."
    "${ADB_BIN}" start-server >/dev/null 2>&1 || true
    if ! adb_s get-state >/dev/null 2>&1 && adbd_tcp_ready; then
        "${ADB_BIN}" connect "${SERIAL}" >/dev/null 2>&1 || true
    fi
fi

log "Waiting for device ${SERIAL} to come online (timeout: ${BOOT_TIMEOUT}s)..."
conn_start="${SECONDS}"
while ! adb_s get-state >/dev/null 2>&1; do
    if [[ "${SERIAL}" == *:* ]] && adbd_tcp_ready; then
        "${ADB_BIN}" connect "${SERIAL}" >/dev/null 2>&1 || true
    fi
    sleep 0.25
    if (( SECONDS - conn_start >= BOOT_TIMEOUT )); then
        echo "[agentdroid:provision] ERROR: Timed out waiting for ADB device ${SERIAL}" >&2
        exit 1
    fi
done

# 2. Elevate to root ADB (Redroid runs with ro.secure=0)
if [[ "$(adb_s shell id -u 2>/dev/null | tr -d '\r' || true)" != "0" ]]; then
    adb_s root >/dev/null 2>&1 || true
    if [[ "${SERIAL}" == *:* ]]; then
        sleep 0.5
        if adbd_tcp_ready; then
            "${ADB_BIN}" connect "${SERIAL}" >/dev/null 2>&1 || true
        fi
    fi
fi

# 3. Wait for sys.boot_completed=1 and package service
log "Waiting for Android system boot completion..."
boot_start="${SECONDS}"
while true; do
    boot_probe="$(adb_s shell 'if [ "$(getprop sys.boot_completed)" = "1" ]; then echo BOOT=1; pm path android; fi' 2>/dev/null | tr -d '\r' || true)"
    if [[ "${boot_probe}" == *BOOT=1* && "${boot_probe}" == *package:* ]]; then
        break
    fi
    sleep 0.25
    if (( SECONDS - boot_start >= BOOT_TIMEOUT )); then
        echo "[agentdroid:provision] ERROR: Timed out waiting for sys.boot_completed on ${SERIAL}" >&2
        exit 1
    fi
done

log "Applying silent AI agent device configuration..."
adb_s shell '
    # Disable all UI animations for fast, deterministic agent perception & actions
    settings put global window_animation_scale 0.0
    settings put global transition_animation_scale 0.0
    settings put global animator_duration_scale 0.0

    # Modern UI/UX: System-wide Dark Theme (no blinding white screen)
    cmd uimode night yes >/dev/null 2>&1 || true
    settings put secure ui_night_mode 2 >/dev/null 2>&1 || true

    # Modern Gesture Navigation (replaces legacy 3-button navigation bar)
    cmd overlay enable com.android.internal.systemui.navbar.gestural >/dev/null 2>&1 || true
    settings put secure navigation_mode 2 >/dev/null 2>&1 || true

    # Clean UI/UX: disable touch vibrations, haptic feedback, and camera/lock sounds
    settings put system haptic_feedback_enabled 0 >/dev/null 2>&1 || true
    settings put system sound_effects_enabled 0 >/dev/null 2>&1 || true
    settings put system lockscreen_sounds_enabled 0 >/dev/null 2>&1 || true
    settings put system font_scale 1.0 >/dev/null 2>&1 || true
    settings put system time_12_24 24 >/dev/null 2>&1 || true

    # Mark device as provisioned & skip first-run setup wizards
    settings put global device_provisioned 1
    settings put secure user_setup_complete 1

    # Keep screen awake indefinitely & dismiss lockscreen/keyguard
    settings put global stay_on_while_plugged_in 7
    settings put system screen_off_timeout 2147483647
    locksettings set-disabled true >/dev/null 2>&1 || true
    wm dismiss-keyguard >/dev/null 2>&1 || true
    input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true

    # Suppress blocking system dialogs, ANR/crash popups, Play Protect & ADB install verifiers
    settings put global hide_error_dialogs 1
    settings put global anr_show_background 0
    settings put global package_verifier_enable 0
    settings put global verifier_verify_adb_installs 0
    settings put global heads_up_notifications_enabled 0
    settings put secure spell_checker_enabled 0
    settings put secure show_ime_with_hard_keyboard 0
    settings put secure immersive_mode_confirmations confirmed

    # Mute all audio streams so the device operates 100% silently
    for stream in 0 1 2 3 4 5; do
        cmd media_session volume --stream "$stream" --set 0 >/dev/null 2>&1 || true
        media volume --stream "$stream" --set 0 >/dev/null 2>&1 || true
    done
    cmd audio set-ringer-mode SILENT >/dev/null 2>&1 || true
'

# 4. Install & enable Artemis Accessibility Helper APK
log "Ensuring Artemis Accessibility Helper (${HELPER_PACKAGE}) is installed and active..."
installed_ver="$(adb_s shell dumpsys package "${HELPER_PACKAGE}" 2>/dev/null | grep -oE 'versionCode=[0-9]+' | head -n1 | cut -d= -f2 || true)"

if [[ -z "${installed_ver}" ]]; then
    if [[ -f "${BUNDLED_APK}" ]]; then
        if [[ -f "${BUNDLED_APK_MANIFEST}" ]] && command -v python3 >/dev/null 2>&1; then
            log "Verifying SHA-256 checksum of bundled ArtemisAccessibilityHelper.apk..."
            PYTHONPATH="${REPO_ROOT}" python3 -c '
import sys
from pathlib import Path
from agentdroid.security import verify_bundled_helper_apk
verify_bundled_helper_apk(Path(sys.argv[1]), strict=True)
' "${REPO_ROOT}"
        elif [[ -f "${BUNDLED_APK_MANIFEST}" ]] && command -v sha256sum >/dev/null 2>&1; then
            expected_sha="$(grep -oE '"sha256"[[:space:]]*:[[:space:]]*"[0-9a-fA-F]{64}"' "${BUNDLED_APK_MANIFEST}" | grep -oE '[0-9a-fA-F]{64}' | head -n1)"
            actual_sha="$(sha256sum "${BUNDLED_APK}" | awk '{print $1}')"
            if [[ -z "${expected_sha}" || "${actual_sha,,}" != "${expected_sha,,}" ]]; then
                echo "[agentdroid:provision] ERROR: ArtemisAccessibilityHelper.apk SHA-256 mismatch (expected=${expected_sha}, got=${actual_sha})" >&2
                exit 1
            fi
        fi
        log "Installing bundled ArtemisAccessibilityHelper.apk from host..."
        adb_s install -r -g "${BUNDLED_APK}" >/dev/null
    elif adb_s shell "[ -f ${DEVICE_FALLBACK_APK} ]" >/dev/null 2>&1; then
        log "Installing ArtemisAccessibilityHelper.apk from device vendor partition..."
        adb_s shell pm install -r -g "${DEVICE_FALLBACK_APK}" >/dev/null
    else
        log "WARNING: ArtemisAccessibilityHelper.apk not found at ${BUNDLED_APK}"
    fi
fi

# Stop any uiautomator2 holder that could suppress AccessibilityService binding
adb_s shell '
    am force-stop com.github.uiautomator >/dev/null 2>&1 || true
    pkill -f "com.wetest.uia2.Main" >/dev/null 2>&1 || true
    appops set com.artemis.helper ACCESS_RESTRICTED_SETTINGS allow >/dev/null 2>&1 || true
' || true

# Enable Accessibility Service in secure settings (retry to ensure AccessibilityManager binds it)
for attempt in 1 2 3 4 5; do
    current_svcs="$(adb_s shell settings get secure enabled_accessibility_services 2>/dev/null | tr -d '\r\n' || true)"
    if [[ ":${current_svcs}:" == *":${HELPER_SERVICE}:"* ]]; then
        acc_on="$(adb_s shell settings get secure accessibility_enabled 2>/dev/null | tr -d '\r\n' || true)"
        if [[ "${acc_on}" != "1" ]]; then
            adb_s shell settings put secure accessibility_enabled 1
        fi
        break
    elif [[ "${current_svcs}" == "null" || -z "${current_svcs}" ]]; then
        new_svcs="${HELPER_SERVICE}"
    else
        new_svcs="${current_svcs}:${HELPER_SERVICE}"
    fi
    adb_s shell settings put secure enabled_accessibility_services "${new_svcs}"
    adb_s shell settings put secure accessibility_enabled 1
    sleep 0.4
    verify_svcs="$(adb_s shell settings get secure enabled_accessibility_services 2>/dev/null | tr -d '\r\n' || true)"
    if [[ ":${verify_svcs}:" == *":${HELPER_SERVICE}:"* ]]; then
        break
    fi
done

# Resolve or generate shared session token for Artemis Helper + InputDaemon
RESOLVED_TOKEN="${AGENTDROID_HELPER_TOKEN:-}"
if [[ -z "${RESOLVED_TOKEN}" ]]; then
    for tok_file in \
        "${TMPDIR:-/tmp}/agentdroid/helper-token/session.token" \
        "${HOME}/.cache/agentdroid/helper-token/session.token" \
        "${TMPDIR:-/tmp}/artemis/helper-token/session.token" \
        "${HOME}/.cache/artemis/helper-token/session.token"; do
        if [[ -f "${tok_file}" ]]; then
            RESOLVED_TOKEN="$(tr -d ' \t\r\n' < "${tok_file}" 2>/dev/null || true)"
            [[ -n "${RESOLVED_TOKEN}" ]] && break
        fi
    done
fi
if [[ -z "${RESOLVED_TOKEN}" ]]; then
    tok_dir="${TMPDIR:-/tmp}/agentdroid/helper-token"
    mkdir -p "${tok_dir}" 2>/dev/null || true
    RESOLVED_TOKEN="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \t\r\n')"
    if [[ -n "${RESOLVED_TOKEN}" ]]; then
        (umask 077 && printf '%s' "${RESOLVED_TOKEN}" > "${tok_dir}/session.token") 2>/dev/null || true
    fi
fi

# Push session token to Artemis Helper
if [[ -n "${RESOLVED_TOKEN}" ]]; then
    adb_s shell am broadcast \
        -n "${HELPER_RECEIVER}" \
        -a "${HELPER_ACTION}" \
        --es token "${RESOLVED_TOKEN}" >/dev/null 2>&1 || true
fi

# Activate conditional uinputd if host kernel exposes /dev/uinput and no touchscreen is bound yet
adb_s shell '
    if grep -qw uinput /proc/misc 2>/dev/null && ! dumpsys input | grep -q "0x00001002"; then
        start vendor.agentdroid_uinputd >/dev/null 2>&1 || nohup /vendor/bin/uinputd </dev/null >/dev/null 2>&1 &
    fi
' >/dev/null 2>&1 || true

# Deploy and start low-latency AgentDroid InputDaemon (~5ms direct InputManager injection)
log "Ensuring AgentDroid InputDaemon (127.0.0.1:${INPUT_DAEMON_PORT}) is running..."
dex_updated=0
if [[ -f "${BUNDLED_INPUT_DEX}" ]]; then
    host_dex_size="$(wc -c < "${BUNDLED_INPUT_DEX}" | tr -d ' ')"
    dev_dex_size="$(adb_s shell "if [ -f ${DEVICE_VENDOR_INPUT_DEX} ] && [ ! -s ${DEVICE_TMP_INPUT_DEX} ]; then cp -f ${DEVICE_VENDOR_INPUT_DEX} ${DEVICE_TMP_INPUT_DEX}; fi; wc -c < ${DEVICE_TMP_INPUT_DEX} 2>/dev/null || echo 0" 2>/dev/null | tr -d '\r\n ' || echo 0)"
    if [[ "${dev_dex_size}" != "${host_dex_size}" ]]; then
        if adb_s push "${BUNDLED_INPUT_DEX}" "${DEVICE_TMP_INPUT_DEX}" >/dev/null 2>&1; then
            dex_updated=1
        fi
    fi
else
    adb_s shell "if [ -f ${DEVICE_VENDOR_INPUT_DEX} ]; then cp -f ${DEVICE_VENDOR_INPUT_DEX} ${DEVICE_TMP_INPUT_DEX}; fi" >/dev/null 2>&1 || true
fi

if [[ -n "${RESOLVED_TOKEN}" ]]; then
    adb_s shell "
        if [ -s ${DEVICE_TMP_INPUT_DEX} ]; then
            prev_tok=\"\$(cat ${DEVICE_INPUT_TOKEN} 2>/dev/null | tr -d '\\r\\n' || true)\"
            umask 077 && printf '%s\\n' '${RESOLVED_TOKEN}' > ${DEVICE_INPUT_TOKEN} && chmod 600 ${DEVICE_INPUT_TOKEN}
            pids=\"\$(ps -A -o PID,NAME,ARGS | sed -n 's/^[[:space:]]*\\([0-9][0-9]*\\)[[:space:]]\\{1,\\}app_process[^[:space:]]*[[:space:]].*InputDaemon.*/\\1/p')\"
            if [ \"${dex_updated}\" = '1' ] || [ \"\${prev_tok}\" != '${RESOLVED_TOKEN}' ] || [ -z \"\${pids}\" ]; then
                for p in \${pids}; do [ \"\${p}\" != \"\$\$\" ] && kill \"\${p}\" 2>/dev/null || true; done
                CLASSPATH=${DEVICE_TMP_INPUT_DEX} nohup app_process / com.agentdroid.InputDaemon ${INPUT_DAEMON_PORT} ${DEVICE_INPUT_TOKEN} </dev/null >/dev/null 2>&1 &
            fi
        fi
    " >/dev/null 2>&1 || true

    # Pre-warm FastDump (127.0.0.1:18890) for instant multi-window / WebView hierarchy dumps
    if [[ -f "${BUNDLED_FAST_DUMP_DEX}" ]]; then
        fast_host_size="$(wc -c < "${BUNDLED_FAST_DUMP_DEX}" | tr -d ' ')"
        fast_dev_size="$(adb_s shell "wc -c < ${DEVICE_TMP_FAST_DUMP_DEX} 2>/dev/null || echo 0" 2>/dev/null | tr -d '\r\n ' || echo 0)"
        if [[ "${fast_dev_size}" != "${fast_host_size}" ]]; then
            adb_s push "${BUNDLED_FAST_DUMP_DEX}" "${DEVICE_TMP_FAST_DUMP_DEX}" >/dev/null 2>&1 || true
        fi
        adb_s shell "
            if [ -s ${DEVICE_TMP_FAST_DUMP_DEX} ]; then
                pids=\"\$(ps -A -o PID,NAME,ARGS | sed -n 's/^[[:space:]]*\\([0-9][0-9]*\\)[[:space:]]\\{1,\\}app_process[^[:space:]]*[[:space:]].*FastDump.*/\\1/p')\"
                if [ -z \"\${pids}\" ]; then
                    CLASSPATH=/system/framework/uiautomator.jar:${DEVICE_TMP_FAST_DUMP_DEX} nohup app_process / com.agentdroid.FastDump ${FAST_DUMP_PORT} ${DEVICE_INPUT_TOKEN} </dev/null >/dev/null 2>&1 &
                fi
            fi
        " >/dev/null 2>&1 || true
    fi
fi

# 5. Grant runtime permissions to all third-party installed apps
log "Auto-granting runtime permissions to third-party packages..."
adb_s shell '
    for pkg in $(pm list packages -3 | cut -d: -f2 | tr -d "\r"); do
        [ "$pkg" = "com.artemis.helper" ] && continue
        for perm in $(dumpsys package "$pkg" | awk "/requested permissions:/{flag=1;next}/install permissions:|runtime permissions:/{flag=0}flag{print \$1}" | grep "^android.permission." | tr -d "\r:"); do
            pm grant "$pkg" "$perm" >/dev/null 2>&1 || true
        done
        appops set "$pkg" SYSTEM_ALERT_WINDOW allow >/dev/null 2>&1 || true
        appops set "$pkg" MANAGE_EXTERNAL_STORAGE allow >/dev/null 2>&1 || true
        appops set "$pkg" POST_NOTIFICATIONS allow >/dev/null 2>&1 || true
    done
' >/dev/null 2>&1 || true

log "Device ${SERIAL} is silently provisioned and ready for AI agent operations."
