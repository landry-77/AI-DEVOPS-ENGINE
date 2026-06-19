## Architecture Overview

```
Your GitHub Repo ──→ ngrok ──→ Ingestion Gateway (Node.js, port 3000)
                                  │
                                  ▼
                            Redis Queue (Celery)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                             ▼
            Celery Worker                   Celery Beat
                    │                             │
                    ▼                             ▼
          FastAPI Brain (AI Engine)     Django Dashboard (UI)
                    │                      │          │
                    ▼                      ▼          ▼
         Air-Gapped Sandbox           PostgreSQL   Billing Collector
         (Docker, no network)         (ZDR audit)  (pluggable — Stripe,
                    │                                manual, or your own)
                    ▼
         GitHub Contents API
         (direct commit to PR branch)
```

This runs entirely on your machine. No cloud. No monthly bill. Connect any GitHub repo.

## Core Stack

| Component | Technology | Role | Configurable? |
|-----------|-----------|------|---------------|
| Ingestion | Node.js + Express | GitHub webhook receiver, Redis task publisher | — |
| Task Queue | Celery + Redis (Broker) | Async job distribution, beat scheduling | — |
| AI Engine | FastAPI → OpenRouter | Code analysis, patch generation | Model choice via `.env` |
| LLM Provider | OpenRouter (Enterprise ZDR) | GPT-4o-mini / Qwen 2.5 Coder 32B | Swap any OpenRouter model |
| Sandbox | Docker SDK (air-gapped) | Isolated test execution | Pre-baked images (Python, JS) |
| Dashboard | Django 6 + Daphne (ASGI) | UI, billing, audit logs, admin | — |
| CLI | `infra/patch-bot.sh` (bash) | Terminal fix trigger, session token auth | `PATCHBOT_API_URL` in `.patchbot.env` |
| Auth | Django auth.User + GitHub App JWT + API Keys | Session + CLI + machine-to-machine | Your GitHub App ID |
| Billing | Pluggable (Stripe/Manual) + billing-collector | Usage metering, forecasts, alerts, AWS/GCP cost polling | Your gateway, your prices, your rules |
| Cost Data | `billing-collector` (Python) | Polls AWS Cost Explorer, GCP Cloud Billing | `AWS_ACCESS_KEY_ID`, `GCP_SERVICE_ACCOUNT_JSON` |
| Caching/Queue | Redis 7 (Alpine) | Brokering, result backend | — |
| Database | PostgreSQL 15 (Alpine) | Audit trail, billing data | Retention configurable in `.env` |
| Deployment | Docker Compose | Local/on-prem orchestration | Ports, volumes all in compose file |

## Every Deployment is Different — That's the Point

This is **open source**. You fork it, clone it, and configure it for YOUR stack.

```bash
git clone https://github.com/landry-77/AI-DEVOPS-ENGINE.git
cd ai-devops-engine

# Everything lives in one env file:
cp .env.example .env
# ┌───────────────────────────────────────────────────────────┐
# │ OPENROUTER_API_KEY      ← your AI provider               │
# │ SLACK_ALERTS_WEBHOOK    ← crash alert channel            │
# │ SLACK_ANALYSIS_WEBHOOK  ← analysis result channel        │
# │ GITHUB_APP_ID           ← your GitHub App installation   │
# │ PAYMENT_GATEWAY         ← stripe / manual / your own     │
# │ STRIPE_SECRET_KEY       ← your billing (your prices)     │
# │ EMAIL_BACKEND           ← sendgrid / smtp / console      │
# │ OPENROUTER_MODEL        ← pick your AI model             │
# │ AUDIT_RETENTION_DAYS    ← your compliance policy         │
# └───────────────────────────────────────────────────────────┘

# Build sandbox images
docker build -t local-pytest-sandbox -f sandbox-env/Dockerfile.python sandbox-env/
docker build -t local-jest-sandbox -f sandbox-env/Dockerfile.javascript sandbox-env/

# Start everything
docker compose up -d

# Expose webhook endpoint (free ngrok tier works)
ngrok http localhost:3000
# → Set ANY GitHub repo's webhook to https://<your-ngrok>.ngrok-free.dev/webhooks/github
```

**You control:** which repos it watches, which AI model it uses, what you charge, how long you keep data, which Slack channels get alerts (separate channels for analysis vs crashes), which branches trigger deployments, who has admin access.

---

## Key Technical Decisions

### 1. Zero-Data-Retention AI Pipeline

```
Inference payload:
  "data_collection": "deny"    ← hardcoded, not config-dependent
```

- **Every** LLM request sends `data_collection: deny` to OpenRouter — your code cannot be used for training
- Source code processed in `/tmp/{project_id}`, wiped in `finally` block — never touches disk at rest
- `RunAuditLog` stores **metadata only** (timestamps, project_id, status) — no patched_code, no reasoning, no source
- Secret scrubbing via `scrubber.py` removes PATs (`ghp_*`, `github_pat_*`), API keys, tokens, and base64-encoded credentials before AI analysis — regex-based sanitization runs on the code string in memory
- Retention configured via `AUDIT_RETENTION_DAYS` in `.env` — you decide compliance window

### 2. Air-Gapped Sandbox Execution

```python
container = docker_client.containers.create(
    image="local-pytest-sandbox",
    network_mode="none",      # zero network access
    mem_limit="512m",         # resource capped
    nano_cpus=2000000000,     # 2 CPU cores max
)
```

- Pre-baked Docker images (`local-pytest-sandbox`, `local-jest-sandbox`) — zero runtime installs
- Files injected via `put_archive()` tar streams — no `COPY`, no `VOLUME`, no filesystem traces
- Network completely disabled — no data exfiltration, no phone-home
- Container removed post-execution — no persistence
- **You can build your own sandbox images** for any language/runtime

### 3. PR Automation

```
GitHub PR (opened) ──→ Ingestion ──→ AI analysis ──→ Auto-commit fix
                                                        │
                                                        ▼
                                              Slack notification
                                                        │
                                                        ▼
                                              Dashboard entry created
```

- Only `opened` events trigger analysis (no `synchronize` — prevents infinite re-trigger loops)
- Auto-commit via **GitHub Contents API** (`PUT /repos/{owner}/{repo}/contents/{path}`) — replaces entire file, no append
- ` ```suggestion` blocks **not used** — they can only replace single lines, not entire files
- Deployment pipeline on push to default branch (`[skip deploy]` escape hatch available)
- Works with **any GitHub repo** you configure — yours, your client's, your org's
- On push to default branch, deployment pipeline auto-triggers (`[skip deploy]` in commit message to skip)
- Supports 4 strategies: Docker, Kubernetes, Serverless, Custom Script

### 4. Billing — Your Prices, Your Plans, Your Rules

```
Payment Gateway ──→ BillingRecord (PostgreSQL)
  (Stripe,             │
   Manual,             ▼
   or your own) ┌───────────────┐
               │ Daily: collect │
               │ Monthly: predict│
               │ Hourly: anomaly │
               └───────────────┘
                       │
                       ▼
               Dashboard ──→ Spend, forecasts, anomaly alerts
```

Billing is fully **pluggable**. The `PaymentBackend` ABC defines two methods:

```python
class PaymentBackend(ABC):
    @abstractmethod
    def create_checkout_session(self, customer_email, organization_name, ...) -> dict:
        ...
    @abstractmethod
    def handle_webhook(self, payload, signature) -> dict:
        ...
```

**Built-in backends:**

| Backend | When to use |
|---------|-------------|
| `stripe` | SaaS subscriptions, Stripe Checkout, webhook events |
| `manual` | Enterprise invoicing, internal cost tracking, no payment processing |

**Bring your own** — implement the ABC, add it to `payment_backends.py`, set `PAYMENT_GATEWAY=your_backend`.

You configure **everything**:

| Variable | Where | What it controls |
|----------|-------|-----------------|
| `PAYMENT_GATEWAY` | `.env` | Which backend to use (stripe/manual) |
| `STRIPE_SECRET_KEY` | `.env` | Your Stripe account (if stripe) |
| `STRIPE_ENTERPRISE_PRICE_ID` | `.env` | Your price point |
| `STRIPE_SUCCESS_URL` | `.env` | Your checkout flow |
| `COLLECT_INTERVAL_SECONDS` | docker-compose | Your billing cadence |
| Billing models | Django admin | Create your own plans, tiers, metering |

**Use cases:**
- SaaS startup: charge per seat, per repo, or per analysis via Stripe
- Consultancy: bill clients per deployment via manual invoices
- Internal tool: track costs per team for chargeback (no payment gateway needed)

### 5. Email — Pluggable Delivery Backend

Email delivery uses a pluggable `EmailBackend` ABC:

```python
class EmailBackend(ABC):
    def send(self, to_email, subject, html_content, from_email=None, from_name=None) -> bool
```

**Built-in backends:**

| Backend | Config Value | When to use |
|---------|-------------|-------------|
| SendGrid | `sendgrid` | Production — reliable API-based delivery, 100 emails/day free |
| SMTP | `smtp` | Any SMTP server — Gmail, Mailgun, SendGrid SMTP, Postmark |
| Console | `console` | Development — prints to stdout (default) |
| Log | `log` | Development — Python logger output |

**Bring your own** — implement the ABC, add it to `email_backends.py`, set `EMAIL_BACKEND=your_backend`.

**Config via `.env`:**
```
EMAIL_BACKEND=sendgrid|smtp|console|log
SENDGRID_API_KEY=SG.xxx...           # for sendgrid
EMAIL_SMTP_HOST=smtp.gmail.com       # for smtp
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=your@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password
EMAIL_FROM_ADDRESS=billing@yourstartupdomain.com
EMAIL_FROM_NAME=AI DevOps Billing
```

### 6. CLI Tool — Developer Terminal Integration

The `patch-bot` CLI lets developers trigger fixes from their terminal without opening a PR:

```bash
patch-bot myfile.py "fix the null pointer exception on line 42"
```

**Install (one-time):**
```bash
# Option A — download from repo (any machine)
curl -o /usr/local/bin/patch-bot https://raw.githubusercontent.com/hirwalandry/ai-devops-engine/main/infra/patch-bot.sh
chmod +x /usr/local/bin/patch-bot

# Option B — from cloned repo
cp infra/patch-bot.sh /usr/local/bin/patch-bot

# Option C — self-install (if already in PATH)
patch-bot --install
```

**Auth flow (no PATs):**
1. Set the server URL: `export PATCHBOT_API_URL=https://your-server.com`
2. `patch-bot --auth` opens browser to install GitHub App on your org
3. After installation, a short-lived session token is displayed
4. `patch-bot --set-token <token>` saves it locally to `~/.config/patchbot/session`
5. Token is hashed and stored server-side — revocable at any time

**Alternative:** Generate API keys from the dashboard (`/dashboard/developer-tokens/`) for CI/CD pipelines.

### 7. Crash Alerting & Telemetry

The `EnterpriseTaskFailureMonitor` base class catches every Celery task failure:

```
Task failure → RunAuditLog (FAILED status) → Slack alert (SLACK_ALERTS_WEBHOOK_URL)
```

Two independent Slack webhooks:
| Webhook | Sent by | When |
|---------|---------|------|
| `SLACK_ALERTS_WEBHOOK_URL` | celery-worker | Task failures, system crashes |
| `SLACK_ANALYSIS_WEBHOOK_URL` | fastapi-brain | AI analysis completed, fix committed |

### 8. Incident Response & MTTR Reduction

US engineering leaders measure everything in **MTTR** (Mean Time to Resolve). This system directly attacks that metric:

```
Bug filed ──→ AI analyzes in 20s ──→ Patch generated ──→ Sandbox tested ──→ PR committed
        ▲                                                                           │
        │                                                                           ▼
        └────────────────────── Slack alert (analysis + fix committed) ──────────────┘
```

**What happens when a production bug is reported:**
1. Developer files an issue (or the on-call engineer opens one)
2. Issue webhook triggers the AI pipeline — no pager needed for routine fixes
3. AI reads the code, generates a patch, runs it in the air-gapped sandbox
4. If tests pass, the fix is committed to a branch and a PR is opened
5. Slack alert fires to `SLACK_ANALYSIS_WEBHOOK_URL` — "Bug #142 fixed, PR #203 ready for review"
6. On-call engineer reviews (30 seconds) and merges

**MTTR reduction by scenario:**

| Scenario | Without system | With system | Savings |
|----------|---------------|-------------|---------|
| Runtime bug (null pointer, off-by-one) | 2–4 hours (triage + fix + test + PR) | 20–60 seconds (AI generates + tests + commits) | **99%+** |
| Test failure after merge | 1–2 hours (revert + fix + re-deploy) | Prevented before merge | **100%** |
| Dependency bump / deprecation | 30 min (manual search + replace) | `patch-bot` CLI, 10 seconds | **98%** |
| On-call after-hours incident | Pager wakes engineer at 3 AM | AI fixes before pager fires | **100% for auto-fixable** |

**For the alerts that can't be auto-fixed** (architecture changes, design decisions), the system still captures the failure, logs it to the audit trail, and alerts Slack — cutting triage time in half by providing the root-cause analysis upfront.

### 9. Admin & Multi-Tenant Controls

- `AdminDashboardView` (`/dashboard/admin/`) — manage users, activate/deactivate, delete
- `PostgreSQLTenantIsolationMiddleware` — auto-scopes data per `organization_name`
- `TenantManager.for_tenant()` — application-level tenant isolation on every model query
- `AuditLogEntry` — SOC 2-compatible audit trail (actor, action, resource, IP, timestamp)
- Each org sees only their own data — built-in multi-tenant by default

---

## Security Boundary

```
                       ┌──────────────────────────┐
                       │     YOUR Machine          │
                       │  ┌────────────────────┐  │
                       │  │  Docker Compose     │  │
                       │  │  ┌────────────┐    │  │
Your GitHub ◄──ngrok──►│  │  │ Ingestion  │    │  │
  (any repo)            │  │  │ (port 3000)│    │  │
                       │  │  └──────┬─────┘    │  │
                       │  │         ▼          │  │
                       │  │  ┌────────────┐    │  │
                       │  │  │   Redis    │    │  │
                       │  │  └──────┬─────┘    │  │
                       │  │         ▼          │  │
                       │  │  ┌────────────┐    │  │
                       │  │  │  Celery    │    │  │
                       │  │  └──────┬─────┘    │  │
                       │  │         │          │  │
                       │  │  ┌──────▼──────┐   │  │
                       │  │  │ FastAPI Brain│   │  │
                       │  │  └──┬──────┬───┘   │  │
                       │  │     │      │       │  │
                       │  │     ▼      ▼       │  │
                       │  │  Sandbox  OpenRouter│  │
                       │  │ (no net)  (ZDR)    │  │
                       │  └────────────────────┘  │
                       └──────────────────────────┘
```

**No cloud dependency. Your code never leaves your machine except for AI inference (and that's contractually barred from training via `data_collection: deny`).**

## Cost Analysis (Self-Hosted)

| Item | Cost | Note |
|------|------|------|
| Docker Desktop | Free | — |
| ngrok (free tier) | $0 | 40 connections/min limit |
| OpenRouter API | ~$0.50/1M tokens | GPT-4o-mini pricing |
| GitHub App | $0 | — |
| Payment gateway (Stripe, etc.) | Varies | Only if you process payments |
| Electricity | ~$0.10/hr | Laptop-level draw |
| **Total per 1000 analyses** | **~$2.00** | — |

Compare: GitHub Copilot ($19/user/mo × 5 = $95/mo) plus CI/CD minutes, plus cloud monitoring — before any automated QA.

## Deploy on US Cloud Providers

The stack is Docker Compose — it runs anywhere Docker runs. US engineering teams can deploy to any major cloud in minutes:

### AWS (ECS Fargate + ElastiCache + RDS)

```bash
# Use the AWS-ready compose override
docker compose -f docker-compose.yml -f docker-compose.web.yml up -d

# What you get:
# ┌─────────────────────────────────────────────────────────┐
# │  node-ingestion  → ALB (port 3000, webhook endpoint)    │
# │  django-dashboard → ALB (port 8000, team UI)            │
# │  celery-worker   → ECS service (auto-scaling)           │
# │  core-brain      → ECS service (GPU optional)           │
# │  redis           → ElastiCache (Redis 7)                │
# │  postgres        → RDS (PostgreSQL 15, Multi-AZ)        │
# │  caddy-proxy     → ALB (TLS termination via Caddy)      │
# └─────────────────────────────────────────────────────────┘
```

**Estimated monthly burn on AWS (us-east-1):** $60–120 for a production deployment handling 1,000+ analyses/month. Fargate spot instances cut that in half.

### GCP (Cloud Run + Memorystore + Cloud SQL)

Each stateless service (`node-ingestion`, `django-dashboard`, `celery-worker`, `core-brain`) deploys as a Cloud Run service — auto-scaling to zero when idle. Redis → Memorystore, PostgreSQL → Cloud SQL.

**Estimated monthly burn:** $50–100, mostly Cloud SQL minimum.

### Azure (Container Apps + Cache for Redis + Flexible Server)

Azure Container Apps with KEDA auto-scaling based on Celery queue depth. Zero infra management.

**Estimated monthly burn:** $70–120.

### DigitalOcean (App Platform + Managed DB)

Simplest path for SMBs. One-click deploy from the Docker Compose file via the App Platform.

**Estimated monthly burn:** $30–60.

---

## What You Ship vs What You Own

| You Ship (open source) | You Own (configurable) |
|------------------------|----------------------|
| The pipeline code | Which repos it watches |
| Docker Compose setup | Which AI model it uses |
| Webhook handler | What you charge customers |
| Dashboard UI | How long data is retained |
| CLI tool (`patch-bot`) | Which server it points to |
| Email templates | Which email service (SendGrid / SMTP / console) |
| Slack integration | Which Slack channels (analysis vs alerts) |
| Payment abstraction | Which payment gateway (Stripe / manual / your own) |
| Billing telemetry & AWS/GCP cost collector | Your cloud provider keys, your prices & plans |
| Admin dashboard | Who has admin access, user activation/deletion |
| Multi-tenant isolation | Which orgs have access |

**Fork it. Point it at your repos. Set your prices. Ship code, not incidents.**

---

[GitHub Repository](https://github.com/landry-77/AI-DEVOPS-ENGINE.git)
