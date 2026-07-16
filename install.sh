#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILLS_DIR="$SCRIPT_DIR/skills"
INSTALL_CLAUDE=0
INSTALL_CODEX=0
INSTALL_QWEN=0
REMOVE_LEGACY=0
SKIP_EXISTING=0

usage() {
  cat <<'USAGE'
Usage: ./install.sh [--all] [--claude] [--codex] [--qwen] [--skip-existing] [--remove-legacy]

With no agent option, installs for all three agents.

Targets:
  Claude Code  ~/.claude/skills
  Codex        ~/.agents/skills
  Qwen Code    ~/.qwen/skills

Options:
  --all      Install for Claude Code, Codex, and Qwen Code
  --claude   Install for Claude Code
  --codex    Install for Codex
  --qwen     Install for Qwen Code
  --skip-existing
             Preserve existing uu-* skill folders instead of replacing them
  --remove-legacy
             Remove the earlier project-plan, project-review, project-revise,
             project-summarize, and project-propose skill folders
  --help     Show this message
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --all)
      INSTALL_CLAUDE=1
      INSTALL_CODEX=1
      INSTALL_QWEN=1
      ;;
    --claude)
      INSTALL_CLAUDE=1
      ;;
    --codex)
      INSTALL_CODEX=1
      ;;
    --qwen)
      INSTALL_QWEN=1
      ;;
    --skip-existing)
      SKIP_EXISTING=1
      ;;
    --remove-legacy)
      REMOVE_LEGACY=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$INSTALL_CLAUDE" -eq 0 ] && [ "$INSTALL_CODEX" -eq 0 ] && [ "$INSTALL_QWEN" -eq 0 ]; then
  INSTALL_CLAUDE=1
  INSTALL_CODEX=1
  INSTALL_QWEN=1
fi

install_to() {
  agent_name=$1
  destination=$2
  mkdir -p "$destination"

  for skill_dir in "$SKILLS_DIR"/uu-*; do
    skill_name=$(basename "$skill_dir")
    target="$destination/$skill_name"

    if [ -e "$target" ] || [ -L "$target" ]; then
      if [ "$SKIP_EXISTING" -eq 1 ]; then
        echo "$agent_name: skipped $skill_name, already exists"
        continue
      fi
      rm -rf "$target"
    fi

    cp -R "$skill_dir" "$target"
    echo "$agent_name: updated $skill_name"
  done

  if [ "$REMOVE_LEGACY" -eq 1 ]; then
    for legacy_name in project-plan project-propose project-review project-revise project-summarize; do
      legacy_target="$destination/$legacy_name"
      if [ -e "$legacy_target" ] || [ -L "$legacy_target" ]; then
        rm -rf "$legacy_target"
        echo "$agent_name: removed legacy $legacy_name"
      fi
    done
  fi
}

install_if_available() {
  agent_name=$1
  agent_dir=$2

  if [ ! -d "$agent_dir" ]; then
    echo "$agent_name: skipped because $agent_dir does not exist"
    return
  fi

  install_to "$agent_name" "$agent_dir/skills"
}

install_codex_if_available() {
  if [ -d "$HOME/.agents" ]; then
    install_to "Codex (.agents)" "$HOME/.agents/skills"
  fi

  if [ -d "$HOME/.codex" ]; then
    install_to "Codex (.codex)" "$HOME/.codex/skills"
  fi

  if [ ! -d "$HOME/.agents" ] && [ ! -d "$HOME/.codex" ]; then
    echo "Codex: skipped because neither $HOME/.agents nor $HOME/.codex exists"
  fi
}

if [ "$INSTALL_CLAUDE" -eq 1 ]; then
  install_if_available "Claude Code" "$HOME/.claude"
fi
if [ "$INSTALL_CODEX" -eq 1 ]; then
  install_codex_if_available
fi
if [ "$INSTALL_QWEN" -eq 1 ]; then
  install_if_available "Qwen Code" "$HOME/.qwen"
fi

echo "Installation complete. Restart an agent session if the new skills do not appear."
