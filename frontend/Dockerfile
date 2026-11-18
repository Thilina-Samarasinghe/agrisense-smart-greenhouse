# syntax=docker/dockerfile:1
# AgriSense dashboard (Next.js standalone build).
# Build from the frontend folder:
#   docker build --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t agrisense-frontend frontend
# NEXT_PUBLIC_API_URL is used by the browser and baked in at build time.

# ---- dependencies (cached separately from the source)
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- build
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- runtime: only the standalone server and static assets
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S agrisense && adduser -S agrisense -G agrisense
COPY --from=build --chown=agrisense:agrisense /app/.next/standalone ./
COPY --from=build --chown=agrisense:agrisense /app/.next/static ./.next/static
COPY --from=build --chown=agrisense:agrisense /app/public ./public
USER agrisense
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD wget -qO- http://127.0.0.1:3000/ > /dev/null || exit 1
CMD ["node", "server.js"]
