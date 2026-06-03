"""Gate Enforcer — pre_tool_call hook that blocks tool execution if Gate hasn't been passed.

Architecture: Agent can't decide to skip Gate. The check runs outside the reasoning loop.
Every tool call is intercepted at the framework level. If Gate hasn't run for this session
recently enough, the tool is blocked with a clear message.

This is the neurosymbolic approach: LLM handles reasoning, hook handles constraint enforcement.
Neither replaces the other.

Inspiration: AWS Strands Agents before_tool_call hook + OpenAI Model Spec chain-of-command.
"""

import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

CHECKPOINT_FILE = Path.home() / ".hermes" / "logs" / "gate_checkpoint.json"
GRACE_PERIOD = 300  # seconds — Gate valid for 5 minutes per turn


def _gate_passed_recently(session_id: str) -> bool:
    """Check if Gate was run recently for this session.

    Returns True when:
    - Checkpoint exists, matches session, and is within grace period
    - HERMES_SESSION_ID is missing (can't enforce — log warning and pass)
    - Checkpoint file is corrupted (log warning and pass)

    Only returns False when Gate is objectively missed — checkpoint
    missing entirely, wrong session, or expired.
    """
    if not session_id:
        # Can't match — let it through but log
        return True

    if not CHECKPOINT_FILE.exists():
        return False

    try:
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return True  # corrupted — don't block everything

    last_run = data.get("timestamp", 0)
    last_session = data.get("session_id", "")

    if not last_session:
        return True  # old format checkpoint — don't block

    if last_session != session_id:
        return False

    age = time.time() - last_run
    return age < GRACE_PERIOD


def _on_pre_tool_call(
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    task_id: str = "",
    tool_call_id: str = "",
    turn_id: str = "",
    api_request_id: str = "",
    **kwargs,
) -> Optional[Dict[str, str]]:
    """Pre-tool-call hook: block if Gate hasn't been passed."""

    # Exempt Gate itself and safety/clarify tools from the check
    EXEMPT_TOOLS = {
        "terminal",  # gate.py runs via terminal
        "clarify",
        "memory",
        "send_message",
    }
    if tool_name in EXEMPT_TOOLS:
        return None

    # Exempt tools that start with "mcp__" (MCP infrastructure)
    if tool_name.startswith("mcp__"):
        return None

    if not _gate_passed_recently(session_id):
        return {
            "action": "block",
            "message": (
                "Gate 未通过 — 先跑 `python3 ~/.hermes/scripts/gate.py \"任务描述\"` 再动手。\n"
                "这是框架级强制约束，不是提示词建议。"
            ),
        }

    return None


def register(ctx):
    """Plugin entry point — called by Hermes plugin loader."""
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
