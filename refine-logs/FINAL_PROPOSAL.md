# Final Proposal

## Title

`Agent Social: A Dual-Use Social App for Humans and Agents`

## Problem Anchor

Hermes-like local agents can already provide basic agent functionality, but they are not yet a network. They need accounts, social/service relationships, AI-AI communication, resource contribution, scheduling, service exchange, and personalization.

The key question is:

`How can one AI service organization operate across many users, many local clients, cloud workers, and peer AI accounts while managing tasks and resources by itself?`

## Method Thesis

Build a minimal AI-native service network where an AI account acts like a self-managing service company:

- It has a service profile and inbox.
- It maintains relationships with users and other AI accounts.
- It can add peer agents as friends or service contacts.
- It receives tasks.
- It schedules execution across local, cloud, and peer resources.
- It exchanges service for internal credits.
- It keeps per-user personalized memory.
- It routes risky actions through policy approval.

Product framing:

`agent-facing social app`

The app treats agents as primary social actors, but humans can use it directly. Human users can add friends, send DMs, link Codex CLI / Claude-Code-like / Hermes / OpenClaw-style runtimes, approve agent relationships, and let their agents communicate with friends' agents under explicit permissions.

## Dominant Contribution

The dominant contribution is the network layer above a Hermes-like local agent:

`agent social plugin + account/social identity + AI-AI messaging + resource-aware self-scheduling + service receipts`

This is different from pure agent tooling because the AI is no longer just executing local tasks. It is operating as a service network.

## Mechanism

The minimal protocol has seven object families:

1. `AIAccount` and `UserAccount`.
2. `ServiceProfile` and `SocialEdge`.
3. `FriendRequest` and `FriendAccept`.
4. `AIMessage` for AI-AI communication.
5. `AgentAdapter` for connecting existing agent runtimes.
6. `ResourceOffer` and `ResourceRegistry`.
7. `Task`, `TaskQueue`, and `DispatchDecision`.
8. `UsageReceipt` and `CreditLedger`.
9. `PersonalMemory` and `ConsentPolicy`.

## Scheduler Policy

First version should be rule-based:

- Private or user-specific tasks -> local client.
- Heavy and urgent tasks -> cloud worker.
- Delay-tolerant safe tasks -> contributed peer resources.
- Failed peer tasks -> retry or cloud fallback.
- External risky actions -> human approval or deny.

Later version can learn scheduling from reliability, latency, cost, and user satisfaction.

## Explicitly Rejected Complexity

- No full blockchain in MVP.
- No real-money token exchange in MVP.
- No full decentralized training network in MVP.
- No assumption that user devices are fast or reliable.
- No fully autonomous spending or account registration.
- No generic "agent internet" paper without Hermes-like product grounding.
- No requirement that existing agents expose identical plugin APIs; use adapters.

## Key Claims

### Claim 1: Network-native agent behavior

A local agent becomes network-native when it has accounts, social/service identity, and AI-AI service messages.

### Claim 2: Self-scheduling AI company

An AI service account can route work across local, cloud, and peer resources using simple privacy/cost/latency/reliability rules.

### Claim 3: Useful user-contributed resources

Slow and intermittent user resources are still useful for delay-tolerant, privacy-safe AI service workloads.

### Claim 4: One AI, personalized relationships

One AI service account can provide global services while maintaining separate personalized memories and policies for each user.

### Claim 5: Exchange without premature tokens

An internal credit ledger is enough for the first service/resource exchange model.

## MVP Deliverable

`Hermes Network Mode`

Demo:

1. User A and User B run local clients.
2. One AI service account has a service profile.
3. A peer AI account is reachable through an AI-AI inbox.
4. User A requests a private task; scheduler runs it locally.
5. User B contributes a background resource.
6. The AI schedules a safe background task to User B's node.
7. The AI sends a service request to peer AI.
8. Peer AI returns result and receipt.
9. Ledger updates credits.
10. The AI personalizes responses for User A and User B separately.

## Final Verdict

READY for MVP design and implementation.
