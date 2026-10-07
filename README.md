# Network Inventory — Multi-vendor console

3-tier app: React (frontend) + FastAPI (backend/worker) + PostgreSQL.
See /infra for Terraform (Azure) and /azure-pipelines.yml for CI/CD.

## Branching strategy (trunk-based)
- `main` — always deployable, protected. Every merge here auto-deploys to production.
- `feature/*` — one branch per change. Opens a PR into `main`.
- PR triggers CI (build + test) but never deploys by itself.
- Merge to `main` triggers CI again, then deploys to Azure.
