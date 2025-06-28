# ---------- Build Stage ----------
FROM node:20-alpine AS build

RUN apk update && apk upgrade --no-cache

WORKDIR /app

ENV npm_config_omit=optional \
    ROLLUP_NATIVE_DISABLE=true

# Copiar sólo los archivos de dependencias
COPY astro-site/package.json astro-site/package-lock.json ./

# Instalar dependencias con caché
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Copiar el resto del código fuente
COPY astro-site/ ./

# Variable de entorno (opcional)
ARG BUILD_ENV=production
ENV NODE_ENV=${BUILD_ENV}

RUN npm install @rollup/rollup-linux-arm64-musl --no-save || true

# Construir la aplicación
RUN --mount=type=cache,target=/root/.npm \
    npm run build

# ---------- Runtime Stage ----------
FROM node:20-alpine AS runtime

RUN apk update && apk upgrade --no-cache

WORKDIR /app

# ⚠️  Mantener la omisión de optionalDependencies en runtime
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
CMD ["node", "./dist/server/entry.mjs"]
