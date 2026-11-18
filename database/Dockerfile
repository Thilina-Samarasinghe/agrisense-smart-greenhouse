# syntax=docker/dockerfile:1
# One-shot migration job: applies prisma/migrations to the database, then exits.
# Build from the database folder:  docker build -t agrisense-migrate database
# Run:  docker run --rm -e MIGRATE_DATABASE_URL=postgresql://... agrisense-migrate
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production \
    CHECKPOINT_DISABLE=1
COPY package.json ./
# Exact versions are pinned in package.json (prisma 7.10.1, dotenv 17.4.2).
RUN npm install --no-audit --no-fund --include=dev
COPY prisma.config.ts ./
COPY prisma ./prisma
RUN addgroup -S agrisense && adduser -S agrisense -G agrisense && chown -R agrisense:agrisense /app
USER agrisense
CMD ["npx", "prisma", "migrate", "deploy"]
