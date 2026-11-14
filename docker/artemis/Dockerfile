# ==============================================================================
# AgentRedroid × Google Artemis Controller Container
# ==============================================================================
# Builds the Google Artemis autonomous Android agent runtime + Web/Stream Console
# and bundles the AgentRedroid (`agentdroid`) compound CLI & silent provisioner.
# ==============================================================================

ARG ARTEMIS_REPO=https://github.com/google/artemis.git
ARG ARTEMIS_REF=main

FROM node:22-bookworm-slim AS artemis-source
ARG ARTEMIS_REPO
ARG ARTEMIS_REF
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 --branch "${ARTEMIS_REF}" "${ARTEMIS_REPO}" /src/artemis

WORKDIR /src/artemis/apps/showcase_ui
RUN npm ci && npm run build


FROM python:3.12-slim AS wheel-builder
WORKDIR /build
COPY --from=artemis-source /src/artemis/ ./
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels ./packages/artemis-client \
    && python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .


FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    curl \
    ffmpeg \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=wheel-builder /wheels/ /wheels/
COPY --from=artemis-source /src/artemis/packages/artemis-accessibility-helper/ /app/packages/artemis-accessibility-helper/
COPY --from=artemis-source /src/artemis/config/ /app/config/

RUN pip install --no-cache-dir /wheels/artemis_client-*.whl \
    && pip install --no-cache-dir /wheels/artemis-*.whl \
    && rm -rf /wheels

# Copy AgentRedroid CLI package & silent device provisioner
COPY pyproject.toml /app/agentdroid-src/pyproject.toml
COPY agentdroid/ /app/agentdroid-src/agentdroid/
COPY bin/agentdroid /usr/local/bin/agentdroid
COPY scripts/provision-device.sh /app/scripts/provision-device.sh
COPY docker/artemis/entrypoint.sh /app/entrypoint.sh

RUN pip install --no-cache-dir -e /app/agentdroid-src \
    && chmod +x /usr/local/bin/agentdroid /app/scripts/provision-device.sh /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV ARTEMIS_APP_DIR=/app
ENV ARTEMIS_KEEP_DEVICE_AWAKE=true
ENV ARTEMIS_HIERARCHY_BACKEND=auto
ENV ARTEMIS_HELPER_AUTO_INSTALL=true
ENV ARTEMIS_DEFAULT_PROFILE=flash
ENV REDROID_ADDR=redroid:5555
ENV PORT=8000

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "apps.admin_console.server:app", "--host", "0.0.0.0", "--port", "8000"]
