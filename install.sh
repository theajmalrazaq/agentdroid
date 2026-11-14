#!/usr/bin/env bash
# ==============================================================================
# AgentRedroid (`agentdroid`) — One-Command Universal Installer & Setup
# ==============================================================================
# Usage:
#   ./install.sh
#   # OR one-liner from anywhere:
#   curl -fsSL https://raw.githubusercontent.com/theajmalrazaq/agentsredroid/master/install.sh | bash
#
# What this single command does:
#   1. Clones/updates AgentRedroid (if not already running inside the repo)
#   2. Installs host tools (adb, scrcpy, docker, python3) & Redroid kernel modules
#   3. Installs `agentdroid` globally on PATH (~/.local/bin & /usr/local/bin)
#   4. Configures .env (auto-detects or prompts for GEMINI_API_KEY / LLM key)
#   5. Injects `agentdroid` skills & rules into Antigravity, Claude Code, Codex,
#      Cursor, Windsurf, and ~/.agents so your AI agent immediately knows how to use it
#   6. Starts the silent Redroid + Artemis stack (`agentdroid up --headless`)
# ==============================================================================

set -euo pipefail

REPO_URL="${AGENTDROID_REPO_URL:-https://github.com/theajmalrazaq/agentsredroid.git}"
INSTALL_DIR="${AGENTDROID_HOME:-${HOME}/.agentdroid}"
SKIP_STACK="${AGENTDROID_SKIP_STACK:-0}"
API_KEY_ARG="${1:-${GEMINI_API_KEY:-${OPENAI_API_KEY:-${ANTHROPIC_API_KEY:-${OPEN_ROUTER_API_KEY:-}}}}}"

info()  { printf "\033[1;36m[agentdroid]\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m[agentdroid] ✓\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[agentdroid] !\033[0m %s\n" "$*" >&2; }

run_privileged() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
        sudo "$@"
    elif command -v sudo >/dev/null 2>&1 && [[ -t 0 ]]; then
        sudo "$@"
    else
        return 1
    fi
}

# 1. Locate or clone repository
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [[ -n "${SCRIPT_PATH}" && -f "$(dirname "${SCRIPT_PATH}")/pyproject.toml" && -d "$(dirname "${SCRIPT_PATH}")/agentdroid" ]]; then
    REPO_ROOT="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
else
    REPO_ROOT="${INSTALL_DIR}/repo"
    mkdir -p "${INSTALL_DIR}"
    if [[ -d "${REPO_ROOT}/.git" ]]; then
        info "Updating existing AgentRedroid checkout at ${REPO_ROOT}..."
        git -C "${REPO_ROOT}" pull --ff-only || true
    else
        info "Cloning AgentRedroid into ${REPO_ROOT}..."
        git clone --depth 1 "${REPO_URL}" "${REPO_ROOT}"
    fi
fi

# 2. Install system packages (adb, scrcpy) & Linux kernel modules (binder_linux, ashmem_linux)
info "Checking host dependencies (adb, scrcpy, docker, python3)..."
MISSING_PKGS=()
command -v adb >/dev/null 2>&1 || MISSING_PKGS+=("adb")
command -v scrcpy >/dev/null 2>&1 || MISSING_PKGS+=("scrcpy")
command -v python3 >/dev/null 2>&1 || MISSING_PKGS+=("python3")
command -v curl >/dev/null 2>&1 || MISSING_PKGS+=("curl")

if (( ${#MISSING_PKGS[@]} > 0 )); then
    info "Installing missing host tools: ${MISSING_PKGS[*]}..."
    if command -v apt-get >/dev/null 2>&1; then
        run_privileged apt-get update -qq && run_privileged apt-get install -y -qq "${MISSING_PKGS[@]}" || \
            warn "Could not auto-install packages via apt-get (continuing)."
    elif command -v dnf >/dev/null 2>&1; then
        run_privileged dnf install -y "${MISSING_PKGS[@]}" || true
    elif command -v pacman >/dev/null 2>&1; then
        run_privileged pacman -Sy --noconfirm "${MISSING_PKGS[@]}" || true
    elif command -v brew >/dev/null 2>&1; then
        brew install "${MISSING_PKGS[@]}" || true
    fi
fi

if [[ "$(uname -s)" == "Linux" ]]; then
    if ! grep -q binder /proc/filesystems 2>/dev/null; then
        info "Loading Linux kernel modules for Redroid (binder_linux, ashmem_linux)..."
        if command -v apt-get >/dev/null 2>&1; then
            run_privileged apt-get install -y -qq "linux-modules-extra-$(uname -r)" >/dev/null 2>&1 || true
        fi
        run_privileged modprobe binder_linux devices="binder,hwbinder,vndbinder" >/dev/null 2>&1 || true
        run_privileged modprobe ashmem_linux >/dev/null 2>&1 || true
        if [[ -d /etc/modules-load.d ]]; then
            printf "binder_linux\nashmem_linux\n" | run_privileged tee /etc/modules-load.d/agentdroid.conf >/dev/null 2>&1 || true
        fi
    fi
fi

# 3. Ensure ~/.local/bin is on PATH and symlink `agentdroid`
mkdir -p "${HOME}/.local/bin"
chmod +x "${REPO_ROOT}/bin/agentdroid" "${REPO_ROOT}/scripts/provision-device.sh"
ln -sf "${REPO_ROOT}/bin/agentdroid" "${HOME}/.local/bin/agentdroid"
ln -sf "${REPO_ROOT}/bin/agentdroid" "${HOME}/.local/bin/agentsredroid"

if [[ -w /usr/local/bin ]]; then
    ln -sf "${REPO_ROOT}/bin/agentdroid" /usr/local/bin/agentdroid || true
    ln -sf "${REPO_ROOT}/bin/agentdroid" /usr/local/bin/agentsredroid || true
fi

for rc_file in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.profile"; do
    if [[ -f "${rc_file}" ]] && ! grep -q '.local/bin' "${rc_file}" 2>/dev/null; then
        printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "${rc_file}"
    fi
done
export PATH="${HOME}/.local/bin:${PATH}"

# Also install editable Python package via uv or pip if available cleanly
if command -v uv >/dev/null 2>&1; then
    uv tool install --force -e "${REPO_ROOT}" >/dev/null 2>&1 || true
fi

# 4. Optional LLM API key detection (only if user explicitly exported one)
if [[ -z "${API_KEY_ARG}" && -f "${REPO_ROOT}/.env" ]]; then
    if grep -qE '^(GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|OPEN_ROUTER_API_KEY)=.+' "${REPO_ROOT}/.env" 2>/dev/null; then
        API_KEY_ARG="__already_set__"
    fi
fi

# 5. Run `agentdroid setup` to configure CLI, mount AI agent skills/rules into AI coding agents, and boot the silent device
SETUP_ARGS=("setup")
if [[ -n "${API_KEY_ARG}" && "${API_KEY_ARG}" != "__already_set__" ]]; then
    SETUP_ARGS+=("--api-key" "${API_KEY_ARG}")
fi
if [[ "${SKIP_STACK}" == "1" ]]; then
    SETUP_ARGS+=("--no-start")
fi

"${REPO_ROOT}/bin/agentdroid" "${SETUP_ARGS[@]}"

echo ""
ok "AgentRedroid is installed and configured!"
printf "   • Global CLI:      \033[1magentdroid\033[0m\n"
printf "   • AI Agent Skills: Mounted into Antigravity, Claude Code, Codex, Cursor & Windsurf\n"
printf "   • Next Step:       Ask your AI agent:\n"
printf "     \033[1;32m\"Use agentdroid to install <app> and do <task>\"\033[0m\n"
printf "     or with live screen view:\n"
printf "     \033[1;32m\"Use agentdroid --watch to ...\"\033[0m\n\n"
