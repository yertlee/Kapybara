from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from lark_channel import OutboundConfig
from lark_channel.ws import client as sdk_ws_client

from kapy_collections.starters.feishu import (
    feishu_message_to_event,
    parse_allowed_open_ids,
)
from kapy_collections.starters.feishu import runner as feishu_runner


def _message(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "chat_type": "p2p",
        "raw_content_type": "text",
        "content_text": "hello",
        "content": SimpleNamespace(text="hello"),
        "chat_id": "oc_chat",
        "sender_id": "ou_user",
        "message_id": "om_message",
        "sender_is_bot": False,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _memory_store() -> SimpleNamespace:
    return SimpleNamespace(append=lambda _record: None)


def test_feishu_message_maps_to_event() -> None:
    event = feishu_message_to_event(_message())

    assert event is not None
    assert event.in_channel == "feishu/chat/oc_chat"
    assert event.contacts == ["feishu/ou_user"]
    assert event.content == "hello"


@pytest.mark.parametrize(
    "message",
    [
        _message(chat_type="group"),
        _message(raw_content_type="image"),
        _message(content_text=" ", content=SimpleNamespace(text="")),
    ],
)
def test_feishu_message_ignores_unsupported_content(message: SimpleNamespace) -> None:
    assert feishu_message_to_event(message) is None


def test_parse_allowlist_requires_user_ids() -> None:
    assert parse_allowed_open_ids(" ou_one,ou_two ,, ") == {"ou_one", "ou_two"}
    with pytest.raises(ValueError, match="at least one"):
        parse_allowed_open_ids(" , ")


@pytest.mark.anyio
async def test_sdk_websocket_loop_is_separate_from_anyio_loop() -> None:
    """The SDK captures its WebSocket loop when runner imports, before anyio."""

    assert not sdk_ws_client.loop.is_running()
    assert sdk_ws_client.loop is not asyncio.get_running_loop()
    assert feishu_runner.FeishuChannel is not None


def test_channel_uses_bounded_sdk_retry_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_channel(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(feishu_runner, "FeishuChannel", fake_channel)

    feishu_runner._create_channel("test-app", "test-secret")

    outbound = cast(OutboundConfig, captured["outbound"])
    retry = outbound.retry
    assert captured["transport"] == "ws"
    assert retry.max_attempts == 5
    assert retry.base_delay_ms == 500


@pytest.mark.anyio
async def test_handler_skips_agent_for_unallowlisted_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kapy_collections.starters.feishu import runner

    called = False

    async def fake_agent_run(**_: object) -> object:
        nonlocal called
        called = True
        return SimpleNamespace(output="answer")

    monkeypatch.setattr(runner, "_run_agent", fake_agent_run)
    handler = runner.make_message_handler(
        channel=SimpleNamespace(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_allowed"},
    )

    await handler(_message())

    assert not called


@pytest.mark.anyio
async def test_handler_sends_nonempty_agent_output_as_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kapy_collections.starters.feishu import runner

    sent: list[tuple[object, ...]] = []

    class FakeChannel:
        async def send(self, *args: object) -> SimpleNamespace:
            sent.append(args)
            return SimpleNamespace(success=True)

    async def fake_agent_run(**_: object) -> object:
        return SimpleNamespace(output="  answer  ")

    monkeypatch.setattr(runner, "_run_agent", fake_agent_run)
    message = _message()
    handler = runner.make_message_handler(
        channel=FakeChannel(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_user"},
    )

    await handler(message)

    assert sent == [("oc_chat", {"text": "answer"}, {"reply_to": "om_message"})]


@pytest.mark.anyio
async def test_handler_persists_record_once_before_sending_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    record = SimpleNamespace(output="answer", compacted=[])

    class MemoryStore:
        def append(self, saved_record: object) -> None:
            assert saved_record is record
            order.append("persist")

    class Channel:
        async def send(self, *_: object) -> SimpleNamespace:
            order.append("send")
            return SimpleNamespace(success=True)

    async def fake_agent_run(**_: object) -> object:
        return record

    monkeypatch.setattr(feishu_runner, "_run_agent", fake_agent_run)
    handler = feishu_runner.make_message_handler(
        channel=Channel(),
        model=object(),
        config=object(),
        memory_store=MemoryStore(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message())

    assert order == ["persist", "send"]


@pytest.mark.anyio
async def test_handler_sends_reply_if_memory_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent: list[tuple[object, ...]] = []

    class BrokenStore:
        def append(self, _: object) -> None:
            raise OSError("disk unavailable")

    class Channel:
        async def send(self, *args: object) -> SimpleNamespace:
            sent.append(args)
            return SimpleNamespace(success=True)

    async def fake_agent_run(**_: object) -> object:
        return SimpleNamespace(output="answer", compacted=[])

    monkeypatch.setattr(feishu_runner, "_run_agent", fake_agent_run)
    handler = feishu_runner.make_message_handler(
        channel=Channel(),
        model=object(),
        config=object(),
        memory_store=BrokenStore(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message())

    assert len(sent) == 1
    assert "memory persistence failed (OSError)" in caplog.text


@pytest.mark.anyio
async def test_handler_sends_fallback_for_empty_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kapy_collections.starters.feishu import runner

    sent: list[tuple[object, ...]] = []

    class FakeChannel:
        async def send(self, *args: object) -> SimpleNamespace:
            sent.append(args)
            return SimpleNamespace(success=True)

    record = SimpleNamespace(output="  ", compacted=["<output></output>"])

    async def fake_agent_run(**_: object) -> object:
        return record

    monkeypatch.setattr(runner, "_run_agent", fake_agent_run)
    handler = runner.make_message_handler(
        channel=FakeChannel(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message())

    assert sent
    assert sent[0][1] == {
        "text": "Sorry, I couldn't prepare a reply this time. Please try again."
    }
    assert record.output == sent[0][1]["text"]
    assert record.compacted == [f"<output>{record.output}</output>"]


@pytest.mark.anyio
async def test_handler_sends_generic_error_when_agent_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kapy_collections.starters.feishu import runner

    sent: list[tuple[object, ...]] = []

    class FakeChannel:
        async def send(self, *args: object) -> SimpleNamespace:
            sent.append(args)
            return SimpleNamespace(success=True)

    async def failing_agent_run(**_: object) -> object:
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(runner, "_run_agent", failing_agent_run)
    handler = runner.make_message_handler(
        channel=FakeChannel(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message())

    assert sent[0][0] == "oc_chat"
    assert sent[0][2] == {"reply_to": "om_message"}
    assert "private diagnostic" not in sent[0][1]["text"]


@pytest.mark.anyio
async def test_handler_ignores_self_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    from kapy_collections.starters.feishu import runner

    called = False

    async def fake_agent_run(**_: object) -> object:
        nonlocal called
        called = True
        return SimpleNamespace(output="answer")

    monkeypatch.setattr(runner, "_run_agent", fake_agent_run)
    handler = runner.make_message_handler(
        channel=SimpleNamespace(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message(sender_is_bot=True))

    assert not called


@pytest.mark.anyio
async def test_handler_ignores_group_even_when_sender_is_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kapy_collections.starters.feishu import runner

    called = False

    async def fake_agent_run(**_: object) -> object:
        nonlocal called
        called = True
        return SimpleNamespace(output="answer")

    monkeypatch.setattr(runner, "_run_agent", fake_agent_run)
    handler = runner.make_message_handler(
        channel=SimpleNamespace(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message(chat_type="group"))

    assert not called


@pytest.mark.anyio
async def test_handler_logs_sdk_send_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from kapy_collections.starters.feishu import runner

    class FailedChannel:
        async def send(self, *_: object) -> SimpleNamespace:
            return SimpleNamespace(success=False, error="permission denied")

    async def fake_agent_run(**_: object) -> object:
        return SimpleNamespace(output="answer")

    monkeypatch.setattr(runner, "_run_agent", fake_agent_run)
    handler = runner.make_message_handler(
        channel=FailedChannel(),
        model=object(),
        config=object(),
        memory_store=_memory_store(),
        allowed_open_ids={"ou_user"},
    )

    await handler(_message())

    assert "Feishu reply send failed: permission denied" in caplog.text


def test_raw_event_diagnostic_logs_only_event_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger=feishu_runner.__name__)
    feishu_runner._log_raw_message_event(
        {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_private"}},
                "message": {"content": "private message text"},
            },
        }
    )

    assert "Feishu inbound event received: im.message.receive_v1" in caplog.text
    assert "ou_private" not in caplog.text
    assert "private message text" not in caplog.text


def test_safety_rejection_diagnostic_logs_only_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feishu_runner._log_safety_rejection(
        SimpleNamespace(reason="duplicate", message_id="om_private")
    )

    assert "Feishu SDK rejected inbound message: reason=duplicate" in caplog.text
    assert "om_private" not in caplog.text


def test_starter_logs_are_visible_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    feishu_runner._configure_starter_logging()
    feishu_runner.logger.info("Feishu console diagnostic")

    assert "Feishu console diagnostic" in capsys.readouterr().err
