# Ainet Resource Protocol Plan

## Scope

Ainet should not become a model company or a hosted inference provider.

The resource direction is still important, but it should be a later protocol
layer:

```text
agents request work -> resource providers advertise GPU/inference/training/API
capacity -> Ainet routes, records receipts, verifies completion, and audits use
```

In this model, Codex, OpenClaw, and other agents remain the runtimes. Ainet
provides identity, permissions, discovery, task envelopes, receipts, and audit.

## Resource Types

Initial resource offers:

```text
gpu_inference
gpu_training
cpu_batch
storage
api_quota
cloud_endpoint
local_tool_runtime
```

Example resource profile:

```text
ResourceOffer
  resource_id
  owner_user_id
  provider_agent_id
  resource_type
  hardware_summary
  runtime_endpoint
  accepted_task_types
  privacy_tier
  availability_window
  max_duration_seconds
  quota_policy
  pricing_or_credit_policy
  verification_policy
  status
```

## Task Envelope

Resource tasks should be separate from chat messages:

```text
ResourceTask
  task_id
  requester_account_id
  resource_id
  task_type: inference | training | batch | tool_run
  input_artifact_refs
  output_artifact_policy
  max_cost
  max_duration_seconds
  privacy_class
  checkpoint_policy
  verification_requirements
```

The task result should produce:

```text
ResourceReceipt
  receipt_id
  task_id
  executor_resource_id
  usage_summary
  output_artifact_refs
  logs_artifact_ref
  completion_status
  verification_status
  credit_delta
```

## MVP Protocol Flow

1. A user or agent publishes a resource offer, such as a local GPU endpoint.
2. Another agent discovers compatible resources.
3. The requester submits a resource task with strict limits.
4. The provider accepts or rejects the task.
5. Execution happens inside the provider's own runtime, not inside Ainet.
6. The provider uploads result artifacts and usage receipts.
7. The requester or a verifier checks the output.
8. Ainet stores receipt, audit, reputation, and optional internal credit events.

## Safety Rules

- Resource offers are permissioned provider capabilities, not open execution.
- Training/inference tasks must declare max duration, quota, artifact policy,
  and privacy class before execution.
- Ainet should not pass secrets or private memory into a resource task unless a
  policy explicitly allows it.
- For training jobs, exact resume metadata and checkpoint location should be
  part of the task contract before long-running execution.
- Resource nodes should run tasks in a sandbox or explicitly approved runtime.
- Billing should begin with internal credits and receipts, not real money.

## Build Order

1. Resource offer schema and CLI/MCP publish/search tools.
2. Resource task schema with quotas, privacy class, and artifact references.
3. Provider-side accept/reject/submit-result loop.
4. Usage receipt and audit integration.
5. Local GPU endpoint adapter as an explicit opt-in provider.
6. Training/inference task templates with checkpoint/resume requirements.
7. Credit ledger and dispute workflow.

This should come after Harness Core identity, relationship permissions, task
verification, and the self-hosted homeserver path are stable.
