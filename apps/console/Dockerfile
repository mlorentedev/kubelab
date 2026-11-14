# console — the operator console's frontend (ADR-074). Astro static output served by nginx.
# Context: apps/console, which is what ci-publish.yml passes (`context/Dockerfile`).
#
# The build stage runs on the build platform and declares no TARGETPLATFORM, TARGETOS or
# TARGETARCH. The output is static files, identical for every architecture, so BuildKit runs
# the stage once and both platforms copy the same dist/. An ARG in scope is part of every
# RUN's cache key: declaring them made `web`'s build run once per target (#376 there).
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS build

WORKDIR /app
RUN chown node:node /app
USER 1000:1000

COPY --chown=node:node package.json package-lock.json ./
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 \
    npm ci

# `.dockerignore` keeps a local node_modules out, so this cannot lay one over what `npm ci`
# installed. `npm run build` is `astro check && astro build`: a type error fails the image.
COPY --chown=node:node . ./
RUN npm run build

# ---------- Runtime: nginx serving dist/ ----------
FROM nginxinc/nginx-unprivileged:1.31-alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e

# ci-publish.yml passes both; they label the image and change nothing else.
ARG VERSION=dev
ARG COMMIT_SHA=unknown

LABEL org.opencontainers.image.title="kubelab-console" \
      org.opencontainers.image.description="Operator console frontend for KubeLab" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${COMMIT_SHA}" \
      org.opencontainers.image.source="https://github.com/mlorentedev/kubelab"

# The base ships its own index.html and 50x.html in the web root, and the COPY below merges
# into that directory. Emptying it first makes the served tree exactly dist/.
USER 0

# SEC: take patched Alpine packages from the live index at build time instead of waiting for a
# new base image. ci-publish.yml's Trivy step fails the publish on any fixable HIGH or CRITICAL,
# and the pinned base carried several (musl, zlib, expat, libxslt) on 2026-11-13. This closes the
# gap between an upstream fix and the next base image, not the gap between a fix and the next
# build of this app: the weekly Dependabot bump of the digest above is what moves the base.
# The runtime stage is the only one Trivy judges, as in edge/errors.
RUN apk update && apk upgrade --no-cache && rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Fail the build, which pull requests run, on a config that would not start.
RUN nginx -t
# The base's own user (uid 101), so the pod can run with a read-only root and a tmpfs at /tmp.
USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "-qO-", "http://localhost:8080/"]
