# Evalium Test Suites & Test Architecture

This directory provides the top-level architectural map for all automated test suites across the Evalium monorepo.

---

## Test Suite Distribution

Evalium maintains strict modular test isolation aligned with subproject boundaries:

| Test Scope | Target Subproject | Location | Framework / Tools |
|---|---|---|---|
| **Backend Core** | FastAPI API Gateway, ORM, Celery | [`backend/tests/`](../backend/tests/) | `pytest`, `pytest-asyncio`, `httpx` |
| **Python SDK** | Official Python Client (`evalforge`) | [`sdk/python/tests/`](../sdk/python/tests/) | `pytest`, `pytest-asyncio` |
| **CLI Tooling** | Command-Line Interface (`evalforge-cli`) | [`cli/tests/`](../cli/tests/) | `pytest`, `unittest.mock` |
| **Frontend Unit** | React Components & Services | [`frontend/src/services/client.test.ts`](../frontend/src/services/client.test.ts) | `vitest` |
| **Frontend E2E** | Full Browser & OAuth Workflows | [`frontend/tests/`](../frontend/tests/) | `@playwright/test` |

---

## Running Tests

### 1. Run Complete Python Test Suite (Backend + SDK + CLI)
From the repository root:
```bash
pytest
```
*Discovers and executes all 230+ unit, integration, and security test cases across `backend/tests/`, `sdk/python/tests/`, and `cli/tests/`.*

### 2. Run Backend Tests Only
```bash
pytest backend/tests -v
```

### 3. Run SDK Tests Only
```bash
pytest sdk/python/tests -v
```

### 4. Run CLI Tests Only
```bash
pytest cli/tests -v
```

### 5. Run Frontend Tests
From the `frontend/` directory:
```bash
cd frontend
npm test             # Vitest unit test suite
npm run test:e2e     # Playwright headless browser E2E tests
```
