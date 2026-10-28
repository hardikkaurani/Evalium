# Evalium Tooling & Maintenance Scripts

This directory contains repository-wide developer tooling, diagnostic utilities, and environment provisioning scripts.

---

## Script Catalog

### 1. Environment & Dependency Doctor (`check_environment.py`)
A comprehensive pre-flight verification tool verifying toolchain compatibility, dependency integrity, database connectivity, and production security rules without leaking secrets.

```bash
# Run verification for local development environment:
python scripts/check_environment.py --env development

# Run verification for production release readiness:
python scripts/check_environment.py --env production
```

*Automated test coverage for this tool is maintained in [`backend/tests/test_environment_doctor.py`](../backend/tests/test_environment_doctor.py).*

---

### 2. Automated Developer Environment Setup

#### Linux / macOS / WSL:
```bash
bash scripts/setup-dev-env.sh
```

#### Windows PowerShell:
```powershell
.\scripts\setup-dev-env.ps1
```

Both scripts automate:
* Virtual environment creation (`.venv`)
* Python dependency installation (`backend/requirements.txt`)
* Editable package installation (`sdk/python` and `cli`)
* Frontend dependency installation (`frontend/package.json`)

---

## Backend Deployment & Runtime Scripts

Additional service-specific scripts are located in [`backend/scripts/`](../backend/scripts/):

* **[`backend/scripts/start.sh`](../backend/scripts/start.sh):** Container entrypoint executing Alembic migrations and starting the Uvicorn ASGI server.
* **[`backend/scripts/bootstrap_workspace.py`](../backend/scripts/bootstrap_workspace.py):** Administrative bootstrap script to provision the initial organization, default workspace, and owner API key.
