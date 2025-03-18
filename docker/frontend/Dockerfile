# Build Stage
FROM node:20-alpine AS build

WORKDIR /app

# Copiar solo los archivos necesarios para instalar dependencias
COPY frontend/package.json frontend/package-lock.json ./

# Instalar dependencias con cache optimizado
RUN npm ci

# Copiar el resto del código fuente
COPY frontend/ ./
COPY frontend/.env ./.env

# Configuración de environment (si es necesario)
ARG BUILD_ENV=production
ENV NODE_ENV=${BUILD_ENV}

# Construir la aplicación
RUN npm run build

# Runtime Stage
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production

# Copiar solo los archivos necesarios de la etapa de build
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./
COPY --from=build /app/package-lock.json ./
COPY --from=build /app/.env ./.env

# Instalar solo las dependencias de producción
RUN npm ci --omit=dev

# Configurar usuario no-root para seguridad
RUN addgroup -g 1001 -S nodejs && \
    adduser -S astro -u 1001 && \
    chown -R astro:nodejs /app

USER astro

# Puerto expuesto por la aplicación
EXPOSE 4321

# Comando para iniciar la aplicación
CMD ["node", "./dist/server/entry.mjs"]