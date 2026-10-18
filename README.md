# Kapybara

This repository runs Kapybara channel starters inside Docker. The container
mounts `data/fs`, so integration credentials, launcher script, and agent config
live there on the host.

## Prerequisites

- Docker and Docker Compose

## Telegram Setup

1. Create `data/fs/.env` from `data/fs/.env.example` and set your Telegram
   token. Recommended:

```dotenv
TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
# JINA_AI_KEY="optional"
```

2. Create `data/fs/start.sh` from `data/fs/start.example.sh`.
   By default, the example includes a `--chat_id` watchlist with placeholder
   values. Replace those with real trusted chat IDs, or remove `--chat_id`
   entirely to accept updates from all chats.

Warning: removing `--chat_id` means the bot will accept updates from every chat
it can see. Only run that mode if you intentionally want an unrestricted bot,
and prefer a trusted allowlist for normal usage.

3. Create `data/fs/.kapybara/config.toml` from
   `data/fs/.kapybara/config.example.toml` and configure the default model used
   by `agent_run`. Recommended Google AI Studio settings:

```toml
[agent_run]
provider = "google"
model_name = "gemini-3-flash-preview"
google_api_key = "your-google-ai-studio-api-key"
# google_base_url = "https://generativelanguage.googleapis.com"
```

If you use Logfire, add it as an optional section in `config.toml`:

```toml
[logfire]
token = "your-logfire-token"
```

## Start The Stack

Run Docker Compose from the [`docker`](/Users/beautyyu/Dev/Kapybara/docker)
directory so the compose file resolves relative paths correctly:

```bash
cd docker
export PUID="$(id -u)" PGID="$(id -g)"
docker compose up -d
```

Check status:

```bash
docker compose ps
docker compose logs -f
```

Stop the stack:

```bash
docker compose down
```

## GPU Support

If you do want NVIDIA GPU reservation, add the override file:

```bash
cd docker
export PUID="$(id -u)" PGID="$(id -g)"
docker compose \
  -f docker-compose.yaml \
  -f docker-compose.gpu.yaml \
  up -d
```

## Runtime Notes

- The container mounts `data/fs` to `/home/k`.
- `start.sh` is launched by Supervisor inside the container.
- `K_CONFIG_BASE` defaults to `/home/k/.kapybara`.

## Feishu Self-Built App

The Feishu starter uses the official `lark-channel-sdk` over WebSocket. It
processes allowlisted private text messages and replies in the same chat. Create
`data/fs/.env` from `data/fs/.env.example` and `data/fs/start.sh` from
`data/fs/start.feishu.example.sh`, then set these values in `data/fs/.env`:

```dotenv
LARK_APP_ID="cli_..."
LARK_APP_SECRET="..."
LARK_ALLOWED_OPEN_IDS="ou_..."
```

The allowlist is required. To learn your own `open_id` before enabling agent
access, set `LARK_ALLOWED_OPEN_IDS="discover"`, start the stack, and send the
bot a private message. Discovery mode only logs the sender ID and never calls
the agent. Read it with `docker compose logs -f basic-os`, replace `discover`
with that ID, then restart the container. Keep `.env` private. This setup does
not require a Telegram token.

Build the local image so it installs `lark-channel-sdk`, then start the service
from the `docker` directory:

```bash
cd docker
export PUID="$(id -u)" PGID="$(id -g)"
docker compose build basic-os
docker compose up -d basic-os
docker compose logs -f basic-os
```

After setting the discovered open_id in `data/fs/.env`, restart with
`docker compose restart basic-os`.

In the Feishu developer console, create and publish a self-built app, add the
bot capability, enable WebSocket event reception, and subscribe to the
`im.message.receive_v1` event. Grant the app the `im:message` and
`im:message:send_as_bot` permissions, then ensure the bot is available to your
account. The adapter ignores group messages and bot-originated messages. The
SDK deduplicates in memory within one process; a process restart or multiple
instances can allow an event to run again.
