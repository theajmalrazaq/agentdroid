"""One-command full environment setup & automatic AI agent skill/rule installer for AgentDroid."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_FILE = REPO_ROOT / "skills" / "agentdroid" / "SKILL.md"
AGENTS_FILE = REPO_ROOT / "AGENTS.md"
MARKER_START = "<!-- AGENTDROID_RULES_START -->"
MARKER_END = "<!-- AGENTDROID_RULES_END -->"


def _upsert_marked_block(target_file: Path, content: str) -> None:
    """Idempotently insert or update the AgentDroid instructions block in a markdown rules file."""
    block = f"{MARKER_START}\n{content.strip()}\n{MARKER_END}\n"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if target_file.is_file():
        existing = target_file.read_text(encoding="utf-8", errors="replace")
        if MARKER_START in existing and MARKER_END in existing:
            before = existing.split(MARKER_START, 1)[0]
            after = existing.split(MARKER_END, 1)[1]
            updated = f"{before.rstrip()}\n\n{block}{after.lstrip()}"
            target_file.write_text(updated, encoding="utf-8")
            return
        sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
        target_file.write_text(f"{existing}{sep}{block}", encoding="utf-8")
    else:
        target_file.write_text(block, encoding="utf-8")


def install_agent_skills_and_rules(home_dir: Path | None = None) -> dict[str, list[str]]:
    """Install AgentDroid skill and rules into all major AI coding agents on the machine."""
    home = home_dir or Path.home()
    skill_text = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""
    rules_text = AGENTS_FILE.read_text(encoding="utf-8") if AGENTS_FILE.is_file() else ""

    installed_skills: list[str] = []
    installed_rules: list[str] = []

    # 1. Standard Skill Directories (Antigravity/Jetski, Claude Code, Codex, Universal ~/.agents)
    skill_targets = [
        home / ".gemini" / "jetski" / "skills" / "agentdroid" / "SKILL.md",
        home / ".gemini" / "skills" / "agentdroid" / "SKILL.md",
        home / ".claude" / "skills" / "agentdroid" / "SKILL.md",
        home / ".codex" / "skills" / "agentdroid" / "SKILL.md",
        home / ".agents" / "skills" / "agentdroid" / "SKILL.md",
    ]
    if skill_text:
        for dest in skill_targets:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(skill_text, encoding="utf-8")
                installed_skills.append(str(dest))
            except OSError:
                continue

    # 2. Dedicated Agent Rule Files (Claude Code, Cursor, Codex, Gemini/Antigravity, Windsurf)
    if rules_text:
        # Claude Code modular rules directory (~/.claude/rules/agentdroid.md)
        claude_rule = home / ".claude" / "rules" / "agentdroid.md"
        try:
            claude_rule.parent.mkdir(parents=True, exist_ok=True)
            claude_rule.write_text(rules_text, encoding="utf-8")
            installed_rules.append(str(claude_rule))
        except OSError:
            pass

        # Cursor global/user rules (~/.cursor/rules/agentdroid.mdc)
        cursor_rule = home / ".cursor" / "rules" / "agentdroid.mdc"
        try:
            cursor_rule.parent.mkdir(parents=True, exist_ok=True)
            mdc_content = (
                "---\n"
                "description: Use agentdroid silent Android device for any Android task, app installation, or testing\n"
                "globs: *\n"
                "alwaysApply: true\n"
                "---\n\n"
                f"{rules_text}"
            )
            cursor_rule.write_text(mdc_content, encoding="utf-8")
            installed_rules.append(str(cursor_rule))
        except OSError:
            pass

        # Append marked block to global agent instruction files if parent exists or create ~/.codex & ~/.gemini
        for shared_rule_file in (
            home / ".gemini" / "GEMINI.md",
            home / ".codex" / "AGENTS.md",
            home / ".codeium" / "windsurf" / "memories" / "global_rules.md",
        ):
            try:
                _upsert_marked_block(shared_rule_file, rules_text)
                installed_rules.append(str(shared_rule_file))
            except OSError:
                continue

    return {
        "skills_installed": installed_skills,
        "rules_installed": installed_rules,
    }


def ensure_cli_on_path(home_dir: Path | None = None) -> str:
    """Symlink `agentdroid` into ~/.local/bin so any AI agent can invoke it globally."""
    home = home_dir or Path.home()
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    src_bin = REPO_ROOT / "bin" / "agentdroid"
    src_bin.chmod(0o755)

    target = local_bin / "agentdroid"
    try:
        if target.is_symlink() or target.exists():
            target.unlink()
        target.symlink_to(src_bin)
    except OSError:
        shutil.copy2(src_bin, target)
        target.chmod(0o755)

    return str(target)


def ensure_env_file(api_key: str | None = None) -> Path:
    """Create .env from .env.example and populate any detected or provided LLM API key."""
    env_file = REPO_ROOT / ".env"
    example_file = REPO_ROOT / ".env.example"
    if not env_file.is_file() and example_file.is_file():
        shutil.copy2(example_file, env_file)
    elif not env_file.is_file():
        env_file.write_text("GEMINI_API_KEY=\nARTEMIS_DEFAULT_PROFILE=flash\n", encoding="utf-8")

    text = env_file.read_text(encoding="utf-8")
    keys_to_sync = (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPEN_ROUTER_API_KEY",
        "XAI_API_KEY",
    )

    if api_key:
        if api_key.startswith("sk-ant-"):
            target_var = "ANTHROPIC_API_KEY"
        elif api_key.startswith("sk-or-"):
            target_var = "OPEN_ROUTER_API_KEY"
        elif api_key.startswith("sk-"):
            target_var = "OPENAI_API_KEY"
        else:
            target_var = "GEMINI_API_KEY"
        os.environ[target_var] = api_key

    lines = text.splitlines()
    new_lines: list[str] = []
    updated_vars: set[str] = set()
    for line in lines:
        matched = False
        for k in keys_to_sync:
            val = os.environ.get(k, "").strip()
            if val and line.startswith(f"{k}="):
                new_lines.append(f"{k}={val}")
                updated_vars.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    for k in keys_to_sync:
        val = os.environ.get(k, "").strip()
        if val and k not in updated_vars and f"{k}=" not in text:
            new_lines.append(f"{k}={val}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return env_file


def run_one_command_setup(
    *,
    api_key: str | None = None,
    start_stack: bool = True,
    build_images: bool = False,
    watch: bool = False,
) -> dict[str, Any]:
    """Execute complete one-command setup: CLI PATH link, .env config, AI agent skills/rules, and stack boot."""
    cli_path = ensure_cli_on_path()
    env_path = ensure_env_file(api_key=api_key)
    agents_mounted = install_agent_skills_and_rules()

    stack_result: dict[str, Any] = {"started": False, "skipped": not start_stack}
    if start_stack:
        docker_bin = shutil.which("docker")
        if docker_bin:
            cmd = [str(REPO_ROOT / "bin" / "agentdroid"), "up", "--json"]
            if build_images:
                cmd.append("--build")
            if watch:
                cmd.append("--watch")
            else:
                cmd.append("--headless")
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
            stack_result = {
                "started": proc.returncode == 0,
                "returncode": proc.returncode,
                "output": (proc.stdout or proc.stderr or "").strip(),
            }
        else:
            stack_result = {
                "started": False,
                "error": "Docker is not installed or not on PATH; skipped container startup.",
            }

    return {
        "ok": True,
        "cli_binary": cli_path,
        "env_file": str(env_path),
        "ai_agents_configured": agents_mounted,
        "stack": stack_result,
    }
