# errors — Branded error pages for KubeLab edge layer
# Serves static error pages (502/503/504) consumed by Traefik error middleware
FROM nginx:1.31-alpine

ARG VERSION=dev
ARG COMMIT_SHA=unknown

LABEL org.opencontainers.image.title="kubelab-errors" \
      org.opencontainers.image.description="Branded error and maintenance pages for KubeLab" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/mlorentedev/kubelab"

# SEC: pull patched packages from Alpine's live index at build time rather than
# waiting for a new nginx:1.31-alpine base image build. Fixes 3 HIGH CVEs
# (CVE-2026-56131/56407/56408) in libexpat 2.8.1-r0, patched in 2.8.2-r0.
#
# SINGLE-STAGE, so this whole file is what Trivy scans — unlike apps/api, where
# only the runtime stage is judged. Stated because a reader cannot otherwise tell
# which layers the gate holds them to.
#
# AND IT IS NOT ENOUGH ON ITS OWN. Measured 2026-08-24: the published image
# carried 5 HIGH CVEs (curl and libcurl 8.19.0-r0, c-ares 1.34.6-r0), every one
# with a fix available upstream that day. The line below would have collected all
# five — on a build that never happened, because this service's source had not
# changed. Patching at build time closes the gap between an upstream fix and a
# new base image; nothing here closes the gap between an upstream fix and the
# next build. That is #1385 AC3, and it is the one that matters for a service
# whose code is stable.
RUN apk update && apk upgrade --no-cache

RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    chown -R appuser:appgroup /var/cache/nginx /var/log/nginx && \
    touch /var/run/nginx.pid && chown appuser:appgroup /var/run/nginx.pid

COPY nginx.conf /etc/nginx/nginx.conf
COPY html/ /usr/share/nginx/html/

RUN chown -R appuser:appgroup /usr/share/nginx/html

USER 1001

EXPOSE 8080

# Exec form with an explicit `sh -c`, not shell form: the `||` needs a shell, and
# hadolint (DL3025) is right that leaving the choice implicit is how a CMD ends
# up depending on whichever shell the base happens to ship. Semantically
# identical to what it replaces.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/bin/sh", "-c", "wget -qO- http://localhost:8080/health || exit 1"]
