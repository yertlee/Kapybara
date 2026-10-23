from __future__ import annotations

import pytest

from k.agent.channels import (
    channel_has_prefix,
    channel_root,
    effective_out_channel,
    iter_channel_prefixes,
    normalize_out_channel,
    validate_channel_path,
    validate_contact_path,
)


def test_validate_channel_path_accepts_non_empty_segments() -> None:
    assert (
        validate_channel_path(
            "feishu/chat/123/thread/9",
            field_name="in_channel",
        )
        == "feishu/chat/123/thread/9"
    )


@pytest.mark.parametrize("bad", ["", " ", "/feishu", "feishu/", "feishu//chat"])
def test_validate_channel_path_rejects_invalid_shapes(bad: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_channel_path(bad, field_name="in_channel")


def test_validate_contact_path_accepts_platform_user_id() -> None:
    assert (
        validate_contact_path("feishu/567113516", field_name="contact")
        == "feishu/567113516"
    )


@pytest.mark.parametrize(
    "bad",
    ["", " ", "feishu", "feishu/", "/567113516", "feishu/123/extra"],
)
def test_validate_contact_path_rejects_invalid_shapes(bad: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_contact_path(bad, field_name="contact")


def test_out_channel_helpers() -> None:
    assert normalize_out_channel(in_channel="feishu/chat/1", out_channel=None) is None
    assert (
        normalize_out_channel(
            in_channel="feishu/chat/1",
            out_channel="feishu/chat/1",
        )
        is None
    )
    assert (
        effective_out_channel(
            in_channel="feishu/chat/1",
            out_channel=None,
        )
        == "feishu/chat/1"
    )


def test_channel_path_helpers() -> None:
    assert channel_root("feishu/chat/1/thread/2") == "feishu"
    assert channel_has_prefix(
        channel="feishu/chat/1/thread/2",
        prefix="feishu/chat/1",
    )
    assert not channel_has_prefix(
        channel="feishu/chat/2/thread/2",
        prefix="feishu/chat/1",
    )
    assert iter_channel_prefixes("feishu/chat/1") == [
        "feishu",
        "feishu/chat",
        "feishu/chat/1",
    ]
