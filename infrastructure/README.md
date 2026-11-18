# Infrastructure

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full stack: PostgreSQL 17 → Prisma migration job → API → dashboard |
| `docker-compose.neon.yml` | Override that uses a Neon database instead of the local PostgreSQL |
| `.env.example` | Settings for Compose; copy to `.env` (git-ignored) |

Images are defined next to their code: `backend/Dockerfile`, `frontend/Dockerfile`,
`database/Dockerfile` (migrations). CI (`.github/workflows/ci.yml`) builds all three on every push.

```bash
cd infrastructure
cp .env.example .env
docker compose up --build                                                  # local PostgreSQL
docker compose -f docker-compose.yml -f docker-compose.neon.yml up --build # Neon
docker compose down          # stop (add -v to also delete the local database volume)
```

See the main README, section "Deployment with Docker", for details.
