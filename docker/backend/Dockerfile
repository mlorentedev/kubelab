FROM golang:1.21-alpine AS builder

# Install air for hot reload
RUN go install github.com/cosmtrek/air@latest

WORKDIR /app

# Copiar los archivos de módulos y descargar dependencias
COPY go.mod go.sum ./
RUN go mod download

# Copiar el código fuente
COPY backend/ .

# Construir la aplicación
RUN CGO_ENABLED=0 GOOS=linux go build -o server ./cmd/server

# Imagen final minimalista
FROM alpine:latest

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

# Copiar el ejecutable
COPY --from=builder /app/server .

# Exponer el puerto
EXPOSE 8080

# Comando por defecto
CMD ["/app/server"]