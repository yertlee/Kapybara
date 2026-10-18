---
name: messager/feishu
description: Prepare plain-text replies for the Feishu adapter to deliver.
---

# messager/feishu

For Feishu direct messages, the integration adapter sends the response after
`agent_run` returns. Do not call `curl`, other external tools, or the Feishu
SDK to send a reply; that would duplicate delivery.

For eligible allowlisted private text messages, reply by default. Put only the
complete user-facing plain text reply in `finish_action.raw_output`; every
non-empty output is sent to the source chat as a reply, so do not put delivery
notes, status summaries, or explanations about sending there. When a near-limit
warning says to finish immediately, do not run more commands or try another
delivery method: put a concise, factual partial answer in `raw_output` using
only what you have verified. If work is incomplete, state what is known and
what remains; never claim that no reply was sent or that the request limit was
reached unless that is factually true. Leave `raw_output` empty only when the
message truly needs no reply, and state that reason in `compacted_actions`.

Passing `parent_memories=[]` means no explicit parent records were selected;
the core agent still injects recent channel and contact memories automatically.
