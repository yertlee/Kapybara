"""CLI entrypoint for the Feishu WebSocket starter."""

from __future__ import annotations

import argparse
import os

import anyio

from . import parse_allowed_open_ids
from .runner import run_forever


def _parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read credentials and mandatory access allowlist from the environment."""

    parser = argparse.ArgumentParser(
        prog="feishu",
        description="Feishu WebSocket starter (private text messages -> agent_run).",
    )
    parser.add_argument(
        "--model-name", default=None, help="Optional model id override."
    )
    return parser.parse_args(argv)


async def main() -> None:
    """Validate required environment and start the long-running adapter."""

    args = _parse_cli_args()
    app_id = os.environ.get("LARK_APP_ID", "").strip()
    app_secret = os.environ.get("LARK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise ValueError("LARK_APP_ID and LARK_APP_SECRET are required")
    raw_allowlist = os.environ.get("LARK_ALLOWED_OPEN_IDS", "").strip()
    allowed_open_ids = (
        set()
        if raw_allowlist.lower() == "discover"
        else parse_allowed_open_ids(raw_allowlist)
    )
    await run_forever(
        app_id=app_id,
        app_secret=app_secret,
        allowed_open_ids=allowed_open_ids,
        model=args.model_name,
    )


def cli() -> None:
    """Synchronous installed-script entrypoint."""

    anyio.run(main)


if __name__ == "__main__":
    cli()
