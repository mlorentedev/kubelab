# Build Stage
FROM golang:1.23-alpine AS build

WORKDIR /app

# Instalar herramientas esenciales
RUN apk add --no-cache git ca-certificates tzdata && \
    update-ca-certificates

# Copiar archivos de módulos y descargar dependencias
COPY backend/go.mod backend/go.sum ./
RUN go mod download

# Copiar el código fuente
COPY backend/ ./

# Compilar la aplicación con optimizaciones
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-w -s" -o server ./cmd/server

# Runtime Stage - usando alpine mínimo
FROM alpine:3.18 AS runtime

WORKDIR /app

# Instalar certificados y zona horaria
RUN apk --no-cache add ca-certificates tzdata && \
    update-ca-certificates

# Copiar el ejecutable compilado desde la etapa de build
COPY --from=build /app/server ./
COPY --from=build /app/.env ./

# Crear usuario no-root para seguridad
RUN addgroup -g 1001 -S app && \
    adduser -S appuser -u 1001 -G app && \
    chown -R appuser:app /app

USER appuser

# Puerto expuesto por la aplicación
EXPOSE 8080

# Definir punto de entrada
ENTRYPOINT ["/app/server"]