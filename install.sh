#!/usr/bin/env bash
# ==============================================================================
# AgentDroid (`agentdroid`) — Safe, Opt-In Installer & Setup
# ==============================================================================
# Usage:
#   ./install.sh [OPTIONS]
#   # OR pinned release tag:
#   curl -fsSL https://raw.githubusercontent.com/theajmalrazaq/agentdroid/v0.3.0/install.sh | bash
#
# By default, invasive host modifications (apt/dnf/pacman packages,
# /etc/modules-load.d, /usr/local/bin, shell rc PATH edits, and global AI
# coding assistant configs) require interactive confirmation or explicit flags:
#   -y, --yes                   Approve all opt-in setup prompts non-interactively
#       --ref <tag|branch>      Git release tag or branch to clone (default: v0.3.0)
#       --with-system-deps      Install missing host tools (adb, scrcpy, python3, curl)
#       --with-kernel-modules   Load binder/ashmem/uinput and write /etc/modules-load.d
#       --with-shell-rc         Append ~/.local/bin to ~/.bashrc / ~/.zshrc / ~/.profile
#       --with-system-bin       Symlink agentdroid into /usr/local/bin
#       --with-agent-configs    Mount skills/rules/MCP into Claude, Codex, Cursor, Gemini, Windsurf
#       --no-start              Skip starting the local Redroid Docker container
#   -h, --help                  Show this help message
# ==============================================================================

set -euo pipefail

REPO_URL="${AGENTDROID_REPO_URL:-https://github.com/theajmalrazaq/agentdroid.git}"
REPO_REF="${AGENTDROID_REF:-v0.3.0}"
INSTALL_DIR="${AGENTDROID_HOME:-${HOME}/.agentdroid}"
SKIP_STACK="${AGENTDROID_SKIP_STACK:-0}"

AUTO_YES=0
OPT_SYSTEM_DEPS=0
OPT_KERNEL_MODULES=0
OPT_SHELL_RC=0
OPT_SYSTEM_BIN=0
OPT_AGENT_CONFIGS=0

usage() {
    sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            AUTO_YES=1
            shift
            ;;
        --ref)
            [[ $# -ge 2 ]] || { echo "Error: --ref requires a value" >&2; exit 2; }
            REPO_REF="$2"
            shift 2
            ;;
        --with-system-deps)
            OPT_SYSTEM_DEPS=1
            shift
            ;;
        --with-kernel-modules)
            OPT_KERNEL_MODULES=1
            shift
            ;;
        --with-shell-rc)
            OPT_SHELL_RC=1
            shift
            ;;
        --with-system-bin)
            OPT_SYSTEM_BIN=1
            shift
            ;;
        --with-agent-configs)
            OPT_AGENT_CONFIGS=1
            shift
            ;;
        --no-start)
            SKIP_STACK=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1 (use --help for usage)" >&2
            exit 2
            ;;
    esac
done

info()  { printf "\033[1;36m[agentdroid]\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m[agentdroid] ✓\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[agentdroid] !\033[0m %s\n" "$*" >&2; }
err()   { printf "\033[1;31m[agentdroid] ✖\033[0m %s\n" "$*" >&2; }

confirm_opt_in() {
    local flag_val="$1"
    local prompt="$2"
    if [[ "${flag_val}" == "1" || "${AUTO_YES}" == "1" ]]; then
        return 0
    fi
    if [[ -t 0 ]]; then
        local reply=""
        read -r -p "[agentdroid] ${prompt} [y/N]: " reply
        [[ "${reply}" =~ ^[Yy]([Ee][Ss])?$ ]]
        return $?
    fi
    return 1
}

run_privileged() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        sudo "$@"
    elif command -v sudo >/dev/null 2>&1 && [[ -t 0 ]]; then
        sudo "$@"
    else
        return 1
    fi
}

# 1. Locate existing checkout or clone pinned release tag
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [[ -n "${SCRIPT_PATH}" && -f "$(dirname "${SCRIPT_PATH}")/pyproject.toml" && -d "$(dirname "${SCRIPT_PATH}")/agentdroid" ]]; then
    REPO_ROOT="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
else
    REPO_ROOT="${INSTALL_DIR}/repo"
    mkdir -p "${INSTALL_DIR}"
    if [[ -d "${REPO_ROOT}/.git" ]]; then
        info "Updating existing AgentDroid checkout at ${REPO_ROOT} (ref: ${REPO_REF})..."
        if ! git -C "${REPO_ROOT}" fetch --depth 1 origin "${REPO_REF}" || \
           ! git -C "${REPO_ROOT}" checkout FETCH_HEAD; then
            err "Failed to check out ref '${REPO_REF}' in ${REPO_ROOT}. Pass --ref <tag|branch> or inspect git status."
            exit 1
        fi
    else
        info "Cloning AgentDroid (${REPO_REF}) into ${REPO_ROOT}..."
        if ! git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" "${REPO_ROOT}"; then
            err "Failed to clone ${REPO_URL} at ref '${REPO_REF}'. Override with --ref <tag|branch>."
            exit 1
        fi
    fi
fi

# 2. Check host tools (opt-in system package installation)
info "Checking host dependencies (adb, scrcpy, docker, python3)..."
MISSING_PKGS=()
command -v adb >/dev/null 2>&1 || MISSING_PKGS+=("adb")
command -v scrcpy >/dev/null 2>&1 || MISSING_PKGS+=("scrcpy")
command -v python3 >/dev/null 2>&1 || MISSING_PKGS+=("python3")
command -v curl >/dev/null 2>&1 || MISSING_PKGS+=("curl")

if (( ${#MISSING_PKGS[@]} > 0 )); then
    warn "Missing host tools: ${MISSING_PKGS[*]}"
    if confirm_opt_in "${OPT_SYSTEM_DEPS}" "Install missing host packages (${MISSING_PKGS[*]}) via system package manager?"; then
        if command -v apt-get >/dev/null 2>&1; then
            if ! (run_privileged apt-get update -qq && run_privileged apt-get install -y -qq "${MISSING_PKGS[@]}"); then
                warn "apt-get install failed for: ${MISSING_PKGS[*]}. Install them manually."
            fi
        elif command -v dnf >/dev/null 2>&1; then
            if ! run_privileged dnf install -y "${MISSING_PKGS[@]}"; then
                warn "dnf install failed for: ${MISSING_PKGS[*]}. Install them manually."
            fi
        elif command -v pacman >/dev/null 2>&1; then
            if ! run_privileged pacman -Sy --noconfirm "${MISSING_PKGS[@]}"; then
                warn "pacman install failed for: ${MISSING_PKGS[*]}. Install them manually."
            fi
        elif command -v brew >/dev/null 2>&1; then
            if ! brew install "${MISSING_PKGS[@]}"; then
                warn "brew install failed for: ${MISSING_PKGS[*]}. Install them manually."
            fi
        else
            warn "No supported package manager detected; please install: ${MISSING_PKGS[*]}"
        fi
    else
        info "Skipped system package install (re-run with --with-system-deps or --yes to install automatically)."
    fi
fi

# 3. Linux kernel modules for Redroid (opt-in)
if [[ "$(uname -s)" == "Linux" ]]; then
    NEED_BINDER=0
    NEED_UINPUT=0
    grep -q binder /proc/filesystems 2>/dev/null || NEED_BINDER=1
    grep -qw uinput /proc/misc 2>/dev/null || NEED_UINPUT=1

    if [[ "${NEED_BINDER}" == "1" || "${NEED_UINPUT}" == "1" || "${OPT_KERNEL_MODULES}" == "1" ]]; then
        if confirm_opt_in "${OPT_KERNEL_MODULES}" "Load Linux kernel modules (binder_linux, ashmem_linux, uinput) and persist in /etc/modules-load.d/agentdroid.conf?"; then
            if [[ "${NEED_BINDER}" == "1" ]]; then
                info "Loading Linux kernel modules for Redroid (binder_linux, ashmem_linux)..."
                if command -v apt-get >/dev/null 2>&1; then
                    run_privileged apt-get install -y -qq "linux-modules-extra-$(uname -r)" || \
                        warn "Could not install linux-modules-extra-$(uname -r)."
                fi
                run_privileged modprobe binder_linux devices="binder,hwbinder,vndbinder" || \
                    warn "modprobe binder_linux failed; verify your kernel includes Android binder support."
                run_privileged modprobe ashmem_linux || \
                    warn "modprobe ashmem_linux skipped (optional on kernels with memfd)."
            fi
            if [[ "${NEED_UINPUT}" == "1" ]]; then
                info "Loading Linux uinput kernel module for Redroid virtual touchscreen..."
                run_privileged modprobe uinput || \
                    warn "modprobe uinput failed; virtual touchscreen acceleration may be unavailable."
            fi
            if [[ -d /etc/modules-load.d ]]; then
                modules_conf="binder_linux\nashmem_linux\n"
                if grep -qw uinput /proc/misc 2>/dev/null || modinfo uinput >/dev/null 2>&1; then
                    modules_conf+="uinput\n"
                fi
                if ! printf "%b" "${modules_conf}" | run_privileged tee /etc/modules-load.d/agentdroid.conf >/dev/null; then
                    warn "Could not write /etc/modules-load.d/agentdroid.conf (insufficient privileges)."
                fi
            fi
        else
            info "Skipped kernel module changes (re-run with --with-kernel-modules or --yes to configure)."
        fi
    fi
fi

# 4. Build native Rust accelerator (`agentdroid-fast`) if Cargo is present
if command -v cargo >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/rust/Cargo.toml" ]]; then
    info "Building native Rust engine (agentdroid-fast)..."
    if ! cargo build --release --manifest-path "${REPO_ROOT}/rust/Cargo.toml"; then
        warn "Rust build failed; pure-Python engine remains active."
    fi
fi

# 5. Install user-local CLI symlink in ~/.local/bin
mkdir -p "${HOME}/.local/bin"
chmod +x "${REPO_ROOT}/bin/agentdroid" "${REPO_ROOT}/scripts/provision-device.sh"
ln -sf "${REPO_ROOT}/bin/agentdroid" "${HOME}/.local/bin/agentdroid"
if [[ -x "${REPO_ROOT}/rust/target/release/agentdroid-fast" ]]; then
    ln -sf "${REPO_ROOT}/rust/target/release/agentdroid-fast" "${HOME}/.local/bin/agentdroid-fast"
fi
export PATH="${HOME}/.local/bin:${PATH}"

# Opt-in: /usr/local/bin symlink
if [[ -w /usr/local/bin ]] && confirm_opt_in "${OPT_SYSTEM_BIN}" "Also symlink agentdroid into /usr/local/bin/agentdroid?"; then
    if ! ln -sf "${REPO_ROOT}/bin/agentdroid" /usr/local/bin/agentdroid; then
        warn "Could not symlink /usr/local/bin/agentdroid."
    fi
fi

# Opt-in: shell rc PATH edit
RC_CANDIDATES=()
for rc_file in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.profile"; do
    if [[ -f "${rc_file}" ]] && ! grep -q '.local/bin' "${rc_file}" 2>/dev/null; then
        RC_CANDIDATES+=("${rc_file}")
    fi
done
if (( ${#RC_CANDIDATES[@]} > 0 )); then
    if confirm_opt_in "${OPT_SHELL_RC}" "Add ~/.local/bin to PATH in: ${RC_CANDIDATES[*]}?"; then
        for rc_file in "${RC_CANDIDATES[@]}"; do
            printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "${rc_file}"
        done
    else
        info "Skipped shell rc edits. Ensure ~/.local/bin is in your PATH (or pass --with-shell-rc)."
    fi
fi

# 6. Initialize .env from template if missing
if [[ ! -f "${REPO_ROOT}/.env" && -f "${REPO_ROOT}/.env.example" ]]; then
    cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
fi

# 7. Run `agentdroid setup` (global AI coding assistant config injection is opt-in)
SETUP_ARGS=("setup")
if [[ "${SKIP_STACK}" == "1" ]]; then
    SETUP_ARGS+=("--no-start")
fi

CONFIGURED_AGENTS=0
if confirm_opt_in "${OPT_AGENT_CONFIGS}" "Install AgentDroid skills, rules, and MCP configs into Claude, Codex, Cursor, Gemini, and Windsurf?"; then
    CONFIGURED_AGENTS=1
else
    SETUP_ARGS+=("--no-agents")
    info "Skipped global AI assistant config edits (run 'agentdroid setup --agents-only' or 'agentdroid mcp --install' anytime to opt in)."
fi

"${REPO_ROOT}/bin/agentdroid" "${SETUP_ARGS[@]}"

echo ""
ok "AgentDroid is installed!"
printf "   • Local CLI:       \033[1m%s/.local/bin/agentdroid\033[0m\n" "${HOME}"
if [[ "${CONFIGURED_AGENTS}" == "1" ]]; then
    printf "   • AI Agent Config: Mounted into Claude Code, Codex, Cursor, Antigravity & Windsurf\n"
else
    printf "   • AI Agent Config: Not modified (opt in with: \033[1magentdroid mcp --install\033[0m / \033[1magentdroid setup --agents-only\033[0m)\n"
fi
printf "   • Next Step:       Run \033[1magentdroid doctor\033[0m or drive Android via MCP / CLI.\n\n"
