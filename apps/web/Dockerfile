# ---------- Build Stage ----------
FROM node:20-alpine AS build

# Declare build arguments for multi-arch support
ARG TARGETPLATFORM
ARG TARGETOS  
ARG TARGETARCH

RUN apk update && apk upgrade --no-cache

WORKDIR /app

# Configure npm to skip optional dependencies for faster builds
ENV npm_config_omit=optional

COPY astro-site/package.json astro-site/package-lock.json ./

# Instalar dependencias con caché
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Copiar el resto del código fuente
COPY astro-site/ ./

# Variable de entorno (opcional)
ARG BUILD_ENV=production
ENV NODE_ENV=${BUILD_ENV}

RUN --mount=type=cache,target=/root/.npm \
    case "$TARGETARCH" in \
      "amd64") \
        echo "Installing Rollup for AMD64..." && \
        npm install --no-save @rollup/rollup-linux-x64-musl ;; \
      "arm64") \
        echo "Installing Rollup for ARM64..." && \
        npm install --no-save @rollup/rollup-linux-arm64-musl ;; \
      *) \
        echo "Warning: Unknown architecture $TARGETARCH, skipping Rollup native binaries" ;; \
    esac

# Construir la aplicación
RUN --mount=type=cache,target=/root/.npm \
    npm run build

# ---------- Runtime Stage ----------
FROM node:20-alpine AS runtime

RUN apk update && apk upgrade --no-cache

WORKDIR /app

# Environment variables for runtime
ENV NODE_ENV=production \
    npm_config_omit=optional \
    ROLLUP_NATIVE_DISABLE=true

# Copiar artefactos desde la etapa de build
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./
COPY --from=build /app/package-lock.json ./

# Instalar SOLO dependencias de producción
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev && \
    npm cache clean --force

# Crear usuario no-root para seguridad
RUN addgroup -g 1001 -S nodejs && \
    adduser -S astro -u 1001 && \
    chown -R astro:nodejs /app

USER astro

EXPOSE 4321

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:4321/health || exit 1

# Start the application
CMD ["node", "./dist/server/entry.mjs"]
