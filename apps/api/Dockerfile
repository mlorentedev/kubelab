# Build Stage
FROM golang:1.25-alpine AS build

WORKDIR /app

# Install essential tools
RUN apk add --no-cache git ca-certificates tzdata && \
    update-ca-certificates

# Install Air for hot reload in development
RUN apk add --no-cache git make bash
RUN go install github.com/air-verse/air@latest

# Copy module files and download dependencies
COPY src/go.mod src/go.sum ./

# Copy source code
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download
COPY src/ ./

# Build the application with optimizations
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 \
    go build -ldflags="-w -s" -o server ./cmd/server

# Runtime Stage - using minimal alpine
FROM alpine:3.18 AS runtime

WORKDIR /app

# Install certificates and timezone data
RUN apk --no-cache add ca-certificates tzdata curl && \
    update-ca-certificates

# Copy the compiled executable from the build stage
COPY --from=build /app/server ./

# Create non-root user for security
RUN addgroup -g 1001 -S app && \
    adduser -S appuser -u 1001 -G app && \
    chown -R appuser:app /app

USER appuser

# Port exposed by the application
EXPOSE 8080

# Define entry point
ENTRYPOINT ["/app/server"]
