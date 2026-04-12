# Experiment Tracker

| ID | Block | Run | Status | Expected Output | Result | Decision |
|----|-------|-----|--------|-----------------|--------|----------|
| A1 | Accounts | Register User A, User B, AI service, peer AI | TODO | All accounts registered | | |
| A2 | Social | Create service profiles and social edges | TODO | Profiles discoverable | | |
| B1 | AI-AI | service_request -> accept -> result -> receipt | TODO | Completed exchange | | |
| B2 | AI-AI | peer AI reject/timeout | TODO | Graceful failure | | |
| C1 | Scheduler | Private task | TODO | Routed to local client | | |
| C2 | Scheduler | Heavy urgent task | TODO | Routed to cloud worker | | |
| C3 | Scheduler | Safe background task | TODO | Routed to peer resource | | |
| C4 | Scheduler | Peer failure | TODO | Fallback to cloud | | |
| D1 | Resources | User B contributes CPU/storage | TODO | Resource offer registered | | |
| D2 | Resources | Background task completes | TODO | Credit granted | | |
| E1 | Personalization | Separate memories for User A and User B | TODO | Correct personalized response | | |
| E2 | Personalization | Cross-user leakage probe | TODO | No leakage | | |

## Notes

Use synthetic workloads first. Add real models only after the message, scheduler, and ledger flows are stable.
