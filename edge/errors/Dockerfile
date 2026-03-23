# errors — Branded error pages for KubeLab edge layer
# Serves static error pages (502/503/504) consumed by Traefik error middleware
FROM nginx:1.27-alpine

ARG VERSION=dev
ARG COMMIT_SHA=unknown

LABEL org.opencontainers.image.title="kubelab-errors" \
      org.opencontainers.image.description="Branded error and maintenance pages for KubeLab" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/mlorentedev/kubelab"

RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    chown -R appuser:appgroup /var/cache/nginx /var/log/nginx && \
    touch /var/run/nginx.pid && chown appuser:appgroup /var/run/nginx.pid

COPY nginx.conf /etc/nginx/nginx.conf
COPY html/ /usr/share/nginx/html/

RUN chown -R appuser:appgroup /usr/share/nginx/html

USER 1001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1
