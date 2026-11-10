#!/usr/bin/env python3
"""PreToolUse guard for Claude Code. Refuses Bash commands that would change or
remove published releases or shared history. Exit 2 blocks the command and
shows the reason to the agent; anything else lets it through.

This binds the agent only. The hard locks are immutable releases and the back
office, which accepts uploads only from the kit's own publish workflow."""

import json
import re
import sys

# A git push, up to the end of that command (not past ; & | or a newline).
PUSH = r"\bgit\s+push\b[^\n;&|]*"

RULES = (
    (re.compile(r"\bgh\s+release\s+(edit|upload|delete|delete-asset)\b"),
     "published releases change only through the kit's workflows; a person edits or deletes them"),
    (re.compile(PUSH + r"\s(--force(-with-lease)?(=\S*)?|-f)(?=\s|$)"),
     "force-pushing rewrites shared history"),
    (re.compile(PUSH + r"\s--(delete|mirror|prune)\b"),
     "this push deletes remote branches or tags; a person does that"),
    (re.compile(PUSH + r"\s:\S+"),
     "pushing ':ref' deletes a remote branch or tag"),
    (re.compile(PUSH + r"\s\+\S+"),
     "a '+' refspec force-pushes"),
    (re.compile(r"\bgit\s+tag\b[^\n;&|]*\s(-[a-zA-Z]*[df][a-zA-Z]*|--delete|--force)(?=\s|$)"),
     "tags are never deleted or moved; release a new version instead"),
)


def reason(command):
    for pattern, why in RULES:
        if pattern.search(command):
            return why
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    why = reason(command)
    if why:
        print(f"Blocked by the Allumee release kit: {why}. Ask the person to do it if it is really needed.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
