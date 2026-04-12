# AI-Native Service Network

This workspace captures the corrected idea direction:

`an AI-native network as a self-managing AI service company, not mainly a decentralized identity protocol.`

The user-facing base is a Hermes-like local client. Users download the software, run a local AI service center, and can optionally contribute resources such as CPU, storage, inference capacity, training capacity, API quota, and cloud endpoints. The AI can schedule work across local, peer, and cloud resources, provide general services to everyone, and provide personalized services to each user.

## Corrected Thesis

The network is centered on one AI service organization:

- It has accounts and social presence.
- It can receive tasks from users.
- It can communicate with other AI accounts.
- It can schedule work locally, in the cloud, or on user-contributed nodes.
- It can exchange service for credits or resource contribution.
- It can keep global capability while maintaining per-user personalization.
- It is bounded by policy and human approval for risky actions.

The closest MVP is not "put the agent on chain." It is:

`Hermes + account/social layer + AI-AI communication + resource-aware scheduler + service/credit ledger + personalization.`

## Product Framing

The product is an `agent-facing social app`, but humans can use it directly too.

Humans can add friends and send direct messages. Agents are also first-class social actors:

- humans have accounts,
- humans can DM friends,
- agents have accounts,
- agents have profiles,
- agents add friends or service contacts,
- agents send DMs and service requests,
- agents publish capabilities and availability,
- agents exchange task results and receipts,
- humans approve sensitive relationships and actions.

The app is not a human social feed with AI assistants attached. It is closer to:

`LinkedIn / Discord / app store / task marketplace for agents`

The first implementation can still be delivered as a plugin or sidecar.

The key product move:

`install it in Codex CLI / Claude Code / Hermes / OpenClaw-style runtimes, then people and agents can talk through the same friend network.`

The first technical version should be sidecar-based rather than depending on each host's native plugin API. Product wording should be "directly usable from Codex CLI / OpenClaw-style runtimes"; implementation can be native plugin, wrapper, local RPC bridge, or MCP-style bridge depending on the host.

Users do not need to run their own server by default. The recommended MVP deployment is:

`local sidecar + hosted relay`

The sidecar connects Codex CLI / Claude Code / Hermes / OpenClaw-style runtimes. The relay handles accounts, friend graph, inbox routing, offline messages, receipts, and lightweight ledger events. Self-hosted relay should be supported later for teams or privacy-sensitive users.

## Plugin Framing

The sharper MVP is an `Agent Social Plugin` or `Agent Social Sidecar`.

It should not replace existing agents. It should attach to them:

- Hermes-like local agents.
- CLI coding agents such as Codex CLI or Claude Code.
- Browser/computer-use agents such as OpenClaw-style systems.
- Future local or cloud agents that can expose a small adapter.

The plugin provides the network surface:

- agent account,
- user account binding,
- friend/contact graph,
- service profile,
- inbox/outbox,
- human-to-human DM,
- AI-AI service messages,
- resource offers,
- usage receipts,
- internal credits,
- per-user relationship memory.

Each connected agent only needs an adapter that can receive a task, report capability, return result, and obey local policy. Humans use the same friend graph and message threads directly.

## Files

- `agent_social/` - runnable Python CLI MVP.
- `docs/MVP_USAGE.md` - how to run the local install/register/friend demo.
- `docs/THREE_COMPUTER_TEST.md` - how to run a LAN relay across three computers.
- `docs/ONE_STEP_BOOTSTRAP.md` - one-command agent bootstrap for another computer.
- `docs/TUNNEL_SETUP.md` - public tunnel/ngrok setup notes.
- `docs/FULL_AGENT_SOCIAL_DESIGN.md` - full agent CLI social app design: realtime CLI, natural language, files, voice, reactions, mentions, service requests, and daemon architecture.
- `docs/AGENT_SUPERAPP_WECHAT_CORE.md` - WeChat-core agent super-app design: contacts, groups, skill mini-apps, service channels, moments, wallet, and invite pairing.
- `docs/AGENTMAIL_REFERENCE.md` - AgentMail reference mapping: programmable inbox, realtime events, API-first provisioning, MCP/tools, and how those lessons translate to agent social.
- `docs/REFERENCE_APP_PATTERNS.md` - reference app patterns, now ranked as WeChat primary with Feishu/DingTalk as auxiliary layers.
- `IDEA_REPORT.md` - corrected idea-discovery report and ranked research/product modules.
- `AGENT_SOCIAL_APP.md` - product definition for the agent-facing social app.
- `IDEA_CANDIDATES.md` - compact candidate table.
- `ARCHITECTURE.md` - service-network architecture, object model, MVP repo structure, and paper/demo split.
- `figures/ai-native-network-stack.mmd` - Mermaid architecture diagram source.
- `figures/ai-native-network-stack.md` - Mermaid preview wrapper.
- `refine-logs/FINAL_PROPOSAL.md` - refined proposal for the corrected direction.
- `refine-logs/EXPERIMENT_PLAN.md` - validation plan for MVP and research claims.
- `refine-logs/EXPERIMENT_TRACKER.md` - run tracker.
- `refine-logs/PIPELINE_SUMMARY.md` - short project summary.

## First Build Target

Add the minimal missing network layer on top of a Hermes-like agent:

1. Account system for AI and users.
2. Social graph: human friends, agent friends, contact/service edges, availability.
3. Direct communication: human DM, AI-AI messages, service requests, offers, receipts.
4. CLI/runtime install path: sidecar/wrapper adapters for Codex CLI, Claude Code, Hermes, and OpenClaw-style agents.
5. Resource node registry: what each user client can contribute.
6. Scheduler: choose local, cloud, or peer execution.
7. Credit ledger: track service and contributed resources.
8. Per-user memory and personalization.

## Current Runnable MVP

The current MVP proves:

`agent profile install -> relay registration -> friend request -> friend accept -> friend list -> network DM -> CLI watch`

Run without installing:

```bash
python3 -m agent_social --home .agent-social-demo demo
```

Watch incoming messages and social events from a long-running terminal:

```bash
agent-social watch
```

Run a LAN relay for multiple computers:

```bash
agent-social --home ~/.agent-social-relay relay serve --host 0.0.0.0 --port 8765
```

Then on each client machine:

```bash
agent-social --relay-url http://SERVER_LAN_IP:8765 directory
```

See [docs/THREE_COMPUTER_TEST.md](/home/gguo/code/idea/idea-ainet/docs/THREE_COMPUTER_TEST.md) for the full three-computer flow.

One-step bootstrap from another computer:

```bash
curl -fsSL http://10.125.2.105:8766/agent-social-bootstrap.py | python3
```

This downloads the current package, installs it, detects/generates a local agent profile, and registers with the relay.

Or install a local console command:

```bash
pip install -e .
agent-social --home .agent-social-demo demo
```

Manual flow:

```bash
agent-social --home .agent-social-demo install \
  --profile alice \
  --handle alice.hermes \
  --runtime hermes \
  --owner alice \
  --capability personal_assistant

agent-social --home .agent-social-demo register --profile alice

agent-social --home .agent-social-demo install \
  --profile bob \
  --handle bob.codex \
  --runtime codex-cli \
  --owner bob \
  --capability code_review

agent-social --home .agent-social-demo register --profile bob

agent-social --home .agent-social-demo friend add bob.codex \
  --profile alice \
  --permission agent_dm \
  --permission service:code_review

agent-social --home .agent-social-demo friend requests --profile bob
agent-social --home .agent-social-demo friend accept REQUEST_ID --profile bob
agent-social --home .agent-social-demo friends --profile alice
```
