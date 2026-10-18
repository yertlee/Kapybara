"""Feishu WebSocket event handling and agent orchestration.

The SDK owns the WebSocket lifecycle and in-process inbound deduplication.
This adapter additionally enforces p2p/text/allowlist policy before invoking
the agent, then sends ``MemoryRecord.output`` directly through the SDK because
the Feishu messager skill assigns delivery to this adapter.

Import the SDK before starting the application's asyncio loop: its WebSocket
client binds a module-level event loop at import time, then runs that loop from
the SDK's connection worker thread.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from lark_channel import FeishuChannel, OutboundConfig, RetryConfig

from . import feishu_message_to_event

if TYPE_CHECKING:
    from k.agent.memory.folder import FolderMemoryStore
    from k.config import Config
    from pydantic_ai.models import Model

logger = logging.getLogger(__name__)

_ERROR_REPLY = (
    "Sorry, I couldn't process that message right now. Please try again later."
)
_EMPTY_OUTPUT_REPLY = (
    "Sorry, I couldn't prepare a reply this time. Please try again."
)
_SEND_RETRY_ATTEMPTS = 5
_SEND_RETRY_BASE_DELAY_MS = 500


def _configure_starter_logging() -> None:
    """Keep operational Feishu logs visible while CLI logs also reach Logfire."""

    logger.setLevel(logging.INFO)
    if any(handler.get_name() == "feishu-console" for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.set_name("feishu-console")
    logger.addHandler(handler)


def _create_channel(app_id: str, app_secret: str) -> Any:
    """Build the SDK channel with bounded, SDK-managed idempotent retries."""

    return FeishuChannel(
        app_id=app_id,
        app_secret=app_secret,
        transport="ws",
        outbound=OutboundConfig(
            retry=RetryConfig(
                max_attempts=_SEND_RETRY_ATTEMPTS,
                base_delay_ms=_SEND_RETRY_BASE_DELAY_MS,
            )
        ),
    )


async def _run_agent(**kwargs: Any) -> Any:
    """Load and invoke the core runtime only when an eligible message arrives."""

    from k.agent.core.agent import agent_run

    return await agent_run(**kwargs)


async def _send_text(channel: Any, message: Any, text: str) -> bool:
    """Send text as a reply and report SDK failures, including SendResult failures."""

    try:
        result = await channel.send(
            message.chat_id,
            {"text": text},
            {"reply_to": message.message_id},
        )
    except Exception:
        logger.exception("Feishu reply send raised an exception")
        return False
    if not getattr(result, "success", False):
        logger.error("Feishu reply send failed: %s", getattr(result, "error", result))
        return False
    return True


def _persist_record(memory_store: Any, record: Any) -> None:
    """Persist a completed agent turn once; memory failure must not block reply delivery."""

    try:
        memory_store.append(record)
    except Exception as exc:
        # Do not retry appends: FolderMemoryStore rejects duplicate record IDs,
        # and a retry cannot distinguish a partial write from a failed write.
        logger.error(
            "Feishu interaction memory persistence failed (%s); continuing reply delivery",
            type(exc).__name__,
        )


def _log_raw_message_event(payload: Any) -> None:
    """Log receipt of the subscribed wire event without exposing its payload."""

    header = payload.get("header") if isinstance(payload, dict) else None
    event_type = (
        header.get("event_type")
        if isinstance(header, dict)
        else getattr(header, "event_type", None)
    )
    # The raw subscription is only installed for this event type. Keep the
    # value constrained to a string so malformed payloads cannot inject logs.
    if event_type != "im.message.receive_v1":
        event_type = "im.message.receive_v1"
    logger.info("Feishu inbound event received: %s", event_type)


def _log_safety_rejection(event: Any) -> None:
    """Log the SDK's safety rejection reason without message or sender data."""

    reason = getattr(event, "reason", "unknown")
    if reason not in {
        "bot_loop",
        "duplicate",
        "lock_contention",
        "policy",
        "self_sent",
        "stale",
    }:
        reason = "unknown"
    logger.warning("Feishu SDK rejected inbound message: reason=%s", reason)


def make_message_handler(
    *,
    channel: Any,
    model: Model,
    config: Config,
    memory_store: FolderMemoryStore,
    allowed_open_ids: set[str],
) -> Callable[[Any], Any]:
    """Build the SDK's async message callback using shared runtime objects."""

    async def on_message(message: Any) -> None:
        """Process one SDK-deduplicated message according to starter policy."""

        if getattr(message, "sender_is_bot", False):
            return
        if getattr(message, "chat_type", None) != "p2p":
            return

        sender_id = getattr(message, "sender_id", "")
        if not allowed_open_ids:
            logger.warning(
                "Feishu discovery mode: sender open_id=%s; agent access is disabled",
                sender_id,
            )
            return
        if sender_id not in allowed_open_ids:
            logger.warning(
                "Ignoring Feishu DM from non-allowlisted open_id=%s", sender_id
            )
            return

        event = feishu_message_to_event(message)
        if event is None:
            logger.info(
                "Ignoring non-text or empty Feishu DM message_id=%s",
                getattr(message, "message_id", ""),
            )
            return

        try:
            record = await _run_agent(
                model=model,
                config=config,
                memory_store=memory_store,
                instruct=event,
                parent_memories=[],
            )
        except Exception:
            logger.exception(
                "agent_run failed for Feishu message_id=%s", message.message_id
            )
            await _send_text(channel, message, _ERROR_REPLY)
            return

        answer = record.output.strip()
        if not answer:
            logger.warning(
                "Agent returned empty output for an eligible Feishu DM; "
                "sending a short fallback reply"
            )
            answer = _EMPTY_OUTPUT_REPLY
            record.output = answer
            compacted = getattr(record, "compacted", None)
            if isinstance(compacted, list):
                for index, step in enumerate(compacted):
                    if isinstance(step, str) and step.startswith("<output>"):
                        compacted[index] = f"<output>{answer}</output>"
                        break
        _persist_record(memory_store, record)
        await _send_text(channel, message, answer)

    return on_message


async def run_forever(
    *,
    app_id: str,
    app_secret: str,
    allowed_open_ids: set[str],
    model: Model | str | None = None,
) -> None:
    """Connect the official SDK over WebSocket and serve private messages."""

    from k.agent.core.cli_runtime import configure_cli_logfire, resolve_cli_model
    from k.agent.memory.folder import FolderMemoryStore
    from k.agent.memory.paths import memory_root_from_config_base
    from k.config import Config

    config = Config()
    configure_cli_logfire(config.config_base)
    _configure_starter_logging()
    resolved_model = resolve_cli_model(config, model)
    memory_store = FolderMemoryStore(
        root=memory_root_from_config_base(config.config_base)
    )
    channel = _create_channel(app_id, app_secret)
    channel.on(
        "message",
        make_message_handler(
            channel=channel,
            model=resolved_model,
            config=config,
            memory_store=memory_store,
            allowed_open_ids=allowed_open_ids,
        ),
    )
    channel.on("error", lambda error: logger.error("Feishu SDK error: %s", error))
    # Observe the subscribed wire event before SDK normalization and safety
    # filters. The handler receives the payload but logs only its event type.
    channel.on_raw_event("im.message.receive_v1", _log_raw_message_event)
    channel.on("reject", _log_safety_rejection)
    if allowed_open_ids:
        logger.info(
            "Starting Feishu WebSocket starter (allowlisted users: %d)",
            len(allowed_open_ids),
        )
    else:
        logger.warning(
            "Starting Feishu WebSocket starter in discovery mode; agent access is disabled"
        )
    await channel.connect()


__all__ = ["make_message_handler", "run_forever"]
