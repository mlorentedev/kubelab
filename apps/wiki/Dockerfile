FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /srv/app

# Copia el binario que construyes en tu etapa build
COPY --from=builder /app/server /usr/local/bin/server

# Copia templates del wiki
COPY src/templates/wiki ./src/templates/wiki

VOLUME ["/data"]  # contenido de docs cacheado por ramas
ENV CONTENT_ROOT=/data/content
ENV GH_OWNER=mlorentedev
ENV GH_REPO=mlorente.dev
ENV GH_BRANCH_ALLOW=develop,master
ENV GH_BRANCH_DENY=
ENV BRANCH_POLL_MINUTES=5

EXPOSE 8080
CMD ["server"]
