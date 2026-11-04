"""Entry point for the ``receipts`` plugin.

Registered surface (must match plugin.yaml `capabilities`):

    hooks     pre_tool_call, post_tool_call, on_session_end
    command   /receipts

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


def _handle_slash(raw_args: str = "") -> str:
    """`/receipts` — what this session has proven so far."""
    try:
        from .receipts import claims
        return claims.render_session_summary(raw_args)
    except Exception as exc:
        return f"receipts: could not read the ledger ({exc})"


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _safe(ledger.pre_tool_call, "pre_tool_call"))
    ctx.register_hook("post_tool_call", _safe(ledger.post_tool_call, "post_tool_call"))
    ctx.register_hook("on_session_end", _safe(ledger.on_session_end, "on_session_end"))
    ctx.register_command(
        "receipts",
        handler=_handle_slash,
        description="Show what this session has actually proven: evidence ledger and claims.",
    )
