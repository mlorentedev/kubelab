FROM node:20-alpine AS base

# Instalar dependencias solo cuando sea necesario
FROM base AS deps
WORKDIR /app

# Copia de files de package para instalación
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# Capa de construcción
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend .

# Usar .env de producción si existe
RUN if [ -f .env.production ]; then cp .env.production .env; fi

# Construir la aplicación
RUN npm run build

# Capa de producción
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production

# Copiar solo los archivos necesarios
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

EXPOSE 4321

CMD ["node", "./dist/server/entry.mjs"]