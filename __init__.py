"""Entry point for the ``claim-receipts`` plugin.

Registered surface (must match plugin.yaml `capabilities`):

    hooks     pre_tool_call, post_tool_call, on_session_end
    command   /claim-receipts

Design rule for this file: every handler is a thin, exception-swallowing wrapper. A plugin that can
break a user's tool call is worse than the problem it solves, so nothing here is allowed to raise.
"""
from __future__ import annotations

import logging
from typing import Any

from .receipts import ledger

logger = logging.getLogger(__name__)


def _safe(fn, label: str):
    def wrapped(*args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:                      # never propagate into the host
            logger.debug("receipts: %s failed: %s", label, exc)
    return wrapped


def _handle_slash(raw_args: str = "", session_id: str = "", platform: str = "", **_: Any) -> str:
    """`/claim-receipts` — this session's evidence so far.

    Hermes fills `session_id` and `platform` for every surface (PR #153708 review). On a messaging
    gateway the command shows only the calling chat's own ledger; the newest-ledger fallback and an
    explicit session argument are for the local CLI only.
    """
    try:
        from .receipts import claims
        return claims.render_for_command(raw_args, session_id, platform)
    except Exception as exc:
        return f"receipts: could not read the ledger ({exc})"


def _session_end(session_id: str = "", task_id: str = "", **kwargs: Any) -> None:
    """Boundary marker first, then the artifact. Two steps, both fail-open and independent: a failure
    writing the receipt must not cost the ledger its end marker, and vice versa."""
    try:
        ledger.on_session_end(session_id=session_id, task_id=task_id, **kwargs)
    except Exception:
        pass
    try:
        from .receipts import receipt
        receipt.write(session_id, task_id)
    except Exception:
        pass


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _safe(ledger.pre_tool_call, "pre_tool_call"))
    ctx.register_hook("post_tool_call", _safe(ledger.post_tool_call, "post_tool_call"))
    ctx.register_hook("on_session_end", _safe(_session_end, "on_session_end"))
    ctx.register_command(
        "claim-receipts",
        handler=_handle_slash,
        description="Show what this session has actually proven: evidence ledger and claims.",
    )
