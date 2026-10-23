# Channel Design

## Data model

Structured input events use:

- `in_channel: str` (required)
- `contacts: list[str]` (optional, `<platform>/<user_id>` entries when known)
- `out_channel: str | None` (optional)

`out_channel=None` means "same as `in_channel`" for routing and skill selection.

Memory records keep:

- `in_channel: str` (required)
- `out_channel: str | None` (optional)

## Channel format

A channel is a URL-path-like hierarchy:

- Slash-separated segments
- No empty segments
- No leading or trailing slash

Example of a hierarchical channel (the current Feishu starter emits
`feishu/chat/<chat_id>` for direct messages):

`feishu/chat/<chat_id>/thread/<message_thread_id>`

## Skill injection

Let `root(channel)` be the first channel segment.

- Messager skill: `messager/{root(effective_out_channel)}`
  - `effective_out_channel = out_channel or in_channel`

This keeps routing explicit while reusing platform-level skills.

## Memory retrieval

When retrieving memory for a channel prefix, filter by `MemoryRecord.in_channel` and `MemoryRecord.out_channel`
using prefix matching.

Example:

- Query prefix: `feishu/chat/<chat_id>`
- Matches:
  - `feishu/chat/<chat_id>`
  - `feishu/chat/<chat_id>/thread/1`
  - `feishu/chat/<chat_id>/thread/2`

## Preference injection

For an `in_channel`/`out_channel`, inject preferences in this order:

Preference files are resolved from `~/.kapybara/preferences`.

1. Root-level preference:
   - `PREFERENCES.md` if present
   - otherwise `PREFERENCES.default.md`
2. For each root-to-leaf channel prefix that exists, inject:
   - `<prefix>.md`
   - `<prefix>/PREFERENCES.md`

Example for `feishu/chat/<chat_id>`:

1. `PREFERENCES.md`
2. `feishu.md`
3. `feishu/PREFERENCES.md`
4. `feishu/chat.md`
5. `feishu/chat/PREFERENCES.md`
6. `feishu/chat/<chat_id>.md`
7. `feishu/chat/<chat_id>/PREFERENCES.md`

## Required Fields

Runtime input events require `in_channel`, with optional `contacts` and
`out_channel`. Memory retrieval requires records to carry `in_channel` (and
optional `out_channel`).
