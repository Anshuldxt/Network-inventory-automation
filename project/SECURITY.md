# Security checklist
- Change POSTGRES_PASSWORD before deployment.
- Keep port 8080 internal or put Nginx/HTTPS/reverse proxy in front.
- Do not expose PostgreSQL (5432) publicly.
- Add SSO/OIDC before production-wide access.
- Back up the PostgreSQL volume and `/data`.
