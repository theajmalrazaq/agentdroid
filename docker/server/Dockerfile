# AgentDroid centralized server: Node + adb only. No LLM keys, no Artemis build.
FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends android-tools-adb ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/package.json server/package-lock.json ./
RUN npm ci --omit=dev --omit=peer
COPY server/src ./src
ENV AGENTDROID_HOST=0.0.0.0 AGENTDROID_PORT=8080 AGENTDROID_DATA_DIR=/data
USER node
EXPOSE 8080
CMD ["node", "src/cli.ts"]
