# Harness Design Next Development Plan

## Core Read

The Z Tech Harness Design interview is highly aligned with Ainet's current
direction, but it also changes the priority order.

Ainet should not be framed as another agent framework or a human chat app
rebuilt for agents. The sharper framing is:

```text
Ainet is an agent-native harness substrate: identity, relationships, group
context, memory, service execution, and verifiable delivery for agents that
need to work across sessions and across runtimes.
```

The next development phase should therefore focus on the infrastructure layer
that stronger models still cannot own by themselves:

- persistent identity,
- durable relationships,
- group/workspace substrate,
- cross-session memory and trajectory reuse,
- verifiable service delivery,
- runtime-agnostic MCP/A2A adapters,
- self-hosted homeserver operations.

This should take priority over broad social-app surface area such as moments,
wallet depth, mini-app marketplace depth, and resource-protocol scheduling.

## Product Thesis

Current Ainet positioning:

```text
Self-hosted agent communication and service network.
```

Next positioning:

```text
Self-hosted harness substrate for agent identity, memory, collaboration, and
verifiable service execution.
```

In practical terms:

- "identity" means every human, agent, provider, runtime, and device has a
  persistent account and relationship history.
- "group substrate" means agents do not collaborate through raw chat alone;
  they share structured context, permissions, memory, files, tasks, and receipts.
- "verification" means every service task can produce artifacts, checks,
  receipts, ratings, and audit history before any real payment layer exists.
- "transparent harness" means users should increasingly ask for goals, not
  manually switch between tools, agents, channels, and workflows.

## Next 6-Week Goal

Build an `Ainet Harness Core MVP`:

```text
An agent can join a self-hosted Ainet homeserver, keep a stable identity,
enter a group workspace, exchange task context with another agent, complete a
service task, attach artifacts, run verification checks, and leave behind
searchable memory, receipts, and audit records.
```

The demo should work through CLI and MCP first. A web or mobile UI can wait.

## Milestone 0: Reframe The Public Roadmap

Timebox: 0.5-1 day

Deliverables:

- Update README and ROADMAP language from generic social/service network toward
  `agent-native harness substrate`.
- Keep the self-hosted Ainet Homeserver direction.
- Make "resource network" explicitly later-stage.
- Add a short architecture diagram:

```text
Agent Runtime -> Ainet Agent Bridge -> Ainet Homeserver -> Search/Memory/Audit
```

Acceptance criteria:

- README answers "why not just use chat/MCP/A2A directly?"
- ROADMAP lists `identity`, `group substrate`, `verification`, and
  `homeserver ops` as the next near-term priorities.
- No claim that Ainet already has resource scheduling, real payments, or full
  federation.

## Milestone 1: Persistent Identity And Relationship Layer

Status: first backend slice implemented. Agent accounts now carry key metadata,
contacts carry trust and permission scopes, `ainet identity show`,
`ainet contact trust`, and `ainet contact permissions` exist, MCP exposes
identity/contact permission tools, and cross-account DM plus agent-backed
service task creation are relationship-gated.

Timebox: 1 week

Why:

The article's strongest point is that current agents live in disposable
sessions. Ainet's first defensible primitive should be persistent identity plus
relationship history.

Engineering tasks:

- Add or harden identity records for:
  - human account,
  - agent account,
  - runtime/device session,
  - provider/service profile,
  - group/workspace membership.
- Add trust scopes on relationships:
  - `dm`,
  - `group_invite`,
  - `service_request`,
  - `artifact_read`,
  - `artifact_write`,
  - `memory_read`,
  - `memory_write`,
  - `requires_human_approval`.
- Add key metadata fields for future signing:
  - public key,
  - key id,
  - rotation timestamp,
  - verification status.
- Add CLI/MCP surfaces:
  - `ainet identity show`,
  - `ainet contact trust`,
  - `ainet contact permissions`,
  - MCP tools for identity/contact permission reads.

Acceptance criteria:

- A task or message can be traced back to a stable agent identity and runtime
  session.
- Relationship permissions are stored and enforced server-side.
- An agent cannot read group memory, artifacts, or service context without the
  right relationship or membership permission.

## Milestone 2: Group Workspace Substrate

Status: first backend slice implemented. Groups now have owner/member records,
membership permissions, durable group messages, per-user group memory refresh,
service task context links, route-level `groups:*` scopes, CLI commands under
`ainet group`, MCP group tools, and regression tests for permission boundaries.
Group artifacts, accept-invite workflow, and group search are still future work.

Timebox: 1-1.5 weeks

Why:

The article argues that agent collaboration should not be a clone of human
chat rooms. In Ainet, a group should be a structured substrate, not only a
message thread.

Engineering tasks:

- Add backend models:
  - `Group`,
  - `GroupMember`,
  - `GroupMemory`,
  - `GroupMessage`,
  - `GroupTaskContext`.
- Add group APIs:
  - create group,
  - invite member,
  - list groups,
  - send group message,
  - read/refresh group memory,
  - attach service task to group.
- Add permission checks:
  - read group,
  - write group,
  - invite agent contact to group,
  - attach visible service task,
  - write shared memory.
- Add CLI/MCP tools:
  - `ainet group create`,
  - `ainet group invite`,
  - `ainet group send`,
  - `ainet group memory`,
  - `ainet group task`.

Acceptance criteria:

- Two agents and one human can share a group workspace.
- The group stores messages, task references, and memory summaries.
- Existing service tasks can be attached to a group and retain group context.
- Non-members and scoped-down tokens cannot read group context.

## Milestone 3: Verifiable Service Execution Loop

Status: first backend slice implemented. Service tasks now start as `created`,
providers can accept tasks, update execution status, submit result receipts,
and requesters can verify or reject with structured `VerificationRecord`
evidence. Ratings are gated on verified or legacy completed tasks. CLI commands
exist under `ainet service task`, MCP exposes matching service tools, and
regression tests cover provider/requester authorization, receipts, verification,
rejection, and reputation updates.

Timebox: 1.5 weeks

Why:

The article identifies verification as the condition for an agent economy.
Before payments or marketplace depth, Ainet needs task acceptance, artifacts,
checks, receipts, ratings, and audit records.

Engineering tasks:

- Extend service task states:
  - `created`,
  - `accepted`,
  - `in_progress`,
  - `submitted`,
  - `verification_running`,
  - `verified`,
  - `rejected`,
  - `failed`,
  - `cancelled`.
- Add `VerificationRecord`:
  - task id,
  - verifier account id,
  - verification type,
  - rubric/check schema,
  - result,
  - evidence artifact refs,
  - created timestamp.
- Add simple verification modes:
  - checklist/rubric result,
  - command/test result reference,
  - human approval result,
  - peer-agent review result.
- Emit service events:
  - `task.accepted`,
  - `task.status_updated`,
  - `task.submitted`,
  - `task.verified`,
  - `task.rejected`,
  - `task.failed`.
- Add CLI/MCP tools:
  - `ainet service task accept`,
  - `ainet service task status`,
  - `ainet service task submit-result`,
  - `ainet service task verify`,
  - `ainet service task reject`.

Acceptance criteria:

- A provider agent can accept a task, submit an artifact, and produce a receipt.
- A requester can verify or reject delivery with structured evidence.
- Audit logs can reconstruct who asked, who accepted, what was submitted, what
  verification happened, and what the final status was.
- Ratings/reputation are based on completed or verified tasks, not raw chat.

## Milestone 4: Long-Running Agent Runtime Support

Timebox: 1 week

Why:

Harness quality is measured by whether the same model can run longer and more
stably without human intervention.

Engineering tasks:

- Add `ainet daemon run`:
  - follows SSE stream,
  - stores cursor locally,
  - keeps a local inbox cache,
  - reconnects on transient failure,
  - rate-limits notifications.
- Add proactive summary command:
  - `ainet home`,
  - `ainet notifications`,
  - `ainet ask "what needs attention?"`.
- Add runtime-neutral task adapter interface:

```text
receive task -> run local adapter -> attach artifact/result -> emit receipt
```

- Implement a safe first adapter:
  - local shell command adapter for explicitly approved test commands, or
  - dry-run adapter that records planned execution without running arbitrary
    commands.

Acceptance criteria:

- An agent does not need to manually poll inbox to notice high-priority events.
- The daemon can restart and continue from the last event cursor.
- The first adapter can complete a toy service task end-to-end without giving
  agents broad unreviewed execution authority.

## Milestone 5: Self-Hosted Homeserver Production Path

Timebox: 1 week

Why:

The article's substrate argument only matters if users can actually own and run
the substrate. This also matches the existing Ainet self-hosted direction.

Engineering tasks:

- Add Docker Compose stack:
  - Ainet API,
  - PostgreSQL,
  - Redis,
  - MinIO,
  - Meilisearch,
  - Caddy or Traefik.
- Add Alembic migrations for the current SQLAlchemy schema.
- Add `ainet server bootstrap --domain DOMAIN --email ADMIN_EMAIL`.
- Add `ainet server backup` and `ainet server restore` skeleton commands.
- Add production config checks:
  - JWT secret strength,
  - SMTP readiness,
  - object storage health,
  - search backend health,
  - database migration state.

Acceptance criteria:

- A fresh VPS can run a working Ainet homeserver from documented commands.
- The first admin can create an invite and pair an agent runtime.
- `ainet server doctor` catches missing secrets, unavailable services, and
  migration drift before the server is treated as ready.

## What To Defer

Defer these until Harness Core is working:

- resource contribution and distributed scheduling,
- real-money payments,
- UCP/AP2 integration,
- public federation,
- full marketplace ranking,
- moments/status feed,
- mobile UI,
- complex mini-app marketplace.

These are useful later, but they depend on identity, group substrate, memory,
verification, and homeserver operations being stable first.

Resource work should return as a protocol layer, not as Ainet-hosted model
infrastructure: users and agents may later offer GPU training, GPU inference,
API quota, or cloud/local endpoints through ResourceOffer and ResourceTask
objects.

## Demo Target

Build one demo that proves the article's thesis in Ainet terms:

```text
1. Alice creates a self-hosted Ainet homeserver.
2. Alice pairs a local agent with a stable identity.
3. Bob pairs another agent.
4. Alice creates a group workspace and invites Bob's agent.
5. Alice asks for a code-review service task inside the group.
6. Bob's agent accepts the task and submits an artifact.
7. Alice or Alice's agent verifies the artifact with a checklist or test result.
8. Ainet records memory, receipt, rating, and audit history.
9. A restarted agent can search the group memory and continue from prior state.
```

This demo is stronger than a broad feature demo because it directly validates:

- identity persistence,
- relationship permissions,
- group substrate,
- durable task context,
- verifiable delivery,
- cross-session memory,
- long-running runtime support.

## Priority Order

1. Reframe docs around Harness Core.
2. Implement identity/relationship permissions.
3. Implement group workspace substrate.
4. Implement verifiable task lifecycle.
5. Implement daemon and runtime adapter MVP.
6. Implement self-hosted Docker Compose and bootstrap path.

If schedule is tight, cut from the bottom, not the top. The product only becomes
distinctive if identity, group substrate, verification, and memory work first.
