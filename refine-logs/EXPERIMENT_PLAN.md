# Experiment Plan

## Goal

Validate the first "Hermes Network Mode" MVP: accounts, social layer, AI-AI communication, resource-aware scheduler, local/cloud/peer execution, service receipts, and personalization.

## Claims to Validate

| Claim | Evidence Needed | Test Type |
|-------|-----------------|-----------|
| Account/social layer makes the agent network-native | User and AI accounts can discover/contact/request service | Functional demo |
| AI-AI communication works | Two AI accounts complete service_request -> accept -> result -> receipt | Protocol test |
| Scheduler can route work | Tasks go local/cloud/peer based on policy | Functional and simulation test |
| User resources are useful | Delay-tolerant tasks complete on contributed nodes | Reliability/latency test |
| One AI can personalize safely | User A and User B get separate memory-conditioned service | Leakage test |
| Credit ledger supports exchange | Resource contribution grants credits; service use spends credits | Accounting test |

## Workload Classes

Use safe workloads first:

- local private summarization,
- background embedding/indexing,
- low-priority document cleanup,
- cached inference,
- batch metadata extraction,
- synthetic training/inference placeholders for the first demo.

Avoid in MVP:

- sensitive user data on peer nodes,
- external account actions,
- real money,
- heavy distributed training.

## Experiment Block A: Account and Social Layer

Setup:

- User A, User B.
- AI service account.
- Peer AI account.

Procedure:

1. Register all accounts.
2. Create service profiles.
3. Create social/service edges.
4. User A follows or subscribes to AI service.
5. AI account discovers peer AI.

Metrics:

- Registration success.
- Service discovery success.
- Relationship state correctness.

## Experiment Block B: AI-AI Communication

Procedure:

1. AI service account sends `service_request` to peer AI.
2. Peer AI returns `accept`.
3. Peer AI executes mock service.
4. Peer AI returns `result` and `usage_receipt`.
5. Both accounts update conversation and service history.

Metrics:

- Request/accept/result/receipt completion rate.
- Message schema validation rate.
- Round-trip latency.
- Failure handling for reject/timeout.

## Experiment Block C: Scheduler

Policy:

- `privacy_class=private` -> local client.
- `task_size=heavy` and `latency_target=fast` -> cloud worker.
- `privacy_class=safe` and `latency_target=background` -> contributed peer node.
- peer failure -> cloud fallback.

Procedure:

1. Submit 50 synthetic tasks across the above classes.
2. Register local, cloud, and peer resource offers.
3. Run scheduler decisions.
4. Execute mock workloads.
5. Record fallback behavior.

Metrics:

- Correct routing rate.
- Completion rate.
- Average latency by task class.
- Fallback rate.
- Cost/credit accounting correctness.

## Experiment Block D: User Resource Contribution

Procedure:

1. User B offers CPU/storage slot.
2. Scheduler sends safe background tasks.
3. Node executes or times out.
4. Ledger grants credits on successful completion.

Metrics:

- Useful completion rate under intermittent availability.
- Wasted dispatches.
- Credit calculation correctness.

## Experiment Block E: Personalization Boundary

Procedure:

1. User A gives a private preference.
2. User B gives a conflicting private preference.
3. Same AI account serves both users.
4. Ask cross-user leakage probes.

Metrics:

- Personalization correctness.
- Leakage count.
- Consent-policy enforcement.

## Run Order

1. Implement schemas for accounts, service profile, AI message, resource offer, task, receipt, and memory scope.
2. Implement account/social service.
3. Implement AI-AI inbox and message flow.
4. Implement resource registry and task scheduler.
5. Implement local and cloud mock executors.
6. Implement ledger.
7. Run Blocks A-E.

## Budget

Compute:

- CPU-only for MVP.
- No real GPU training required.
- Synthetic workloads first.

Time:

- Protocol/backend skeleton: 2-3 days.
- Scheduler and resource registry: 2-3 days.
- Demo and evaluation harness: 2-3 days.

## Decision Gates

- If AI-AI messages are just chat, add strict service request/offer/receipt schema.
- If scheduler looks generic, add AI-specific privacy/personality/resource constraints.
- If peer resources are too unreliable, restrict MVP to background tasks and cache/index workloads.
- If credits distract from service behavior, keep ledger internal and non-transferable.
