# Build Stage
FROM golang:1.25-alpine AS build

WORKDIR /app

# Instalar herramientas esenciales
RUN apk add --no-cache git ca-certificates tzdata && \
    update-ca-certificates

# Instalar Air para recarga en desarrollo
RUN apk add --no-cache git make bash
RUN go install github.com/air-verse/air@latest

# Copiar archivos de módulos y descargar dependencias
COPY src/go.mod src/go.sum ./

# Copiar el código fuente
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download
COPY src/ ./

# Compilar la aplicación con optimizaciones
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 \
    go build -ldflags="-w -s" -o server ./cmd/server

# Runtime Stage - usando alpine mínimo
FROM alpine:3.18 AS runtime

WORKDIR /app

# Instalar certificados y zona horaria
RUN apk --no-cache add ca-certificates tzdata && \
    update-ca-certificates

# Copiar el ejecutable compilado desde la etapa de build
COPY --from=build /app/server ./

# Crear usuario no-root para seguridad
RUN addgroup -g 1001 -S app && \
    adduser -S appuser -u 1001 -G app && \
    chown -R appuser:app /app

USER appuser

# Puerto expuesto por la aplicación
EXPOSE 8080

# Definir punto de entrada
ENTRYPOINT ["/app/server"]