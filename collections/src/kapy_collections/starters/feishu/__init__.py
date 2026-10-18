"""Feishu private-message starter backed by the official Channel SDK.

The adapter accepts allowlisted plain-text direct messages, converts each to a
Kapybara :class:`Event`, runs ``agent_run``, and sends non-empty output back to
the source chat. SDK in-memory deduplication applies to one process lifetime.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from k.agent.core.entities import Event

logger = logging.getLogger(__name__)


def parse_allowed_open_ids(value: str | Iterable[str]) -> set[str]:
    """Parse a comma-separated allowlist of Feishu user ``open_id`` values.

    Empty allowlists are rejected so the integration cannot accidentally run
    with access control disabled.
    """

    parts = value.split(",") if isinstance(value, str) else value
    open_ids = {item.strip() for item in parts if item.strip()}
    if not open_ids:
        raise ValueError("LARK_ALLOWED_OPEN_IDS must contain at least one open_id")
    return open_ids


def feishu_message_to_event(message: Any) -> Event | None:
    """Convert an eligible inbound Feishu message to a Kapybara event.

    Only p2p text is represented. Groups and non-text messages return ``None``;
    the caller applies the sender allowlist before invoking the agent.
    """

    if getattr(message, "chat_type", None) != "p2p":
        return None
    if getattr(message, "raw_content_type", None) != "text":
        return None

    body = getattr(message, "content_text", "")
    if not isinstance(body, str) or not body.strip():
        content = getattr(message, "content", None)
        body = getattr(content, "text", "")
    if not isinstance(body, str) or not body.strip():
        return None

    chat_id = getattr(message, "chat_id", "")
    sender_id = getattr(message, "sender_id", "")
    if not isinstance(chat_id, str) or not chat_id:
        raise ValueError("Feishu message is missing chat_id")
    if not isinstance(sender_id, str) or not sender_id:
        raise ValueError("Feishu message is missing sender open_id")

    return Event(
        in_channel=f"feishu/chat/{chat_id}",
        contacts=[f"feishu/{sender_id}"],
        content=body,
    )


__all__ = ["feishu_message_to_event", "parse_allowed_open_ids"]
