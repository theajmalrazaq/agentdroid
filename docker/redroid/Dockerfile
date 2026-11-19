ARG REDROID_IMAGE=redroid/redroid:11.0.0-latest
FROM ${REDROID_IMAGE}

# Android /init ignores SIGTERM; SIGKILL avoids Docker's 10s stop timeout on restart
STOPSIGNAL SIGKILL

# Bundle Artemis Accessibility Helper APK, InputDaemon DEX, and silent agent config
COPY packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk /vendor/etc/artemis/ArtemisAccessibilityHelper.apk
COPY packages/artemis-accessibility-helper/helper_manifest.json /vendor/etc/artemis/helper_manifest.json
COPY packages/agentdroid-input-daemon/agentdroid-input.dex /vendor/etc/artemis/agentdroid-input.dex
COPY docker/redroid/silent-agent.prop /vendor/etc/artemis/silent-agent.prop
COPY --chmod=0644 docker/redroid/agentdroid-touch.rc /vendor/etc/init/agentdroid-touch.rc
