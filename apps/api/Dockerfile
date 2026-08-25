# Build Stage — CI v2 (build-args from YAML config)
FROM golang:1.27-alpine AS build

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
# Pin a supported release: 3.18 reached EOL (no security updates -> Trivy
# HIGH/CRITICAL on patched-elsewhere CVEs). 3.24 is the current stable.
FROM alpine:3.24 AS runtime

WORKDIR /app

# THIS STAGE IS WHAT TRIVY SCANS, and the builder above is not. The gate judges
# the shipped artifact: this base, the packages added here, and the Go binary
# copied in. A Dependabot bump of `golang:*-alpine` therefore cannot change the
# scan result — measured 2026-08-24, when exactly that bump (#1358) was blamed
# for a CVE it could not have introduced (#1385).
#
# `apk upgrade` before `add`, matching edge/errors: the base image tag is
# rebuilt upstream on its own schedule, so pulling from Alpine's live index at
# build time is what closes the window between a package fix shipping and a new
# base appearing. It does NOT close the other window — nothing rebuilds this
# image unless its source changes, so a package set freezes at build time
# regardless (#1385 AC3).
RUN apk --no-cache upgrade && \
    apk --no-cache add ca-certificates tzdata curl && \
    update-ca-certificates

# Copy the compiled executable from the build stage
COPY --from=build /app/server ./

# Create non-root user for security
RUN addgroup -g 1001 -S app && \
    adduser -S appuser -u 1001 -G app && \
    chown -R appuser:app /app

# Numeric, not `appuser`: a name is resolved inside the image, and a Kubernetes
# `runAsNonRoot` check is made outside it — with a name the kubelet cannot tell
# whether the user is root and refuses to start the pod. Same uid the adduser
# above creates (hadolint DL3066).
USER 1001

# Port exposed by the application
EXPOSE 8080

# Define entry point
ENTRYPOINT ["/app/server"]
