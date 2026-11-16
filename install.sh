#!/usr/bin/env bash
# ==============================================================================
# AgentDroid (`agentdroid`) — One-Command Universal Installer & Setup
# ==============================================================================
# Usage:
#   ./install.sh
#   # OR one-liner from anywhere:
#   curl -fsSL https://raw.githubusercontent.com/theajmalrazaq/agentdroid/main/install.sh | bash
#
# What this single command does:
#   1. Clones/updates AgentDroid (if not already running inside the repo)
#   2. Installs host tools (adb, scrcpy, docker, python3) & Redroid kernel modules
#   3. Installs `agentdroid` globally on PATH (~/.local/bin & /usr/local/bin)
#   4. (no API keys or .env needed: your AI agent is the brain)
#   5. Injects `agentdroid` skills & rules into Antigravity, Claude Code, Codex,
#      Cursor, Windsurf, and ~/.agents so your AI agent immediately knows how to use it
#   6. Starts the silent Redroid stack + central server (`agentdroid up --headless`)
# ==============================================================================

set -euo pipefail

REPO_URL="${AGENTDROID_REPO_URL:-https://github.com/theajmalrazaq/agentdroid.git}"
INSTALL_DIR="${AGENTDROID_HOME:-${HOME}/.agentdroid}"
SKIP_STACK="${AGENTDROID_SKIP_STACK:-0}"

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
        info "Updating existing AgentDroid checkout at ${REPO_ROOT}..."
        git -C "${REPO_ROOT}" pull --ff-only || true
    else
        info "Cloning AgentDroid into ${REPO_ROOT}..."
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
    fi
    if ! grep -qw uinput /proc/misc 2>/dev/null; then
        info "Loading Linux uinput kernel module for Redroid virtual touchscreen..."
        run_privileged modprobe uinput >/dev/null 2>&1 || true
    fi
    if [[ -d /etc/modules-load.d ]]; then
        modules_conf="binder_linux\nashmem_linux\n"
        if grep -qw uinput /proc/misc 2>/dev/null || modinfo uinput >/dev/null 2>&1; then
            modules_conf+="uinput\n"
        fi
        printf "%b" "${modules_conf}" | run_privileged tee /etc/modules-load.d/agentdroid.conf >/dev/null 2>&1 || true
    fi
fi

# 3. Ensure ~/.local/bin is on PATH and symlink `agentdroid`
mkdir -p "${HOME}/.local/bin"
chmod +x "${REPO_ROOT}/bin/agentdroid" "${REPO_ROOT}/scripts/provision-device.sh"
ln -sf "${REPO_ROOT}/bin/agentdroid" "${HOME}/.local/bin/agentdroid"

if [[ -w /usr/local/bin ]]; then
    ln -sf "${REPO_ROOT}/bin/agentdroid" /usr/local/bin/agentdroid || true
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

# 4. Initialize .env from template if missing
if [[ ! -f "${REPO_ROOT}/.env" && -f "${REPO_ROOT}/.env.example" ]]; then
    cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
    if command -v docker >/dev/null 2>&1 && docker image inspect redroid/redroid:11.0.0-latest >/dev/null 2>&1; then
        sed -i 's|REDROID_IMAGE=.*|REDROID_IMAGE=redroid/redroid:11.0.0-latest|' "${REPO_ROOT}/.env"
    fi
fi

# 5. Run `agentdroid setup` to configure CLI, mount AI agent skills/rules into AI coding agents, and boot the silent device
SETUP_ARGS=("setup")
if [[ "${SKIP_STACK}" == "1" ]]; then
    SETUP_ARGS+=("--no-start")
fi

"${REPO_ROOT}/bin/agentdroid" "${SETUP_ARGS[@]}"

echo ""
ok "AgentDroid is installed and configured!"
printf "   • Global CLI:      \033[1magentdroid\033[0m\n"
printf "   • AI Agent Skills: Mounted into Antigravity, Claude Code, Codex, Cursor & Windsurf\n"
printf "   • Next Step:       Ask your AI agent:\n"
printf "     \033[1;32m\"Use agentdroid to install <app> and do <task>\"\033[0m\n"
printf "     or with live screen view:\n"
printf "     \033[1;32m\"Use agentdroid --watch to ...\"\033[0m\n\n"
