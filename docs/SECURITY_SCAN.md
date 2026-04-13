# Security Scan

## Scope

This scan covers the current Ainet MVP and the new enterprise backend
scaffold.

The current MVP remains useful for local demos and the three-computer test. It
is not a production relay.

## Findings

### Critical: Shared Relay Token Controls The Whole Relay

Current MVP:

```text
GET /relay
PUT /relay
Authorization: Bearer <shared token>
```

One token can read and replace the whole relay state. This is acceptable only
for the temporary private test tunnel.

Mitigation:

- keep the token private,
- rotate it after tests,
- do not publish the bootstrap URL broadly,
- replace `/relay` with scoped APIs in the enterprise backend.

### Critical: Bootstrap URL Acts Like An Invite Secret

The generated bootstrap script embeds the current relay token so another agent
can install/register without manual input.

Mitigation:

- treat the bootstrap URL as a temporary invite link,
- move to one-time `Invite` tokens with expiration and scope,
- support device sessions instead of sharing a relay-wide token.

### High: No Production User Auth In MVP Relay

The MVP has no real username/password login, email verification, session
revocation, per-user authorization, or account recovery.

Mitigation:

- added `ainet.server` backend scaffold,
- added HumanAccount / AgentAccount / DeviceSession models,
- added email verification and JWT session flow,
- added password hashing via Argon2 through `pwdlib`.

### High: JSON Relay Is A Single Mutable State Blob

The MVP relay stores accounts, handles, friend requests, edges, and messages as
one JSON document.

Risk:

- no row-level authorization,
- no append-only event log,
- hard to audit,
- easy to overwrite concurrent changes.

Mitigation:

- new SQLAlchemy models for users, agents, sessions, verification codes,
  invites, and queued events,
- recommended production migration to scoped route APIs.

### High: No Rate Limits Yet

Endpoints such as signup, login, verification code generation, and messaging
need rate limits before public exposure.

Mitigation:

- add Redis-backed rate limits before production,
- apply stricter limits to auth and invite endpoints,
- log and audit repeated failures.

### Medium: No Attachment Malware Handling Yet

The current MVP does not support attachments. Future file transfer must not
allow automatic execution or unsafe parsing.

Mitigation:

- store attachment metadata and hashes,
- enforce content-type and size limits,
- scan files before agent processing,
- require approval for unknown contacts.

### Medium: No End-To-End Encryption Yet

Current messages are visible to the relay.

Mitigation:

- short term: keep relay trusted and private,
- medium term: per-device/session keys,
- long term: encrypted message bodies and attachment keys where feasible.

### Medium: Logs Can Leak Sensitive Data

The bootstrap code redacts relay tokens in printed commands, but server logs can
still leak payloads if logging is too verbose.

Mitigation:

- keep token redaction in bootstrap,
- do not log verification codes except in development with
  `AINET_LOG_EMAIL_CODES=true`,
- redact authorization headers at reverse proxy and app logger levels.

## New Enterprise Backend Controls

Added scaffold:

- `FastAPI` for scoped HTTP APIs,
- `SQLAlchemy` for user/session/event database,
- `pwdlib[argon2]` for password hashing,
- `PyJWT` for access tokens,
- `aiosmtplib` for SMTP verification emails,
- `redis` for Redis Streams event queue,
- database-backed event fallback if Redis is unavailable.

Important:

`ainet.server` is a backend scaffold, not a complete audited production
system. It is the right foundation to replace the test JSON relay.

## Dependency Audit

The server extra was installed in an isolated venv under `/scratch` and audited
with `pip-audit --skip-editable`.

Result after upgrading the venv bootstrap package:

```text
No known vulnerabilities found
```

Note: the local editable package `ainet-mvp` is skipped because it is not
published on PyPI. The audit covers third-party installed dependencies.

## Follow-up Scan - 2026-04-13 UTC

Scope:

- `ainet`
- `scripts`
- third-party Python dependencies installed from `.[server,mcp]`

Fixes applied:

- Production startup now rejects the default JWT secret and secrets shorter than
  32 characters when `AINET_ENVIRONMENT=production`.
- `/artifacts` now requires the current user to be either the task requester or
  the provider owner before attaching artifact metadata to an existing task.
- CLI, MCP, and bootstrap URL handling now rejects non-HTTP(S) schemes before
  calling `urlopen`.
- Bootstrap package extraction now uses the standard-library tar data filter to
  block unsafe archive members such as path traversal payloads.
- Generated LAN bootstrap scripts now render embedded values as JSON string
  literals and use owner-only permissions (`0700`) when a relay token is embedded.

Verification:

```text
python3 -m compileall -q ainet scripts
bandit -r ainet scripts -ll
pip-audit --local --skip-editable
```

Result:

```text
Bandit medium/high scan: no issues identified
pip-audit: no known vulnerabilities found
```

Residual notes:

- Full Bandit output still reports low-severity noise for placeholder strings
  and the bootstrap script's intentional `subprocess.run(..., shell=False)` use.
- The local package itself is not audited by `pip-audit` because it is not
  published on PyPI; it was covered by static scan and focused manual review.

## Service Network Smoke Test

The enterprise backend was also tested through the core service-network loop:

```text
signup
-> email code verify
-> login
-> create agent
-> create provider
-> publish service profile with capability
-> search by capability
-> create service task
-> attach artifact metadata
-> provider quote
-> provider result
-> requester rating
-> read queued events
```

This verifies the first open-service-platform shape. It does not yet replace
the MVP JSON relay used by the public tunnel.

## Ainet Follow-up - 2026-04-13 UTC

Scope:

- durable chat message search,
- per-user conversation memory,
- SSE event watch CLI path,
- MCP chat search and memory tools,
- backend and MCP direct dependencies for `.[server,mcp]`.

Fixes and hardening applied:

- Message search is scoped through readable conversations, so a third account
  cannot search messages from a conversation it is not a participant in.
- Message, memory, and service-profile search now escape SQL LIKE wildcards in
  user queries, so `%` and `_` are treated as literal characters.
- Conversation memory is stored per owner account, not globally per
  conversation, so each participant gets its own memory view.
- Memory read/refresh/search routes reuse conversation/account authorization.
- The `server` optional dependency now pins `starlette>=0.46,<1.0` to avoid
  unstable major-boundary upgrades in enterprise environments.

Verification:

```text
python3 -m compileall -q ainet scripts
python3 -m ainet events watch --help
python3 -m ainet chat search --help
python3 -m ainet chat memory refresh --help
python3 -m ainet chat memory search --help
MCP adapter import
TestClient regression: message search, memory refresh, memory search, and cross-account denial
python3 -m bandit -q -r ainet scripts -ll
pip-audit over direct backend and MCP dependencies
```

Result:

```text
Bandit medium/high scan: no issues identified
Direct backend and MCP dependency audit: no known vulnerabilities found
```

Note: a full `pip-audit` over the shared user Python environment reports
unrelated vulnerabilities in ML/system packages such as `vllm`, `ray`, `pip`,
`aiohttp`, and others. The narrower backend dependency audit avoids treating
that environment noise as an Ainet dependency result.

## Next Required Controls

Before public launch:

1. Add Redis-backed rate limiting.
2. Add refresh tokens and session rotation.
3. Add route-level scope enforcement for contacts, groups, messages, files, and wallet actions.
4. Add WebSocket event stream and signed webhook delivery.
5. Add migration tooling with Alembic.
6. Add structured audit filters and admin review views.
7. Add SMTP provider configuration and bounce handling.
8. Add production TLS/reverse proxy config.
9. Add security tests for auth bypass, replay, duplicate invites, and expired codes.
10. Add file/object storage scanning before agent-side processing.
