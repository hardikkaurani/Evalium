<div align="center">

<h1>Evalium.</h1>

<p><strong>Evalium — Production-grade AI Evaluation Infrastructure.<br/>G-Eval, LLM-as-a-Judge, RAG evaluation, and fully customisable AI evaluation pipelines. Built in public. Designed for production.</strong></p>

<br/>

<a href="https://eval-forge-sandy.vercel.app"><img src="https://img.shields.io/badge/Live%20Demo-eval--forge--sandy.vercel.app-blueviolet?logo=vercel&logoColor=white" height="28" /></a>
&nbsp;
<a href="#getting-started"><img src="https://img.shields.io/badge/Quick%20Start-Docker-2496ED?logo=docker&logoColor=white" height="28" /></a>
&nbsp;
<a href="docs/api.md"><img src="https://img.shields.io/badge/API%20Docs-OpenAPI-85EA2D?logo=swagger&logoColor=black" height="28" /></a>
&nbsp;
<a href="ROADMAP.md"><img src="https://img.shields.io/badge/Roadmap-12%20Phases-FF6B6B" height="28" /></a>

<img src="docs/assets/demo.gif" alt="Evalium" width="700" style="border-radius: 14px;" />

---

<img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white" />
<img src="https://img.shields.io/badge/React-Frontend-61DAFB?logo=react&logoColor=black" />
<img src="https://img.shields.io/badge/TypeScript-Typed-3178C6?logo=typescript&logoColor=white" />
<img src="https://img.shields.io/badge/PostgreSQL-Database-336791?logo=postgresql&logoColor=white" />
<img src="https://img.shields.io/badge/Redis-Queue-DC382D?logo=redis&logoColor=white" />
<img src="https://img.shields.io/badge/Celery-Workers-37814A?logo=celery&logoColor=white" />
<img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-blue.svg" />
<img src="https://img.shields.io/badge/Status-v1.0.0%20Released-22c55e" />
<img src="https://img.shields.io/github/stars/hardikkaurani/Evalium?style=social" />

<br/><br/>

</div>

---

## Table of Contents

- [Overview](#overview)
- [Why Evalium](#why-evalium)
- [System Architecture](#system-architecture)
- [Database Schema](#database-schema)
- [Evaluation Engine Design](#evaluation-engine-design)
- [Evaluation Job Lifecycle](#evaluation-job-lifecycle)
- [G-Eval Scoring Pipeline](#g-eval-scoring-pipeline)
- [RAG Evaluation Pipeline](#rag-evaluation-pipeline)
- [CI/CD Integration Flow](#cicd-integration-flow)
- [Run State Machine](#run-state-machine)
- [SaaS and Multi-Tenancy Architecture](#saas-and-multi-tenancy-architecture)
- [Security Model](#security-model)
- [12-Phase Build Roadmap](#12-phase-build-roadmap)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Environment Configuration](#environment-configuration)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Error Handling](#error-handling)
- [Observability](#observability)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Evalium is a self-hosted, developer-first LLM evaluation platform built for AI engineers, product teams, and researchers who need rigorous, reproducible benchmarking of language model outputs. It replaces ad-hoc evaluation scripts and spreadsheets with a structured platform featuring automated pipelines, a real-time dashboard, a public API, and a judge abstraction layer that unifies G-Eval, DeepEval, AlpacaEval, and custom LLM-as-a-Judge configurations under a single interface.

The core insight behind Evalium is that LLM evaluation has the same requirements as software testing — it needs to be automated, versioned, reproducible, and integrated into the development workflow. Most teams evaluate LLMs manually before a release, if at all. Evalium makes evaluation a first-class, continuous process triggered on every model change, prompt change, or data change — the same way unit tests run on every commit.

Key design decisions:

- **Async-first backend**: FastAPI with async SQLAlchemy ensures evaluation jobs — which can involve hundreds of LLM inference calls per dataset — never block the API layer. All long-running work is dispatched to background Celery workers via Redis queues with priority support and dead-letter handling.
- **Decoupled judge abstraction**: The `JudgeBase` abstract class sits between the evaluation pipeline and any specific framework. Swapping from G-Eval to a custom judge requires changing one configuration field, not touching any pipeline code.
- **Immutable dataset versioning**: Every dataset upload creates an immutable version snapshot. Evaluation runs are pinned to a specific version, ensuring results are reproducible even as ground truth evolves over time.
- **Self-hostable with one command**: `docker compose up --build -d` spins up the full stack — FastAPI, React frontend, PostgreSQL, Redis, Celery workers — with no external service dependencies.
- **CI/CD ready by design**: The REST API is the primary interface. Triggering an evaluation run, polling for completion, and fetching results are all achievable with standard HTTP calls, making GitHub Actions or GitLab CI integration trivial.
- **SaaS-ready architecture**: Organisation-level tenancy, team-scoped API keys, usage metering hooks, and subscription plan enforcement are designed into the data model from Phase 1, not retrofitted later.

---

## Why Evalium

| Comparison        | Ad-hoc scripts      | Commercial eval platforms | Evalium                                                 |
| ----------------- | ------------------- | ------------------------- | ------------------------------------------------------- |
| Reproducibility   | No versioning       | Vendor-controlled         | Immutable dataset versions, run snapshots               |
| Judge flexibility | Single method       | Fixed metric sets         | G-Eval, DeepEval, AlpacaEval, custom — same interface   |
| CI/CD integration | Manual copy-paste   | Often paywalled           | REST API first, GitHub Actions examples included        |
| Data privacy      | Scripts run locally | Data sent to vendor       | 100% self-hosted, no external calls required            |
| Cost              | Engineering time    | Per-evaluation pricing    | Open source, infra cost only                            |
| Observability     | Print statements    | Vendor dashboard          | Prometheus metrics, Grafana dashboards, structured logs |
| Multi-tenancy     | Not applicable      | Usually included          | Orgs, teams, usage limits — built into Phase 11         |

---

## System Architecture

The complete component topology of Evalium — from browser and CI clients through the API, evaluation engine, background workers, and data layer.

```mermaid
graph TB
    subgraph Clients [Client Layer]
        BROWSER[Browser Client]
        GHA[GitHub Actions]
        GITLAB[GitLab CI]
        SDK[Python SDK or REST Client]
    end

    subgraph FE [Frontend - React 18 + Vite + TypeScript]
        SPA[Single Page Application]
        AUTH_UI[Auth Pages - Login and Register]
        DASH[Dashboard - Runs and Metrics]
        PROJ[Projects and Datasets]
        LEADERBOARD[Leaderboard]
        COMPARE[Side-by-side Compare]
        SPA --> AUTH_UI
        SPA --> DASH
        SPA --> PROJ
        SPA --> LEADERBOARD
        SPA --> COMPARE
    end

    subgraph API [Backend API - FastAPI - Python 3.12 - port 8000]
        GW[API Gateway]
        RATE[Rate Limiter]
        AUTH_MW[JWT Middleware]
        RBAC[RBAC Middleware]
        ROUTER[Versioned Router v1]
        CTRL[Controllers]
        SVC[Service Layer]
        GW --> RATE --> AUTH_MW --> RBAC --> ROUTER --> CTRL --> SVC
    end

    subgraph Engine [Evaluation Engine]
        JUDGE_BASE[JudgeBase Interface]
        GEVAL[G-Eval]
        DEEPEVAL[DeepEval]
        ALPACA[AlpacaEval]
        CUSTOM[Custom Prompt Template]
        PAIRWISE[Pairwise Comparator]
        JUDGE_BASE --> GEVAL
        JUDGE_BASE --> DEEPEVAL
        JUDGE_BASE --> ALPACA
        JUDGE_BASE --> CUSTOM
        JUDGE_BASE --> PAIRWISE
    end

    subgraph Workers [Celery Workers]
        QUEUE[Redis Task Queue]
        W1[Worker Instance 1]
        W2[Worker Instance 2]
        WN[Worker Instance N]
        QUEUE --> W1
        QUEUE --> W2
        QUEUE --> WN
    end

    subgraph Data [Data Layer]
        PG[(PostgreSQL)]
        REDIS_CACHE[(Redis - Cache and Queue)]
        FILE_STORE[File Storage - Datasets]
    end

    subgraph Obs [Observability]
        PROM[Prometheus]
        GRAF[Grafana]
        LOGS[Structlog - JSON Logs]
        PROM --> GRAF
    end

    BROWSER --> SPA
    GHA -->|REST| GW
    GITLAB -->|REST| GW
    SDK -->|REST| GW
    SPA -->|REST| GW

    SVC -->|Dispatch| QUEUE
    W1 --> JUDGE_BASE
    W2 --> JUDGE_BASE
    WN --> JUDGE_BASE

    SVC --> PG
    SVC --> REDIS_CACHE
    W1 --> PG
    W2 --> PG
    JUDGE_BASE --> LOGS
    API --> PROM
    Workers --> PROM
```

---

## Database Schema

The core relational model behind Evalium. All tables use UUID primary keys. Evaluation runs are immutably linked to a specific dataset version, ensuring past results remain reproducible.

```mermaid
erDiagram
    Organisation {
        uuid id PK
        string name
        string slug UK
        string plan
        int monthly_run_limit
        timestamp created_at
    }

    Team {
        uuid id PK
        uuid org_id FK
        string name
        timestamp created_at
    }

    User {
        uuid id PK
        uuid org_id FK
        uuid team_id FK
        string email UK
        string password_hash
        string role
        timestamp created_at
    }

    APIKey {
        uuid id PK
        uuid user_id FK
        string key_hash UK
        string scope
        int request_count
        timestamp last_used_at
        timestamp expires_at
    }

    Project {
        uuid id PK
        uuid org_id FK
        string name
        string description
        timestamp created_at
    }

    Dataset {
        uuid id PK
        uuid project_id FK
        string name
        int version
        string format
        string storage_path
        int row_count
        timestamp created_at
    }

    Run {
        uuid id PK
        uuid project_id FK
        uuid dataset_id FK
        uuid created_by FK
        string judge
        string metrics
        string status
        float aggregate_score
        int total_cases
        int completed_cases
        timestamp started_at
        timestamp completed_at
    }

    TestCaseResult {
        uuid id PK
        uuid run_id FK
        int case_index
        text model_output
        text reference
        string metric
        float score
        text reasoning
        timestamp evaluated_at
    }

    Organisation ||--o{ Team : "has"
    Organisation ||--o{ User : "has"
    Organisation ||--o{ Project : "owns"
    Team ||--o{ User : "contains"
    User ||--o{ APIKey : "has"
    User ||--o{ Run : "creates"
    Project ||--o{ Dataset : "contains"
    Project ||--o{ Run : "has"
    Dataset ||--o{ Run : "used in"
    Run ||--o{ TestCaseResult : "produces"
```

---

## Evaluation Engine Design

The judge abstraction layer is the architectural core of Evalium. Every metric — regardless of which framework computes it — flows through the same `JudgeBase` interface. This means evaluation pipelines are stable even as the underlying judge implementation changes or new frameworks are added.

```mermaid
flowchart TD
    INPUT([Evaluation Request\nmodel output plus reference plus criteria plus metric]) --> VALIDATE[Validate input schema\nPydantic v2]

    VALIDATE --> TEMPLATE[Load Jinja2 Prompt Template\nfor metric and judge combination]
    TEMPLATE --> REGISTRY{Metric Registry\nlookup judge for metric}

    REGISTRY -->|coherence, relevance, correctness, fluency| GEVAL[G-Eval\nChain-of-Thought scoring]
    REGISTRY -->|faithfulness, hallucination, toxicity, answer relevancy| DEEPEVAL[DeepEval\nspecialised modules]
    REGISTRY -->|instruction following winrate| ALPACA[AlpacaEval\npairwise winrate]
    REGISTRY -->|user-defined rubric| CUSTOM[Custom LLM Judge\nJinja2 prompt template]
    REGISTRY -->|A vs B model comparison| PAIRWISE[Pairwise Comparator\nbracket tournament or ELO]

    GEVAL --> RAW[Raw Judge Response\nJSON with score and reasoning]
    DEEPEVAL --> RAW
    ALPACA --> RAW
    CUSTOM --> RAW
    PAIRWISE --> RAW

    RAW --> PARSE[Parse and validate response\nextract score and chain-of-thought]
    PARSE --> NORMALISE[Normalise to 0.0 to 1.0\nper-metric calibration]
    NORMALISE --> STORE[(INSERT TestCaseResult\nPostgreSQL)]
    STORE --> AGGREGATE[Aggregate across N test cases\nmean, median, p10, p90]
    AGGREGATE --> UPDATE[(UPDATE Run aggregate_score\nand status)]
    UPDATE --> BROADCAST[Broadcast progress\nWebSocket or SSE]
    BROADCAST --> DASH([Live dashboard update])
```

---

## Evaluation Job Lifecycle

The complete sequence of events from the moment a user submits an evaluation job to the moment results are available on the dashboard — including error recovery and cancellation paths.

```mermaid
sequenceDiagram
    actor User
    participant API as FastAPI Backend
    participant Auth as JWT and RBAC
    participant Limit as Rate and Plan Limiter
    participant SVC as Evaluation Service
    participant DB as PostgreSQL
    participant QUEUE as Redis Queue
    participant WORKER as Celery Worker
    participant JUDGE as Judge Layer
    participant LLM as External Judge LLM
    participant WS as WebSocket Channel

    User->>API: POST /api/v1/runs with dataset_id, judge, metrics, config
    API->>Auth: Verify Bearer token
    Auth-->>API: userId and orgId confirmed

    API->>Limit: Check plan run limit for org
    Limit-->>API: Within limit

    API->>DB: Fetch dataset version and row count
    DB-->>API: Dataset metadata confirmed

    API->>DB: INSERT Run with status PENDING
    DB-->>API: run_id returned

    API->>QUEUE: Enqueue job payload with run_id and priority
    API-->>User: 202 Accepted with run_id and polling URL

    QUEUE->>WORKER: Dequeue job
    WORKER->>DB: UPDATE Run status to RUNNING, set started_at

    loop For each test case 1 to N
        WORKER->>JUDGE: evaluate(output, reference, metric, config)
        JUDGE->>LLM: POST formatted judge prompt
        LLM-->>JUDGE: Raw response with score and reasoning

        alt LLM returns valid response
            JUDGE-->>WORKER: Normalised score and chain-of-thought
            WORKER->>DB: INSERT TestCaseResult
            WORKER->>DB: UPDATE Run completed_cases counter
            WORKER->>WS: Broadcast progress percentage
        else LLM timeout or malformed response
            WORKER->>WORKER: Retry up to 3 times with backoff
            WORKER->>DB: Mark test case as FAILED with error detail
        end
    end

    WORKER->>DB: Compute aggregate score, p10, p90, mean, median
    WORKER->>DB: UPDATE Run status to COMPLETED
    WORKER->>WS: Broadcast COMPLETED event with summary

    User->>API: GET /api/v1/runs/run_id
    API->>DB: Fetch run with all TestCaseResults
    DB-->>API: Full result set
    API-->>User: 200 with scores, reasoning, aggregate metrics, breakdown
```

---

## G-Eval Scoring Pipeline

A deep look at how G-Eval specifically works inside Evalium — the chain-of-thought generation step, the step-level scoring, and how the final metric score is derived.

```mermaid
flowchart TD
    INPUT([Test Case\noutput plus reference plus metric name]) --> COT_PROMPT[Build Chain-of-Thought Prompt\nAsk LLM to generate evaluation steps]

    COT_PROMPT --> LLM1[LLM Call 1\nGenerate evaluation steps]
    LLM1 --> STEPS[Ordered list of evaluation steps\ne.g. Check factual accuracy then Check coherence]

    STEPS --> SCORE_PROMPT[Build Scoring Prompt\nInject steps plus output plus reference]
    SCORE_PROMPT --> LLM2[LLM Call 2\nScore each step 1 to 5]

    LLM2 --> STEP_SCORES[Per-step scores\nstep 1 score 4, step 2 score 5, step 3 score 3]

    STEP_SCORES --> WEIGHTED[Apply step weights\nuser-configurable or uniform]
    WEIGHTED --> AGGREGATE[Weighted average]
    AGGREGATE --> NORMALISE[Normalise to 0.0 to 1.0]
    NORMALISE --> STORE[(Store score plus all step reasoning\nin TestCaseResult)]
```

---

## RAG Evaluation Pipeline

How Evalium evaluates Retrieval-Augmented Generation systems — covering retrieval quality and generation quality as separate, independently scored dimensions.

```mermaid
flowchart TD
    RAG_INPUT([RAG Test Case\nquery plus retrieved chunks plus generated answer plus ground truth]) --> SPLIT{Split into\ntwo evaluation tracks}

    SPLIT --> RETRIEVAL_TRACK[Retrieval Quality Track]
    SPLIT --> GENERATION_TRACK[Generation Quality Track]

    subgraph Retrieval [Retrieval Evaluation]
        RETRIEVAL_TRACK --> CTX_PREC[Contextual Precision\nAre retrieved chunks relevant to the query?]
        RETRIEVAL_TRACK --> CTX_RECALL[Contextual Recall\nDo retrieved chunks cover the ground truth?]
        RETRIEVAL_TRACK --> CTX_REL[Context Relevancy\nSignal to noise ratio of retrieved set]
    end

    subgraph Generation [Generation Evaluation]
        GENERATION_TRACK --> FAITHFUL[Faithfulness\nIs the answer grounded in retrieved chunks?]
        GENERATION_TRACK --> ANSWER_REL[Answer Relevancy\nDoes the answer address the original query?]
        GENERATION_TRACK --> HALLUCINATION[Hallucination Check\nDoes the answer introduce unsupported claims?]
    end

    CTX_PREC --> RETRIEVAL_SCORE[Retrieval Score - weighted mean]
    CTX_RECALL --> RETRIEVAL_SCORE
    CTX_REL --> RETRIEVAL_SCORE

    FAITHFUL --> GENERATION_SCORE[Generation Score - weighted mean]
    ANSWER_REL --> GENERATION_SCORE
    HALLUCINATION --> GENERATION_SCORE

    RETRIEVAL_SCORE --> FINAL[Combined RAG Score\nuser-configurable retrieval vs generation weight]
    GENERATION_SCORE --> FINAL
    FINAL --> STORE[(Store dimension scores\nand combined score)]
```

---

## CI/CD Integration Flow

How Evalium fits into a standard model deployment pipeline — evaluation as a gate between training and production.

```mermaid
flowchart LR
    subgraph Dev [Development]
        COMMIT[Commit new model\nor prompt change]
    end

    subgraph CI [GitHub Actions or GitLab CI]
        TRIGGER[Workflow triggered\non push to main]
        EVAL_STEP[Run Evalium step\nPOST to /api/v1/runs]
        POLL[Poll GET /api/v1/runs/id\nuntil COMPLETED or FAILED]
        THRESHOLD{Score above\nconfigured threshold?}
        PASS[Pipeline passes\nProceed to deployment]
        FAIL[Pipeline fails\nBlock merge or deploy]
        TRIGGER --> EVAL_STEP --> POLL --> THRESHOLD
        THRESHOLD -->|Yes| PASS
        THRESHOLD -->|No| FAIL
    end

    subgraph Evalium [Evalium Platform]
        API_RECV[Receive run request]
        ASYNC_EXEC[Execute async evaluation job]
        RESULT[Return scored results]
        API_RECV --> ASYNC_EXEC --> RESULT
    end

    subgraph Deploy [Deployment]
        STAGING[Deploy to staging]
        PROD[Promote to production]
        STAGING --> PROD
    end

    COMMIT --> TRIGGER
    EVAL_STEP -->|REST API| API_RECV
    RESULT -->|JSON response| POLL
    PASS --> STAGING
```

---

## Run State Machine

Every evaluation run moves through a defined set of states. Transitions are enforced at the service layer — no direct state mutation is allowed from outside the service.

```mermaid
stateDiagram-v2
    [*] --> Pending : Run submitted via API

    Pending --> Running : Worker picks up job from queue
    Pending --> Cancelled : User cancels before worker starts

    Running --> Completed : All test cases evaluated successfully
    Running --> Failed : Unrecoverable error after retries exhausted
    Running --> PartiallyCompleted : Some test cases failed, rest succeeded
    Running --> Cancelled : User cancels mid-execution

    PartiallyCompleted --> Completed : User accepts partial results
    PartiallyCompleted --> Retrying : User triggers retry for failed cases

    Failed --> Retrying : User triggers full retry
    Retrying --> Running : Worker restarts job

    Completed --> [*]
    Cancelled --> [*]
```

---

## SaaS and Multi-Tenancy Architecture

How Evalium isolates data between organisations and enforces per-plan limits — relevant from Phase 11 onwards but designed into the data model from Phase 1.

```mermaid
flowchart TD
    REQUEST([Incoming API Request]) --> AUTH[JWT Verification\nextract userId and orgId]

    AUTH --> TENANT[Tenant Context Middleware\nattach org and team to request]

    TENANT --> RBAC{RBAC Check\nrole and permission}

    RBAC -->|Insufficient permission| DENY[403 Forbidden]
    RBAC -->|Permitted| PLAN[Plan Limit Check\ncheck org monthly_run_limit]

    PLAN -->|Limit exceeded| LIMIT_ERR[429 Plan limit reached\nupgrade prompt]
    PLAN -->|Within limit| SCOPE[Apply org_id scope\nto all DB queries]

    SCOPE --> HANDLER[Route Handler]
    HANDLER --> DB_QUERY[Scoped DB Query\nWHERE org_id = tenant org_id]
    DB_QUERY --> RESPONSE([Scoped response\nno cross-org data leakage])

    subgraph Roles [Role Hierarchy]
        ORG_ADMIN[Org Admin\nfull org access]
        TEAM_ADMIN[Team Admin\nteam-scoped access]
        MEMBER[Member\nread and run within team]
        VIEWER[Viewer\nread-only]
        ORG_ADMIN --> TEAM_ADMIN --> MEMBER --> VIEWER
    end
```

---

## Security Model

Evalium applies defence-in-depth at every layer. The following table maps each threat to its mitigation.

| Threat                     | Mitigation                                                                                              |
| -------------------------- | ------------------------------------------------------------------------------------------------------- |
| Unauthenticated API access | JWT Bearer tokens on all protected routes, short-lived access tokens with refresh token rotation        |
| Brute-force login          | Rate limiting per IP on `/auth/login`, exponential backoff on repeated failures                         |
| Cross-tenant data access   | `org_id` scope injected into every database query by tenant middleware — no route handler can bypass it |
| SQL injection              | SQLAlchemy parameterised queries throughout — no raw string concatenation                               |
| Privilege escalation       | RBAC middleware enforces role hierarchy per operation before any controller logic runs                  |
| API key compromise         | Keys are stored as bcrypt hashes — compromise of the database does not expose raw keys                  |
| Malicious file upload      | Dataset uploads are validated for format, size, and schema before any content is parsed or stored       |
| Secrets in environment     | All secrets via environment variables, never hardcoded, `.env` excluded from Git and Docker layers      |
| Container escape           | Docker containers run as non-root users with no unnecessary capabilities                                |
| Insecure HTTP              | HTTPS enforced at the reverse proxy layer (Nginx / Caddy) in all production deployments                 |

---

## 12-Phase Build Roadmap

Evalium is being built across 12 structured phases. The Gantt chart shows estimated timelines; the tables below document the exact scope of each phase.

```mermaid
gantt
    title Evalium 12-Phase Build Plan
    dateFormat YYYY-MM-DD
    section Foundation
    Phase 1 Foundation           :done,    p1, 2025-01-01, 3d
    section Backend
    Phase 2 Backend Core         :done,    p2, after p1, 7d
    section Evaluation
    Phase 3 Evaluation Engine    :done,    p3, after p2, 8d
    section Data
    Phase 4 Dataset Management   :done,    p4, after p3, 5d
    section Frontend
    Phase 5 Frontend Dashboard   :done,    p5, after p4, 10d
    section Jobs
    Phase 6 Evaluation Jobs      :done,    p6, after p5, 6d
    section Analytics
    Phase 7 Analytics Reports    :done,    p7, after p6, 6d
    section Advanced
    Phase 8 Advanced Evals       :done,    p8, after p7, 8d
    section Production
    Phase 9 Production Eng       :done,    p9, after p8, 6d
    section API
    Phase 10 API Platform        :done,    p10, after p9, 5d
    section SaaS
    Phase 11 SaaS Features       :done,    p11, after p10, 8d
    section Launch
    Phase 12 Launch              :done,    p12, after p11, 7d
```

---

### Phase 1 — Foundation (2–3 days)

| Task             | Details                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------- |
| Repository setup | GitHub repo, branch protection rules, required status checks, issue and PR templates        |
| README           | Architecture overview, contributing guide, security policy, changelog, roadmap              |
| Folder structure | `backend/`, `frontend/`, `docker/`, `datasets/`, `tests/`, `scripts/`, `examples/`, `docs/` |
| Docker           | Multi-stage Dockerfiles for backend and frontend, base compose with healthchecks            |
| CI setup         | GitHub Actions — lint, type-check, and pytest on every PR to main                           |
| Editor config    | `.editorconfig`, `.gitignore`, pre-commit hooks for formatting and import sorting           |

---

### Phase 2 — Backend Core (5–7 days)

| Task                | Details                                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------------------ |
| FastAPI app factory | Lifespan management, router registration, CORS, trusted host middleware                                      |
| PostgreSQL          | Async SQLAlchemy engine, session factory, base declarative model, connection pool config                     |
| Alembic             | Migration environment setup, initial schema migration, auto-generation workflow                              |
| Core models         | User, Organisation, Team, Project, Dataset, Run, TestCaseResult, APIKey ORM models                           |
| REST APIs           | CRUD endpoints for all core resources under `/api/v1`, response model separation                             |
| Authentication      | JWT access and refresh token pair, bcrypt password hashing, `/auth/register`, `/auth/login`, `/auth/refresh` |
| RBAC                | Role enum, permission matrix, RBAC middleware applied per route                                              |
| Settings            | Pydantic `BaseSettings` with `.env` loading, per-environment config classes                                  |

---

### Phase 3 — Evaluation Engine (6–8 days)

| Task                 | Details                                                                                         |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| JudgeBase            | Abstract base class with `evaluate(output, reference, metric, config) -> EvalResult` contract   |
| Metric registry      | `MetricRegistry` maps metric names to judge classes, supports runtime registration              |
| G-Eval               | Two-call pipeline — step generation then step-level scoring, configurable step weights          |
| DeepEval integration | Faithfulness, answer relevancy, contextual recall, contextual precision, hallucination modules  |
| Prompt templates     | Jinja2 template system, per-metric and per-judge-model template variants, version-controlled    |
| Score normalisation  | Per-metric calibration curves mapping raw judge outputs to 0.0–1.0 range                        |
| Unit tests           | Per-metric test suite with fixture outputs, mock LLM responses, expected score tolerance ranges |

---

### Phase 4 — Dataset Management (4–5 days)

| Task                | Details                                                                                   |
| ------------------- | ----------------------------------------------------------------------------------------- |
| AlpacaEval format   | Native parsing of AlpacaEval JSON instruction sets with schema validation                 |
| CSV upload          | Column mapping interface, type inference, null handling, preview before commit            |
| JSON upload         | Schema validation, nested field flattening, custom field mapping                          |
| Dataset versioning  | Each upload creates immutable version; runs reference a specific `dataset_id` + `version` |
| Storage layer       | File metadata in PostgreSQL, raw files in local filesystem or S3-compatible object store  |
| Dataset preview API | `/datasets/:id/preview?version=N&limit=20` for sampling rows without full download        |

---

### Phase 5 — Frontend Dashboard (7–10 days)

| Task            | Details                                                                                            |
| --------------- | -------------------------------------------------------------------------------------------------- |
| Auth pages      | Login, register, forgot password, JWT refresh handling, protected route guard HOC                  |
| Dashboard       | Run history table with status badges, aggregate score trend sparkline, recent activity feed        |
| Projects page   | Create and list projects, project-level run summary, member list                                   |
| Dataset pages   | Upload wizard (drag-drop + column mapping), version history list, row preview table                |
| Run detail page | Per-test-case score breakdown, chain-of-thought reasoning expandable, score distribution histogram |
| Leaderboard     | Model ranking table sortable by metric, run-over-run score delta column                            |
| Compare view    | Side-by-side model output comparison with score diff highlighting                                  |

---

### Phase 6 — Evaluation Jobs (5–6 days)

| Task               | Details                                                                                 |
| ------------------ | --------------------------------------------------------------------------------------- |
| Celery setup       | Celery app with Redis broker, result backend, worker concurrency config                 |
| Task definition    | `run_evaluation_job` task with run_id, dataset fetch, progress callback                 |
| Priority queuing   | High, default, and low priority queues — CI jobs on high, manual runs on default        |
| Retry logic        | Per-test-case retry with exponential backoff, max 3 attempts, dead-letter on exhaustion |
| Progress tracking  | WebSocket channel per run_id, SSE fallback for clients that don't support WS            |
| Job management API | `DELETE /runs/:id` to cancel, `POST /runs/:id/retry` to restart failed cases            |
| Worker health      | `/workers/status` endpoint exposing active, reserved, and scheduled task counts         |

---

### Phase 7 — Analytics and Reports (5–6 days)

| Task                | Details                                                                        |
| ------------------- | ------------------------------------------------------------------------------ |
| Score distribution  | Histogram of per-test-case scores per metric per run                           |
| Run comparison      | Line chart of aggregate score across multiple runs on the same dataset         |
| Metric radar chart  | Per-run multi-metric spider chart for holistic quality view                    |
| Leaderboard         | Global ranking of models by metric, filterable by project and date range       |
| PDF report          | Auto-generated PDF with run summary, charts, aggregate table, per-case samples |
| CSV and JSON export | Full test case result export with scores and reasoning, paginated download     |

---

### Phase 8 — Advanced Evaluations (7–8 days)

| Task                    | Details                                                                                            |
| ----------------------- | -------------------------------------------------------------------------------------------------- |
| Hallucination detection | Claim extraction from output, fact-checking each claim against reference context                   |
| Faithfulness            | Source attribution — every statement in the answer traced to a retrieved chunk                     |
| Toxicity                | Content safety scoring via configurable classifier (Perspective API or local model)                |
| RAG evaluation          | Full pipeline: contextual precision, contextual recall, answer relevancy, faithfulness in sequence |
| Pairwise comparison     | A vs B comparison via LLM judge, ELO rating update, tournament bracket support                     |
| Custom metrics          | User-defined metric with Jinja2 rubric, scoring scale, and weight configuration via API            |

---

### Phase 9 — Production Engineering (5–6 days)

| Task               | Details                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| Production compose | Separate `docker-compose.prod.yml` with resource limits, restart policies, healthchecks                 |
| Structured logging | `structlog` JSON output with request ID, trace context, user ID, severity                               |
| Prometheus         | `/metrics` endpoint exposing request rate, error rate, job queue depth, worker utilisation              |
| Grafana            | Pre-provisioned dashboard for API latency, evaluation throughput, error rate, queue depth               |
| Rate limiting      | Per-user and per-API-key limits, plan-aware limits, 429 responses with Retry-After header               |
| Security hardening | Input sanitisation on all endpoints, file upload size and type enforcement, SQL parameter binding audit |
| Nginx config       | Reverse proxy config with SSL termination, gzip, static file serving for frontend build                 |

---

### Phase 10 — API Platform (4–5 days)

| Task               | Details                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------ |
| Public REST API    | Separate versioned namespace `/api/v1/public/` for external consumers                      |
| API key management | Create, list, rotate, and revoke API keys, scoped to read or write or admin                |
| Usage tracking     | Per-key request count, token usage estimate, rate limit state exposed in response headers  |
| Python SDK         | `evalforge-python` package with `EvalForgeClient`, typed run submission and result polling |
| JS SDK example     | Minimal JavaScript fetch wrapper with TypeScript types for CI/CD integration               |
| OpenAPI spec       | Auto-generated from FastAPI, published at `/docs` and `/redoc`, downloadable as JSON       |

---

### Phase 11 — SaaS Features (6–8 days)

| Task                 | Details                                                                            |
| -------------------- | ---------------------------------------------------------------------------------- |
| Organisations        | Org creation, slug-based routing, org admin role, member invite via email token    |
| Teams                | Team creation within org, team-scoped project access, team-level API keys          |
| Usage metering       | Per-org run counter, token usage estimator, usage history endpoint                 |
| Plan limits          | Free, Pro, and Enterprise plan model, feature gating middleware, limit enforcement |
| Subscription hooks   | Webhook receiver for billing events, plan upgrade and downgrade handling           |
| Billing-ready schema | `subscription_plan`, `usage_event`, `invoice` tables ready for Stripe integration  |

---

### Phase 12 — Launch (5–7 days)

| Task                  | Details                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------- |
| Production deployment | Cloud VM or managed Kubernetes, domain, SSL via Let's Encrypt or Caddy                  |
| Full documentation    | User guide, self-hosting guide, API reference, SDK docs, CI integration cookbook        |
| GitHub polishing      | Final README pass, repository topics, social preview image, v1.0.0 release tag          |
| Demo video            | Screencast walkthrough covering run submission, live progress, results, and leaderboard |
| Product Hunt          | Launch page, tagline, assets, community coordination, scheduled launch day              |
| Hacker News           | Show HN post with technical depth and architecture rationale                            |
| Portfolio update      | Resume and portfolio updated with Evalium as a featured production project            |

---

## Tech Stack

### Backend

| Technology         | Version | Purpose                                              |
| ------------------ | ------- | ---------------------------------------------------- |
| Python             | 3.12    | Runtime                                              |
| FastAPI            | Latest  | REST API framework, async-native, auto OpenAPI       |
| SQLAlchemy (Async) | Latest  | ORM and query layer, async session management        |
| Alembic            | Latest  | Database migration management, auto-generation       |
| Pydantic v2        | Latest  | Request and response validation, settings management |
| Celery             | Latest  | Distributed task queue, background job execution     |
| Redis              | Latest  | Celery broker, result backend, response cache        |
| Structlog          | Latest  | Structured JSON logging with async support           |
| bcrypt             | Latest  | Password hashing, API key storage                    |
| Jinja2             | Latest  | Judge prompt template rendering                      |

### Frontend

| Technology  | Version | Purpose                                                  |
| ----------- | ------- | -------------------------------------------------------- |
| React       | 18      | UI component library, concurrent rendering               |
| TypeScript  | Latest  | Type-safe frontend code, API response typing             |
| Vite        | Latest  | Build tool, HMR dev server, optimised production bundle  |
| Vanilla CSS | —       | Premium styling without library overhead or bundle bloat |

### Infrastructure

| Technology              | Purpose                                                  |
| ----------------------- | -------------------------------------------------------- |
| Docker + Docker Compose | Full stack containerisation, dev and prod variants       |
| PostgreSQL              | Primary relational database, ACID transactions           |
| Redis                   | Celery task broker, caching, WebSocket pub/sub           |
| GitHub Actions          | CI — lint, type-check, pytest, type-coverage on every PR |
| Prometheus              | Metrics scraping from API and workers                    |
| Grafana                 | Pre-provisioned observability dashboards                 |
| Nginx                   | Reverse proxy, SSL termination, static file serving      |

### Evaluation Frameworks

| Framework           | Metrics Supported                                                                      |
| ------------------- | -------------------------------------------------------------------------------------- |
| G-Eval              | Coherence, relevance, correctness, fluency — any rubric via chain-of-thought           |
| DeepEval            | Faithfulness, answer relevancy, contextual recall, contextual precision, hallucination |
| AlpacaEval          | Instruction following, pairwise winrate against reference model                        |
| Custom LLM Judge    | Any user-defined scoring rubric via Jinja2 prompt template                             |
| Pairwise Comparator | A/B model comparison with ELO rating and tournament bracket                            |

---

## Project Structure

```
Evalium/
|
+-- .github/
|   +-- workflows/
|   |   +-- ci.yml                   # Lint, type-check, pytest on every PR
|   |   +-- release.yml              # Tag and release automation
|   +-- ISSUE_TEMPLATE/
|   |   +-- bug_report.md
|   |   +-- feature_request.md
|   +-- PULL_REQUEST_TEMPLATE.md
|
+-- backend/
|   +-- app/
|   |   +-- api/
|   |   |   +-- v1/
|   |   |       +-- auth.py          # /auth/register, /auth/login, /auth/refresh
|   |   |       +-- projects.py      # Project CRUD
|   |   |       +-- datasets.py      # Dataset upload, version management
|   |   |       +-- runs.py          # Run submission, status, results
|   |   |       +-- leaderboard.py   # Aggregate model ranking
|   |   |       +-- keys.py          # API key management
|   |   |       +-- health.py        # /health endpoint
|   |   +-- core/
|   |   |   +-- config.py            # Pydantic BaseSettings, env loading
|   |   |   +-- security.py          # JWT helpers, bcrypt, token rotation
|   |   |   +-- dependencies.py      # FastAPI dependency injection
|   |   |   +-- middleware.py        # RBAC, tenant context, rate limit
|   |   +-- db/
|   |   |   +-- engine.py            # Async SQLAlchemy engine and session factory
|   |   |   +-- base.py              # Declarative base, UUID PK mixin, timestamp mixin
|   |   +-- models/                  # SQLAlchemy ORM models
|   |   |   +-- user.py
|   |   |   +-- organisation.py
|   |   |   +-- team.py
|   |   |   +-- project.py
|   |   |   +-- dataset.py
|   |   |   +-- run.py
|   |   |   +-- test_case_result.py
|   |   |   +-- api_key.py
|   |   +-- schemas/                 # Pydantic request and response schemas
|   |   +-- services/                # Business logic layer
|   |   |   +-- run_service.py       # Run creation, dispatch, status management
|   |   |   +-- dataset_service.py   # Upload parsing, versioning, storage
|   |   |   +-- auth_service.py      # Registration, login, token management
|   |   +-- evaluation/              # Evaluation engine
|   |   |   +-- judge_base.py        # Abstract JudgeBase interface and EvalResult type
|   |   |   +-- registry.py          # MetricRegistry — metric name to judge class mapping
|   |   |   +-- geval.py             # G-Eval two-call chain-of-thought implementation
|   |   |   +-- deepeval_judge.py    # DeepEval framework wrapper
|   |   |   +-- alpaca.py            # AlpacaEval winrate integration
|   |   |   +-- pairwise.py          # Pairwise A/B comparator with ELO updater
|   |   |   +-- custom.py            # Custom Jinja2 prompt template judge
|   |   |   +-- rag_pipeline.py      # Full RAG evaluation pipeline orchestrator
|   |   |   +-- normaliser.py        # Per-metric score normalisation and calibration
|   |   |   +-- templates/           # Jinja2 prompt templates per metric and model
|   |   +-- workers/
|   |   |   +-- tasks.py             # Celery task definitions
|   |   |   +-- celery_app.py        # Celery app factory with broker and backend config
|   |   +-- main.py                  # FastAPI app factory, lifespan, router registration
|   +-- alembic/
|   |   +-- versions/                # Migration files
|   |   +-- env.py                   # Alembic async migration environment
|   +-- requirements.txt
|   +-- requirements-dev.txt         # Dev dependencies — pytest, mypy, ruff
|
+-- frontend/
|   +-- src/
|   |   +-- components/              # Reusable UI components
|   |   +-- pages/                   # Dashboard, Projects, Datasets, Runs, Leaderboard
|   |   +-- api/                     # Typed Axios client wrappers per resource
|   |   +-- hooks/                   # useRun, useDataset, useLeaderboard, useAuth
|   |   +-- context/                 # AuthContext, TenantContext
|   |   +-- types/                   # TypeScript type definitions mirroring backend schemas
|   |   +-- utils/                   # Date formatting, score colour coding, chart helpers
|   +-- vite.config.ts
|   +-- tsconfig.json
|
+-- datasets/                        # Sample golden datasets for development and testing
+-- docker/
|   +-- backend.Dockerfile           # Multi-stage Python build
|   +-- frontend.Dockerfile          # Multi-stage Node.js build, nginx serving
+-- docs/
|   +-- ARCHITECTURE.md              # System architecture design
|   +-- HLD.md                       # High-level system design
|   +-- LLD.md                       # Low-level component design
|   +-- PRD.md                       # Product requirements document
|   +-- api.md                       # Full API reference
|   +-- architecture.md              # Detailed architecture decisions
|   +-- self-hosting.md              # Production deployment guide
|   +-- assets/                      # README banner, screenshots
+-- examples/
|   +-- python_sdk_example.py        # Python SDK usage
|   +-- github_actions_example.yml   # CI integration template
|   +-- curl_examples.sh             # Raw REST API examples
+-- scripts/
|   +-- seed.py                      # Database seed with sample data
|   +-- generate_migration.sh        # Alembic migration generation helper
+-- tests/
|   +-- unit/                        # Unit tests per service and evaluation module
|   +-- integration/                 # API integration tests using TestClient
|   +-- fixtures/                    # Shared test fixtures and mock LLM responses
+-- docker-compose.yml               # Development stack
+-- docker-compose.prod.yml          # Production stack with resource limits
+-- CONTRIBUTING.md
+-- CHANGELOG.md
+-- ROADMAP.md
+-- SECURITY.md
+-- LICENSE
+-- README.md
```

---

## Environment Configuration

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

```env
# ── App ────────────────────────────────────────────────────────────────────────
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
SECRET_KEY=your-minimum-64-character-secret-key-change-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://evalforge:password@localhost:5432/evalforge
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# ── Redis ──────────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# ── Judge LLM ─────────────────────────────────────────────────────────────────
# The model used as the judge in G-Eval and custom LLM-as-a-Judge evaluations
JUDGE_LLM_PROVIDER=openai          # openai | anthropic | local
JUDGE_LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-key  # if using Anthropic as judge

# ── Storage ────────────────────────────────────────────────────────────────────
STORAGE_BACKEND=local              # local | s3
LOCAL_STORAGE_PATH=./storage
AWS_S3_BUCKET=your-bucket
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# ── Rate Limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL=info
LOG_FORMAT=json
```

---

## Prerequisites

| Requirement       | Version | Notes                                                  |
| ----------------- | ------- | ------------------------------------------------------ |
| Docker            | v20+    | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Docker Compose    | v2+     | Bundled with Docker Desktop                            |
| Node.js           | v20+    | Required for frontend development without Docker       |
| Python            | 3.11+   | Required for backend development without Docker        |
| Judge LLM API key | —       | OpenAI, Anthropic, or a local Ollama instance          |

---

## Getting Started

### Option A — Full Stack with Docker (Recommended)

```bash
git clone https://github.com/hardikkaurani/Evalium.git
cd Evalium
cp backend/.env.example backend/.env
docker compose up --build -d
```

| Service            | URL                         | Notes |
| ------------------ | --------------------------- | ----- |
| Frontend           | http://localhost            | React 19 SPA |
| Backend API        | http://localhost:8000       | FastAPI REST Gateway |
| API Docs - Swagger | http://localhost:8000/docs  | Interactive OpenAPI explorer |
| API Docs - ReDoc   | http://localhost:8000/redoc | ReDoc reference |
| Grafana (Prod profile) | http://localhost:3000   | `docker compose -f docker-compose.prod.yml up` |
| Prometheus (Prod profile) | http://localhost:9090 | Metrics telemetry |

### Option B — Manual Development Setup

```bash
# Step 1 — Start infrastructure (PostgreSQL & Redis)
docker compose up postgres redis -d

# Step 2 — Backend setup & migrations
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head            # Apply database migrations
uvicorn app.main:app --reload --port 8000

# Step 3 — Start Celery background worker (in a new terminal)
cd backend
source .venv/bin/activate      # Windows: .venv\Scripts\activate
celery -A app.jobs.queue.celery_app worker --loglevel=info --concurrency=4

# Step 4 — Frontend setup
cd frontend
npm install
cp .env.example .env
npm run dev                    # Serves on http://localhost:5173
```

---

## API Reference

All endpoints are versioned under `/api/v1`. Protected routes require:

```
Authorization: Bearer <access_token>
```

### Authentication

| Method | Endpoint                | Auth | Description                                         |
| ------ | ----------------------- | ---- | --------------------------------------------------- |
| `POST` | `/api/v1/auth/register` | No   | Create user account                                 |
| `POST` | `/api/v1/auth/login`    | No   | Authenticate, returns access and refresh token pair |
| `POST` | `/api/v1/auth/refresh`  | No   | Exchange refresh token for new access token         |
| `POST` | `/api/v1/auth/logout`   | Yes  | Revoke refresh token                                |

### Projects

| Method   | Endpoint               | Auth | Description                                   |
| -------- | ---------------------- | ---- | --------------------------------------------- |
| `GET`    | `/api/v1/projects`     | Yes  | List all projects in authenticated user's org |
| `POST`   | `/api/v1/projects`     | Yes  | Create a new project                          |
| `GET`    | `/api/v1/projects/:id` | Yes  | Get project details and run summary           |
| `PUT`    | `/api/v1/projects/:id` | Yes  | Update project metadata                       |
| `DELETE` | `/api/v1/projects/:id` | Yes  | Delete project and all associated runs        |

### Datasets

| Method | Endpoint                        | Auth | Description                                         |
| ------ | ------------------------------- | ---- | --------------------------------------------------- |
| `POST` | `/api/v1/datasets`              | Yes  | Upload new dataset (CSV or JSON), creates version 1 |
| `GET`  | `/api/v1/datasets`              | Yes  | List all datasets in project                        |
| `GET`  | `/api/v1/datasets/:id/versions` | Yes  | List all immutable versions of a dataset            |
| `GET`  | `/api/v1/datasets/:id/preview`  | Yes  | Preview rows from a specific dataset version        |

### Runs

| Method   | Endpoint                    | Auth | Description                                              |
| -------- | --------------------------- | ---- | -------------------------------------------------------- |
| `POST`   | `/api/v1/runs`              | Yes  | Submit a new evaluation job                              |
| `GET`    | `/api/v1/runs`              | Yes  | List all runs with optional project and status filter    |
| `GET`    | `/api/v1/runs/:id`          | Yes  | Full run results with per-test-case scores and reasoning |
| `GET`    | `/api/v1/runs/:id/progress` | Yes  | Current completion percentage and status                 |
| `DELETE` | `/api/v1/runs/:id`          | Yes  | Cancel a pending or running job                          |
| `POST`   | `/api/v1/runs/:id/retry`    | Yes  | Retry failed test cases in a completed run               |

### Leaderboard and Reports

| Method | Endpoint                  | Auth | Description                        |
| ------ | ------------------------- | ---- | ---------------------------------- |
| `GET`  | `/api/v1/leaderboard`     | Yes  | Global model ranking by metric     |
| `GET`  | `/api/v1/runs/:id/report` | Yes  | Download auto-generated PDF report |
| `GET`  | `/api/v1/runs/:id/export` | Yes  | Download full result CSV or JSON   |

### Platform

| Method   | Endpoint           | Auth | Description                          |
| -------- | ------------------ | ---- | ------------------------------------ |
| `GET`    | `/api/v1/keys`     | Yes  | List API keys for authenticated user |
| `POST`   | `/api/v1/keys`     | Yes  | Create new API key with scope        |
| `DELETE` | `/api/v1/keys/:id` | Yes  | Revoke an API key                    |
| `GET`    | `/api/v1/health`   | No   | API, DB, and Redis status            |
| `GET`    | `/metrics`         | No   | Prometheus metrics endpoint          |

---

## Error Handling

All errors follow a consistent JSON envelope:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "dataset_id is required when submitting a run",
    "details": { "field": "dataset_id" }
  },
  "request_id": "01J3K2..."
}
```

| HTTP Code | Error Code         | Meaning                                                          |
| --------- | ------------------ | ---------------------------------------------------------------- |
| 400       | `VALIDATION_ERROR` | Request body or query param failed Pydantic validation           |
| 401       | `UNAUTHENTICATED`  | Missing or expired JWT                                           |
| 403       | `FORBIDDEN`        | Authenticated but insufficient role for this operation           |
| 404       | `NOT_FOUND`        | Resource does not exist or belongs to a different org            |
| 409       | `CONFLICT`         | Duplicate resource (e.g. dataset name already exists in project) |
| 422       | `UNPROCESSABLE`    | Semantically invalid input (e.g. dataset has no rows)            |
| 429       | `RATE_LIMITED`     | Per-user or per-plan limit exceeded, check `Retry-After` header  |
| 500       | `INTERNAL_ERROR`   | Unhandled server error, `request_id` included for support        |

---

## Observability

Evalium exposes a Prometheus-compatible `/metrics` endpoint from the API. The following metrics are tracked:

| Metric                                    | Type      | Description                                           |
| ----------------------------------------- | --------- | ----------------------------------------------------- |
| `evalforge_http_requests_total`           | Counter   | Total HTTP requests by method, route, and status code |
| `evalforge_http_request_duration_seconds` | Histogram | Request latency with p50, p95, p99 buckets            |
| `evalforge_runs_total`                    | Counter   | Total evaluation runs submitted by status             |
| `evalforge_run_duration_seconds`          | Histogram | End-to-end evaluation job duration                    |
| `evalforge_queue_depth`                   | Gauge     | Current number of jobs in the Celery queue            |
| `evalforge_worker_active_tasks`           | Gauge     | Currently executing Celery tasks across all workers   |
| `evalforge_test_cases_evaluated_total`    | Counter   | Total test cases evaluated across all runs            |
| `evalforge_judge_latency_seconds`         | Histogram | Per-LLM-call latency for each judge type              |

The Grafana dashboard is auto-provisioned at `http://localhost:3001` when running via Docker Compose.

---

## Phase 3: Evaluation Engine

Evalium now includes a modular evaluation engine with:

- provider abstraction for OpenAI, Gemini, Claude, Ollama, OpenRouter, and DeepSeek
- judge abstraction for G-Eval, pairwise, reference-based, and rubric-based evaluation
- versioned prompt templates and runtime prompt overrides
- a rubric catalog with custom rubric support
- metric plugin registration and aggregate scoring
- batch execution with retry support and partial failure isolation

### Documentation

- [Evaluation Engine Guide](docs/evaluation-engine-guide.md)
- [Provider Guide](docs/provider-guide.md)
- [Rubric Guide](docs/rubric-guide.md)
- [API Documentation](docs/api-documentation.md)
- [Architecture Diagram](docs/architecture-diagram.md)
- [Developer Documentation](docs/developer-documentation.md)

---

## Contributing

1. Fork the repository and create your branch from `main`:

```bash
git checkout -b feat/your-feature-name
```

2. Follow Conventional Commits:

```
feat(engine): add pairwise ELO rating updater
fix(api): handle empty dataset upload with clear error message
docs(readme): update phase 8 RAG pipeline scope
chore(docker): add postgres healthcheck to compose
test(evaluation): add G-Eval fixture tests with mock LLM responses
```

3. Ensure all checks pass before opening a PR:

```bash
# Backend — lint, type-check, tests
cd backend
ruff check app/
mypy app/
pytest tests/ -v --cov=app --cov-report=term-missing

# Frontend — type-check, lint
cd frontend
npm run type-check
npm run lint
```

4. Open a Pull Request against `main` with a description, motivation, and screenshots or test output where relevant.

See our full guides:

- **[CONTRIBUTING.md](CONTRIBUTING.md):** Comprehensive 23-section maintainer & contributor handbook.
- **[FIRST_CONTRIBUTOR_GUIDE.md](.github/FIRST_CONTRIBUTOR_GUIDE.md):** 10-minute quickstart guide for first-time open source contributors.
- **[CONTRIBUTOR_ISSUES_CATALOG.md](docs/CONTRIBUTOR_ISSUES_CATALOG.md):** 30 real, curated engineering issues ready for assignment.
- **[SUPPORT.md](SUPPORT.md):** Support channels, GitHub Discussions, and community help.
- **[GOVERNANCE.md](GOVERNANCE.md) & [MAINTAINERS.md](MAINTAINERS.md):** Project governance, maintainer team, and triage policies.
- **[SECURITY.md](SECURITY.md):** Security policies and private vulnerability reporting SLAs.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md):** Contributor Covenant v2.1 standards.

---

## 👥 Community & Contributor Recognition

We love and appreciate our open-source contributors! Evalium is built by developers worldwide.

<a href="https://github.com/hardikkaurani/Evalium/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=hardikkaurani/Evalium" alt="Evalium Contributors" />
</a>

### How to Join the Contributor Hall of Fame:

1. Pick an unassigned issue from our [`good first issue`](https://github.com/hardikkaurani/Evalium/issues?q=is%3Aissue+is%3Aopen+label%3A"good+first+issue") list.
2. Run `./scripts/setup-dev-env.sh` (or `.\scripts\setup-dev-env.ps1`) to initialize your local stack.
3. Submit your PR — once merged, your avatar will appear above automatically!

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><b>1. Can I run Evalium 100% locally without an internet connection?</b></summary>
<br/>
Yes! Evalium can be hosted entirely offline via Docker Compose using local database instances and Ollama or vLLM local judge inference models. Zero outbound telemetry is collected.
</details>

<details>
<summary><b>2. How does Evalium ensure evaluation reproducibility?</b></summary>
<br/>
Every dataset import creates an immutable version snapshot (`v1`, `v2`). Evaluation experiments are snapshot-pinned to a specific version, ensuring identical benchmark scoring results over time.
</details>

<details>
<summary><b>3. Is Evalium suitable for production enterprise workloads?</b></summary>
<br/>
Yes. Evalium features Celery worker queues backed by Redis for horizontal scaling, PostgreSQL async connection pooling, API key SHA-256 hashing, rate limiting, and multi-tenant organization boundaries.
</details>

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

<div align="center">

_EvalForge — built for AI engineers who refuse to ship LLMs they cannot measure._

<br/>

**[hardikkaurani](https://github.com/hardikkaurani)** &nbsp;·&nbsp; [Issues](https://github.com/hardikkaurani/Evalium/issues) &nbsp;·&nbsp; [Discussions](https://github.com/hardikkaurani/Evalium/discussions) &nbsp;·&nbsp; [ROADMAP.md](ROADMAP.md) &nbsp;·&nbsp; [CONTRIBUTING.md](CONTRIBUTING.md)

</div>

## Workspace interface

See [UI setup and API-key provisioning](docs/ui-setup.md) for the redesigned interface, local browser validation, and production configuration. [Release evidence](docs/ui-release-review.md) records tested workflows and remaining deployment checks.
