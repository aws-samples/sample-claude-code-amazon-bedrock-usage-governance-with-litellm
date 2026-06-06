# Sample Claude Code through Amazon Bedrock — Usage governance with LiteLLM

The solution to centrally govern, administer, and monitor Claude AI access for engineering teams using **Amazon Bedrock** as the inference backend and **LiteLLM** as the proxy layer.

---

## The Problem

When an enterprise rolls out Claude Code (or any LLM-based developer tool) across a team, three hard problems emerge immediately:

1. **No spend control.** Each developer's usage goes directly to Bedrock. There is no per-user budget, no team cap, and no way to stop runaway spend before the monthly bill arrives.
2. **No visibility.** There is no audit trail for who called what model, how many tokens they used, and what it cost. Finance and security teams cannot answer "who used what?"
3. **No access governance.** Onboarding a new developer requires manually provisioning API keys and model permissions with no tie-in to the company's existing identity management (AWS IAM Identity Center / SSO). Offboarding is equally manual and error-prone.

---

## The Solution

This platform sits between your developers and Bedrock, adding a governance and observability layer without changing how developers use Claude Code or any OpenAI-compatible tool.

```
Developers / Claude Code / Chat App
           │
           ▼
   LiteLLM Proxy (:4000)        ← API key auth, budget enforcement, rate limits
           │
           ▼
   Amazon Bedrock               ← claude-sonnet-4-6 / haiku-4-5 / opus-4-8
           │
           ▼
   CloudWatch Logs              ← Per-user audit trail for every API call
   PostgreSQL (RDS)             ← Spend tracking, user/team state
```

An admin dashboard (Streamlit, port 8501) gives ops/platform teams a GUI for the entire lifecycle. A self-service chat app (Streamlit, port 8502) gives end users a governed Claude Chat interface.

---

## Key Capabilities

### User & Group Management
- Create, view, and delete users with auto-generated API keys
- Bi-directional sync with **AWS IAM Identity Center** — import users and groups, or push changes back
- Assign users to teams; team membership controls model access and shared budget pools

### Budget & Rate Limit Enforcement
- Set per-user and per-team USD budgets (monthly or rolling)
- Set token-per-minute (TPM) and request-per-minute (RPM) limits
- LiteLLM hard-blocks API calls the moment a user hits their limit — no over-spend possible
- **Manual reset only:** admins explicitly reset spend counters; users cannot self-reset
- Every reset is recorded to an immutable Spend Audit History table

### Model Access Control
- Whitelist specific Bedrock models per user or team
- Add new Bedrock inference profiles from the Model Management page without restarting containers
- Defaults are defined in `litellm_config.yaml` so new users automatically get a safe starting configuration

### Observability
- Real-time usage dashboard: spend by user/team, token breakdown, latency
- Per-user CloudWatch log streams (`/litellm/claude-code-usage/user-{user_id}`) for every success and failure event
- Spend Audit History page shows all admin resets with full trail (who reset, when, prior spend, note)

### Claude Chat App (End-User Interface)
- Self-hosted chat UI that authenticates via user API key — users see only their own budget and allowed models
- Web search via DuckDuckGo (tool-use) for real-time information grounding
- File upload support: PDF, DOCX, code files, images, and more
- Budget progress bar and rate-limit indicators so users know their standing at a glance


---

## Architecture

| Component | Tech | Port |
|---|---|---|
| LiteLLM Proxy | Docker (`ghcr.io/berriai/litellm:v1.88.0-rc.1`) | 4000 |
| Admin Dashboard | Streamlit + Python | 8501 |
| Claude Chat App | Streamlit + Python | 8502 |
| Database | PostgreSQL on Amazon RDS | 5432 |
| Audit Logging | Amazon CloudWatch Logs | — |
| Identity Sync | AWS IAM Identity Center | — |

All three services are wired together via `docker-compose.yml`. Bedrock credentials are sourced from the EC2 instance profile — no long-lived AWS keys are needed.

---

## Getting Started

### Prerequisites
- AWS account with Bedrock access in  your target region
- Bedrock inference profiles provisioned for Claude Sonnet 4.6, Haiku 4.5, and Opus 4.8
- PostgreSQL RDS instance (or any Postgres-compatible database)
- EC2 instance (or ECS task) with an IAM role that has Bedrock and IAM Identity Center permissions
- Docker and Docker Compose installed

### Configuration

**1. Update `litellm_config.yaml`** with your Bedrock inference profile ARNs and your RDS connection string.

**2. Update `docker-compose.yml`** environment variables:
```
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/litellm
LITELLM_MASTER_KEY=<your-secret-key>
IDENTITY_STORE_ID=<your-identity-store-id>
AWS_REGION_NAME=<your-region>
```

**3. Set admin credentials** in:
- `litellm-admin-dashboard/.streamlit/secrets.toml`
- `claude-chat-app/.streamlit/secrets.toml`

### Launch

```bash
docker compose up -d
```

- Admin Dashboard: `http://<host>:8501`
- Claude Chat App: `http://<host>:8502`
- LiteLLM API: `http://<host>:4000`

### Developer Setup (Claude Code)

Point Claude Code at the LiteLLM proxy and use the API key generated for the user from the Admin Dashboard:

```bash
claude config set apiBaseUrl http://<host>:4000
claude config set apiKey sk-<user-api-key>
```

---

## Project Structure

```
claude-code-admin/
├── docker-compose.yml               # All three services
├── litellm_config.yaml              # Model list, budget defaults, LiteLLM settings
├── custom_callback.py               # CloudWatch audit logger (per-user log streams)
├── litellm-admin-dashboard/
│   ├── app.py                       # Dashboard home + quick stats
│   ├── auth.py                      # Password-gated admin auth
│   ├── pages/
│   │   ├── 1_User_Management.py     # Add/delete users, sync from Identity Center
│   │   ├── 2_Group_Management.py    # Team creation, user assignment
│   │   ├── 3_Budget_Controls.py     # Per-user / per-team limits, bulk reset
│   │   ├── 4_Usage_Dashboard.py     # Real-time spend analytics
│   │   ├── 5_Model_Management.py    # View and add Bedrock models
│   │   └── 6_Spend_Audit_History.py # Immutable spend reset audit trail
│   └── utils/
│       ├── litellm_client.py        # LiteLLM REST API wrapper
│       ├── identity_center.py       # AWS IAM Identity Center client
│       ├── spend_tracker.py         # Spend reset audit log (Postgres)
│       └── config_loader.py         # litellm_config.yaml reader
└── claude-chat-app/
    ├── app.py                       # Chat UI with web search and file upload
    ├── auth.py                      # API-key-based user auth
    └── utils/
        ├── file_handler.py          # Multi-format file-to-API conversion
        └── chat_config_loader.py    # Model list and budget fetcher
```

---

## Why This Approach

- **No vendor lock-in for the proxy layer.** LiteLLM opensource.
- **Bedrock keeps data in your AWS account.** No prompt data leaves your AWS environment.
- **EC2 instance profile auth.** No AWS access keys are stored in config files or environment variables.
- **Hard budget blocks, not soft alerts.** The proxy refuses requests at the limit — there is no "notify and hope" pattern.
- **Audit trail that survives container restarts.** CloudWatch log streams and Postgres records are external to the container lifecycle.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.