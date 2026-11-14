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
DEVICE_FALLBACK_APK="/vendor/etc/artemis/ArtemisAccessibilityHelper.apk"

log() {
    if [[ "${QUIET}" != "1" ]]; then
        echo "[agentdroid:provision] $*" >&2
    fi
}

adb_s() {
    "${ADB_BIN}" -s "${SERIAL}" "$@"
}

# 1. Connect to TCP device if SERIAL looks like host:port
if [[ "${SERIAL}" == *:* ]]; then
    log "Connecting to ADB target ${SERIAL}..."
    "${ADB_BIN}" start-server >/dev/null 2>&1 || true
    "${ADB_BIN}" connect "${SERIAL}" >/dev/null 2>&1 || true
fi

log "Waiting for device ${SERIAL} to come online (timeout: ${BOOT_TIMEOUT}s)..."
elapsed=0
while ! adb_s get-state >/dev/null 2>&1; do
    if [[ "${SERIAL}" == *:* ]]; then
        "${ADB_BIN}" connect "${SERIAL}" >/dev/null 2>&1 || true
    fi
    sleep 1
    elapsed=$((elapsed + 1))
    if (( elapsed >= BOOT_TIMEOUT )); then
        echo "[agentdroid:provision] ERROR: Timed out waiting for ADB device ${SERIAL}" >&2
        exit 1
    fi
done

# 2. Elevate to root ADB (Redroid runs with ro.secure=0)
adb_s root >/dev/null 2>&1 || true
if [[ "${SERIAL}" == *:* ]]; then
    sleep 1
    "${ADB_BIN}" connect "${SERIAL}" >/dev/null 2>&1 || true
fi

# 3. Wait for sys.boot_completed=1 and package service
log "Waiting for Android system boot completion..."
while true; do
    boot_done="$(adb_s shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n' || true)"
    pm_ready="$(adb_s shell pm path android 2>/dev/null | tr -d '\r\n' || true)"
    if [[ "${boot_done}" == "1" && "${pm_ready}" == package:* ]]; then
        break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
    if (( elapsed >= BOOT_TIMEOUT )); then
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

    # Modern Android 16 UI/UX: System-wide Dark Theme (no blinding white screen)
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
    if [[ "${current_svcs}" == "null" || -z "${current_svcs}" ]]; then
        new_svcs="${HELPER_SERVICE}"
    elif [[ ":${current_svcs}:" != *":${HELPER_SERVICE}:"* ]]; then
        new_svcs="${current_svcs}:${HELPER_SERVICE}"
    else
        new_svcs="${current_svcs}"
    fi
    adb_s shell settings put secure enabled_accessibility_services "${new_svcs}"
    adb_s shell settings put secure accessibility_enabled 1
    sleep 0.4
    verify_svcs="$(adb_s shell settings get secure enabled_accessibility_services 2>/dev/null | tr -d '\r\n' || true)"
    if [[ ":${verify_svcs}:" == *":${HELPER_SERVICE}:"* ]]; then
        break
    fi
done

# Push session token if AGENTDROID_HELPER_TOKEN is provided
if [[ -n "${AGENTDROID_HELPER_TOKEN:-}" ]]; then
    adb_s shell am broadcast \
        -n "${HELPER_RECEIVER}" \
        -a "${HELPER_ACTION}" \
        --es token "${AGENTDROID_HELPER_TOKEN}" >/dev/null 2>&1 || true
fi

# 5. Grant runtime permissions to all third-party installed apps
log "Auto-granting runtime permissions to third-party packages..."
adb_s shell '
    for pkg in $(pm list packages -3 | cut -d: -f2 | tr -d "\r"); do
        for perm in $(dumpsys package "$pkg" | awk "/requested permissions:/{flag=1;next}/install permissions:|runtime permissions:/{flag=0}flag{print \$1}" | grep "^android.permission." | tr -d "\r:"); do
            pm grant "$pkg" "$perm" >/dev/null 2>&1 || true
        done
        appops set "$pkg" SYSTEM_ALERT_WINDOW allow >/dev/null 2>&1 || true
        appops set "$pkg" MANAGE_EXTERNAL_STORAGE allow >/dev/null 2>&1 || true
        appops set "$pkg" POST_NOTIFICATIONS allow >/dev/null 2>&1 || true
    done
' >/dev/null 2>&1 || true

log "Device ${SERIAL} is silently provisioned and ready for AI agent operations."
