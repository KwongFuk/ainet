# AI-Native Service Network Stack

Architecture view for a Hermes-like AI service network: accounts, social graph, AI-AI inbox, local service center, user resource registry, scheduler, cloud fallback, and service/credit ledger.

```mermaid
flowchart TB
    userA[User A]
    userB[User B]
    clientA[Local Client A]
    clientB[Local Client B]
    cloud[Cloud Worker]
    peer[Peer AI Account]
    ledger[Credit Ledger]

    subgraph accounts[Account and Social Layer]
        ai[AI Service Account]
        profile[Service Profile]
        graph[Social Graph]
        inbox[AI Inbox]
        ai --> profile
        ai --> graph
        ai --> inbox
    end

    subgraph center[Local Service Center]
        memory[Personal Memory]
        catalog[Service Catalog]
        tools[Local Tools]
    end

    subgraph scheduler[AI Company Scheduler]
        queue[Task Queue]
        policy[Dispatch Policy]
        dispatch[Dispatch Decision]
        queue --> policy
        policy --> dispatch
    end

    subgraph resources[Resource Network]
        offerA[Resource Offer A]
        offerB[Resource Offer B]
        registry[Resource Registry]
        offerA --> registry
        offerB --> registry
    end

    userA --> clientA
    userB --> clientB
    clientA --> memory
    clientA --> offerA
    clientB --> offerB
    clientA --> ai
    clientB --> ai
    ai --> queue
    catalog --> queue
    tools --> queue
    registry --> policy
    dispatch -->|private task| clientA
    dispatch -->|background task| clientB
    dispatch -->|heavy task| cloud
    inbox -->|AI-AI service request| peer
    peer -->|result and receipt| inbox
    clientA -->|usage receipt| ledger
    clientB -->|usage receipt| ledger
    cloud -->|usage receipt| ledger
    peer -->|service receipt| ledger
    ledger -->|credits or service quota| ai

    classDef account fill:#e8f3ff,stroke:#2f6f9f,stroke-width:1px,color:#0b1f33;
    classDef local fill:#edf8ee,stroke:#2c7a3f,stroke-width:1px,color:#103519;
    classDef sched fill:#fff7e6,stroke:#9a6a00,stroke-width:1px,color:#332200;
    classDef exchange fill:#f6f1ff,stroke:#6c4ab6,stroke-width:1px,color:#1f1538;

    class ai,profile,graph,inbox,peer account;
    class clientA,clientB,memory,catalog,tools,userA,userB local;
    class queue,policy,dispatch,offerA,offerB,registry,cloud sched;
    class ledger exchange;
```
