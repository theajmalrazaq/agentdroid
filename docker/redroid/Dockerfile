ARG REDROID_IMAGE=redroid/redroid:12.0.0_64only-latest
FROM ${REDROID_IMAGE}

# Bundle Artemis Accessibility Helper APK inside the image for instant provisioning
COPY packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk /vendor/etc/artemis/ArtemisAccessibilityHelper.apk
COPY packages/artemis-accessibility-helper/helper_manifest.json /vendor/etc/artemis/helper_manifest.json
COPY docker/redroid/silent-agent.prop /vendor/etc/artemis/silent-agent.prop
