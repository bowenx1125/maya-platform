FROM node:24.14.0-alpine@sha256:7fddd9ddeae8196abf4a3ef2de34e11f7b1a722119f91f28ddf1e99dcafdf114 AS base

ENV PNPM_HOME=/pnpm
ENV PATH=${PNPM_HOME}:${PATH}

RUN corepack enable && corepack prepare pnpm@11.19.0 --activate

WORKDIR /workspace

FROM base AS dependencies

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json frontend/package.json
RUN pnpm install --frozen-lockfile --filter @maya/frontend...

FROM dependencies AS builder

ARG NEXT_PUBLIC_RUNTIME_MODE=container
ARG NEXT_PUBLIC_BUILD_SHA=local
ENV NEXT_PUBLIC_RUNTIME_MODE=${NEXT_PUBLIC_RUNTIME_MODE}
ENV NEXT_PUBLIC_BUILD_SHA=${NEXT_PUBLIC_BUILD_SHA}

COPY frontend frontend
RUN pnpm --filter @maya/frontend build

FROM base AS runner

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /workspace /workspace

WORKDIR /workspace
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:3000/health').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["pnpm", "--filter", "@maya/frontend", "start"]
