# Ainet Self-Hosted Open Source Plan

## Name

Project name:

```text
Ainet
```

Meaning:

```text
AI Native Network
```

Component names:

```text
Ainet Client       -> CLI, local daemon, future web/mobile client
Ainet Homeserver   -> self-hosted communication and service-network server
Ainet Agent Bridge -> MCP/A2A/runtime adapters
Ainet Ops          -> agent-assisted server bootstrap, backup, upgrade, doctor
```

Working tagline:

```text
Ainet is an open-source agent communication and self-hosted agent service network.
```

## Direction

Use the Element/Matrix pattern as the deployment and ecosystem reference:

```text
open client surface
customizable self-hosted server
open protocol/data model
optional managed hosting later
```

For this project, that becomes:

```text
Ainet Client + Ainet Homeserver + Ainet Agent Bridge
```

The goal is not to become a Matrix client. The goal is to make an open-source
agent network that people can run on their own server, with agents helping them
install, configure, verify, update, and operate it.

## Product Promise

Users should not need our hosted server.

They should be able to:

1. Rent or use an existing VPS.
2. Point a domain or local hostname at it.
3. Run one command.
4. Let an agent configure the server.
5. Receive an admin invite and device pairing link.
6. Connect local agents through CLI, MCP, or future web/mobile clients.

Target sentence:

```text
Ainet: self-host your own agent communication and service network, or connect
to a trusted federation later.
```

## What We Copy From Element/Matrix

Useful patterns:

- client and server are separate,
- users can self-host,
- hosted and self-hosted deployments can share the same product model,
- data ownership belongs to the homeserver operator,
- open standards allow interoperability,
- enterprise deployments need admin controls, permissions, audit, and secure
  updates.

What we do not copy directly:

- the full Matrix protocol on day one,
- broad public federation before abuse controls exist,
- consumer chat-only positioning,
- server hosting as the only way to use the product.

## Target Architecture

```text
Agent clients
  - CLI
  - MCP adapter
  - local daemon
  - future web/mobile UI

Ainet Homeserver
  - auth and device sessions
  - contacts, conversations, groups
  - durable messages and memory
  - service profiles and tasks
  - artifacts, receipts, ratings
  - admin and audit

Open adapters
  - MCP for local tools
  - A2A-style agent cards and tasks
  - future Matrix bridge for human chat interop
  - future UCP/AP2 adapters for commerce/payment verticals
```

## Deployment Modes

### Mode 1: Local Evaluation

For one developer or one laptop.

```text
SQLite
local filesystem
no public federation
no external SMTP required
```

Use this for demos and development.

### Mode 2: Self-Hosted Team Server

For a personal server, lab, small team, or family.

Recommended open-source stack:

```text
Caddy or Traefik      -> TLS and reverse proxy
Ainet Homeserver API  -> FastAPI app
PostgreSQL            -> durable relational data
Redis Streams         -> realtime events and rate limits
MinIO                 -> file/artifact object storage
Meilisearch           -> full-text chat/search index
Qdrant                -> optional vector memory index
OpenTelemetry         -> traces and logs
```

This should be the first serious self-hosting target.

## Enterprise Data Plane

The earlier enterprise backend work should become the Ainet homeserver data
plane, not a separate product.

Baseline production stack:

```text
PostgreSQL          -> source-of-truth relational database
Alembic             -> schema migrations and upgrade/downgrade history
PgBouncer           -> connection pooling for many agents and clients
Redis Streams       -> realtime event bus, presence, rate limits, task queue
MinIO or S3         -> files, voice, artifacts, service packages, backups
Meilisearch         -> simple self-hosted full-text search
OpenSearch          -> larger enterprise full-text search and log search
Qdrant or pgvector  -> vector memory and semantic recall
OpenTelemetry       -> traces, metrics, logs, request correlation
Prometheus/Grafana  -> optional metrics dashboard
```

Core relational tables:

```text
human_accounts
agent_accounts
device_sessions
invites
contacts
conversations
conversation_members
social_messages
conversation_memories
groups
group_members
attachments
providers
service_profiles
capabilities
service_tasks
artifacts
quotes
service_orders
payment_records
wallet_ledger_entries
ratings
audit_logs
reports
moderation_actions
```

Search and memory indexes:

```text
messages_index          -> message body, handles, conversation metadata
memories_index          -> summaries, key facts, pinned memories
service_profiles_index  -> services, categories, capability names
artifacts_index         -> filenames, metadata, hashes
vector_memory_index     -> optional embeddings for long-term recall
```

Object storage buckets:

```text
ainet-attachments
ainet-artifacts
ainet-service-packages
ainet-backups
ainet-audit-exports
```

Durability requirements:

- PostgreSQL is the source of truth.
- Redis is replaceable and replayable from PostgreSQL event records when
  possible.
- Object storage stores content-addressed files with hashes recorded in
  PostgreSQL.
- Search/vector indexes are rebuildable from PostgreSQL and object metadata.
- Backups include PostgreSQL dumps or WAL archives, object storage snapshots,
  and deployment secrets manifest references.

Enterprise controls:

- invite-only registration by default,
- admin-created org/team spaces,
- route-level token scopes,
- audit log retention policy,
- attachment size and type limits,
- malware scanning hook before agent processing,
- backup/restore health check,
- migration preflight before upgrade,
- data export for one user, one group, or one organization,
- retention and deletion workflows.

### Mode 3: Enterprise / Large Agent Network

For many users, many agents, or regulated organizations.

```text
Kubernetes
PostgreSQL managed cluster
Redis cluster
object storage
search/vector cluster
OIDC/SAML
policy engine
audit export
backup/restore automation
```

This mode should be compatible with the same homeserver API, but can use more
professional infrastructure under the hood.

## One-Command Agent Setup

The target command should be:

```bash
ainet server bootstrap --domain agents.example.com --email admin@example.com
```

The bootstrap agent should do the operational work:

1. Inspect OS, CPU, memory, disk, ports, and Docker availability.
2. Check DNS for the selected domain.
3. Generate `.env` with strong secrets.
4. Generate Docker Compose or Kubernetes manifests.
5. Configure reverse proxy and TLS.
6. Start PostgreSQL, Redis, object storage, search, and the API.
7. Run migrations.
8. Create the first admin account or one-time admin invite.
9. Run health checks and security checks.
10. Print pairing commands for local agents.

Target follow-up commands:

```bash
ainet server doctor
ainet server init --domain agents.example.com --email admin@example.com
ainet server deploy --target docker-compose
ainet server status
ainet server invite --admin
ainet server backup
ainet server upgrade
```

The CLI should support an interactive agent mode:

```bash
ainet server autopilot
```

In autopilot mode, the agent asks only for the few values it cannot infer:

```text
domain
admin email
public or private registration
SMTP provider or local dev email mode
storage path or S3/MinIO endpoint
```

## Open Source Distribution

Repository layout target:

```text
deploy/
  docker-compose/
    compose.yaml
    caddy/Caddyfile
    postgres/init.sql
    minio/
    meilisearch/
  kubernetes/
    helm/
  systemd/
scripts/
  server_bootstrap.py
ainet/server/provisioning/
  doctor.py
  secrets.py
  templates.py
  smoke.py
```

The open-source self-hosted version should include:

- source code,
- Docker Compose templates,
- sample Caddy/Traefik config,
- `.env.example`,
- backup and restore script,
- health check script,
- upgrade notes,
- security hardening checklist,
- admin invite flow,
- local agent pairing flow.

## Federation Strategy

Do not start with global federation.

Recommended sequence:

1. Single homeserver with invite-only users and agents.
2. Multiple homeservers with manual trusted peering.
3. Domain-verified homeserver discovery:

```text
https://agents.example.com/.well-known/ainet/server
```

4. Signed Agent Card export and A2A-compatible task endpoints.
5. Optional bridge to Matrix rooms for human chat interoperability.
6. Open federation after rate limits, moderation, report/ban, and trust scoring
   are implemented.

This keeps the open network goal without taking on Matrix-scale abuse handling
too early.

## Future Work From Current Gaps

### Product Surface

- groups,
- reactions,
- mentions,
- read receipts,
- service cards in chat,
- moments/status feed,
- channel pages,
- wallet/receipts UI.

### Self-Hosted Operations

- Docker Compose templates,
- Caddy/Traefik TLS config,
- PostgreSQL production mode,
- Redis-backed rate limits,
- MinIO object storage,
- Meilisearch/OpenSearch full-text search,
- Qdrant vector memory,
- backup/restore,
- migration tooling with Alembic,
- one-command server bootstrap.

### Security

- invite-only default registration,
- route-level scopes for implemented profile/session/contact/message/service/event/audit APIs,
- refresh token rotation,
- domain verification,
- signed Agent Cards,
- file scanning hooks,
- admin audit filters,
- abuse report and ban workflow,
- encrypted secrets at rest for provider credentials.

### Protocol Interop

- A2A-compatible Agent Card and task/status/artifact adapter,
- MCP adapter hardening,
- Matrix bridge later for human rooms,
- UCP/AP2 only for commerce/payment verticals.

## MVP Definition For Self-Hosting

The self-hosted MVP is done when a user can:

1. Run one command on a VPS.
2. Get a working HTTPS Ainet Homeserver.
3. Create an admin account or accept an admin invite.
4. Pair two local agents.
5. Send realtime messages.
6. Search history.
7. Refresh conversation memory.
8. Publish one service profile.
9. Submit one structured task.
10. Back up and restore the server data.

That is the open-source version of the Ainet direction.
