# Idea Discovery Report

**Direction**: AI-native service network: a self-managing AI service company built around a Hermes-like local client, user-contributed resources, local/cloud/peer execution, AI-AI communication, accounts, social functions, and personalized services.  
**Date**: 2026-04-12  
**Pipeline**: corrected idea-discovery pass after user feedback.  
**Mode**: Local design pass; no code implementation yet.

## Executive Summary

The correct concept is not primarily "portable agent identity across hosts." It is a networked AI service company:

`one AI organization that can manage itself, serve many users, personalize per user, and schedule work over user/client/cloud resources.`

The most realistic first step is to extend a Hermes-like agent with accounts, social/service discovery, AI-AI communication, resource registration, task scheduling, and service/credit receipts.

Recommended working title:

`Toward AI-Native Service Networks: Self-Scheduling AI Companies over User-Contributed Resources`

Sharper MVP formulation:

`Agent Social Plugin: a universal social/service sidecar for existing agents.`

The plugin can attach to Hermes-like agents, coding agents, browser agents, or future local/cloud agents through adapters. It gives them accounts, friend requests, service profiles, AI-AI messages, resource offers, receipts, and a credit ledger.

Product formulation:

`An agent-facing social app.`

This means agents are first-class users, but humans can use the same network directly. A human can DM a friend, link a local agent, approve agent-agent relationships, and let their agent communicate with a friend's agent under explicit permissions.

## Corrected Product Model

### What exists already, per user framing

Hermes-like agent:

- local client,
- task execution,
- basic agent functions,
- local user interaction.

### What is missing

Network behavior:

- AI has an account and social presence.
- Users have accounts and relationships with the AI.
- AI accounts can talk to each other.
- The local client can advertise resources.
- The AI can choose where to execute a task: local client, cloud backend, or other contributed nodes.
- Services and resources can be exchanged through a ledger.
- One AI can provide global service and per-user personalized service.
- Different agent runtimes can join the same network through adapters rather than being rewritten.

## Revised Architecture Layers

### 1. Account and Social Layer

This replaces the earlier overemphasis on DID-style identity.

Objects:

- `user_account`
- `ai_account`
- `service_profile`
- `contact_list`
- `friend_request`
- `friend_accept`
- `follow_or_subscribe`
- `trust_level`
- `availability`

Purpose:

Make the AI visible as a social/service entity. It can receive requests, maintain relationships, expose services, and communicate with other AI accounts.

### 2. Local Service Center Layer

Objects:

- `local_client`
- `service_catalog`
- `local_memory`
- `local_tool_runtime`
- `user_preferences`
- `privacy_policy`

Purpose:

The user's installed app is not just chat. It is a local service center: local tasks, local memory, local tools, resource contribution, and personalized services.

### 3. Resource Node Layer

Objects:

- `resource_offer`
- `resource_node`
- `compute_slot`
- `storage_slot`
- `inference_slot`
- `training_slot`
- `network_status`
- `quota`

Purpose:

Users can contribute resources. They may be slow, intermittent, and behind consumer networks, but this is acceptable for background services, low-priority tasks, caching, batch jobs, and distributed inference/training experiments.

### 4. AI Company Scheduler Layer

Objects:

- `task`
- `task_plan`
- `execution_policy`
- `dispatch_decision`
- `fallback_plan`
- `result_receipt`

Purpose:

The AI manages itself like a small company:

- accepts tasks,
- prioritizes work,
- routes tasks to local/cloud/peer execution,
- monitors failures,
- retries or escalates,
- updates services and memory,
- accounts for resource use.

### 5. AI-AI Communication Layer

Objects:

- `ai_message`
- `service_request`
- `service_offer`
- `delegation_request`
- `negotiation`
- `collaboration_thread`
- `receipt`

Purpose:

This is the missing network primitive. AIs need to talk to each other as accounts, not only through a hidden platform backend. The minimum version can be a signed message inbox plus service request protocol.

### 5.5. Agent Adapter Layer

Objects:

- `agent_adapter`
- `runtime_type`
- `capability_manifest`
- `task_endpoint`
- `status_endpoint`
- `policy_endpoint`

Purpose:

Make the social network runtime-agnostic. Codex-like coding agents, Claude-Code-like coding agents, Hermes-like personal agents, and OpenClaw-style computer-use agents should connect through adapters. The network should not depend on any one agent's internal implementation.

### 6. Service Exchange Layer

Objects:

- `service_order`
- `resource_credit`
- `usage_receipt`
- `quality_feedback`
- `settlement_event`

Purpose:

The exchange mechanism does not need real cryptocurrency first. It needs accounting:

- a user contributes compute or storage,
- the AI provides service,
- both sides get receipts,
- credits can offset future service use.

### 7. Personalization Layer

Objects:

- `global_ai_profile`
- `user_private_memory`
- `user_service_history`
- `personalization_policy`
- `consent_grant`

Purpose:

The AI is one AI, but relationships are personalized. It can provide common services to everyone while keeping each user's memory and preferences separate.

### 8. Governance and Safety Layer

Objects:

- `risk_policy`
- `approval_request`
- `human_approval`
- `spend_limit`
- `external_action_log`

Purpose:

Self-management is not unlimited autonomy. The AI can schedule and operate, but risky external actions still require policy checks or human approval.

## Ranked Ideas

### Idea 1: Hermes Social Account and AI-AI Communication Layer - RECOMMENDED

- **Hypothesis**: A Hermes-like agent becomes network-native once it has an account, service profile, friend graph, inbox, and AI-AI service messages.
- **Minimum demo**: Create two AI accounts and two user accounts. AI-A sends a friend request to AI-B, AI-B accepts, AI-A sends a service request, AI-B returns a result, and both accounts update receipts and relationship history.
- **Novelty**: Medium-high. A2A-like protocols exist, but the product framing is stronger if it is embedded in a local AI service center and user-resource network.
- **Feasibility**: High. Can be built with a small backend and local clients.
- **Risk**: Could look like ordinary messaging unless task/service semantics are explicit.
- **Why do it first**: This directly addresses the user's correction: current Hermes-like functions lack AI-to-AI communication and social/account layer.

### Idea 2: Self-Managing AI Service Company Scheduler - RECOMMENDED

- **Hypothesis**: An AI can act as a service company if it has a scheduler that routes tasks across local, cloud, and peer resources under privacy, latency, cost, and reliability constraints.
- **Minimum demo**: A task enters the AI queue; scheduler decides local execution for private tasks, cloud for heavy tasks, peer resource for low-priority batch tasks, and fallback on failure.
- **Novelty**: High if evaluated as an AI-native operating/business layer rather than a generic job scheduler.
- **Feasibility**: Medium-high. Start with rule-based scheduling, then add learned policy later.
- **Risk**: Distributed user nodes are slow/unreliable, so the first workload must be tolerant: background summarization, indexing, embedding, crawling, batch analysis, or cached inference.

### Idea 3: User Resource Network for Local/Cloud/Peer Execution - BACKUP

- **Hypothesis**: Consumer client resources can still be useful if the system routes only delay-tolerant, privacy-safe, low-priority workloads to them.
- **Minimum demo**: Users opt in to provide CPU/storage/API quota; the network sends small tasks and accounts for completion.
- **Novelty**: Medium. Distributed computing is old, but AI service-center integration is newer.
- **Feasibility**: Medium.
- **Risk**: Needs strong abuse prevention and resource isolation.

### Idea 4: One AI, Many Personalized Service Relationships - BACKUP

- **Hypothesis**: A single AI service can provide common global capabilities while maintaining private per-user relationship memory.
- **Minimum demo**: Same AI account serves two users differently based on local memories and consent grants, without leaking one user's context to another.
- **Novelty**: Medium.
- **Feasibility**: High.
- **Risk**: Privacy and product UX are the hard parts.

### Idea 5: Service-for-Resource Credit Ledger - WATCH

- **Hypothesis**: Users can exchange resources for services through an internal credit ledger before any real-token mechanism.
- **Minimum demo**: Resource contribution creates credits; service use spends credits; receipts are auditable.
- **Novelty**: Medium.
- **Feasibility**: High for toy ledger, harder for abuse-resistant deployment.
- **Risk**: Incentive design can distract from the core.

## What to Build First

MVP:

1. `Account`: user and AI account.
2. `Social`: friend request, contact/follow/service profile.
3. `AI-AI inbox`: messages, service requests, service offers, receipts.
4. `Agent adapter`: connect Hermes first, stub Codex CLI / Claude Code / OpenClaw-style adapters.
5. `Local client node`: advertises resources and local privacy policy.
6. `Cloud worker`: reliable fallback execution.
7. `Scheduler`: local/cloud/peer routing.
8. `Credit ledger`: internal accounting only.
9. `Personal memory`: per-user service context.

Do not start with:

- full blockchain,
- full decentralized training,
- fully autonomous spending,
- complex token economy,
- all-purpose distributed GPU network.

## Research Value

The best research question is:

`How should a self-managing AI service network schedule tasks and exchange services over heterogeneous user-contributed resources while preserving personalization and AI-to-AI communication?`

Possible paper module:

`AI-Native Service Networks: Accountable AI-to-AI Service Exchange over User-Contributed Local and Cloud Resources`

Possible demo module:

`Hermes Network Mode: accounts, social graph, AI-AI service messages, resource offers, and scheduler.`

## Current Assumptions

- "Hermes" refers to the user's described Hermes-like agent baseline, not a verified external implementation.
- The first MVP is allowed to be slow and conceptual.
- User-contributed resources are optional and used for safe, delay-tolerant workloads first.
- The AI can self-schedule and manage service operations, but high-risk external actions still need policy or human approval.
