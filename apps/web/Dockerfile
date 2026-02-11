# ---------- Build Stage ----------
FROM node:22-alpine AS build

# Declare build arguments for multi-arch support
ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH

# Astro-specific build arguments (passed from docker-compose)
ARG PUBLIC_ALLOWED_HOSTS
ARG PUBLIC_SITE_TITLE
ARG PUBLIC_SITE_DESCRIPTION
ARG PUBLIC_SITE_DOMAIN
ARG PUBLIC_SITE_URL
ARG PUBLIC_SITE_MAIL
ARG PUBLIC_SITE_AUTHOR
ARG PUBLIC_SITE_KEYWORDS
ARG PUBLIC_TWITTER_URL
ARG PUBLIC_YOUTUBE_URL
ARG PUBLIC_GITHUB_URL
ARG PUBLIC_CALENDLY_URL
ARG PUBLIC_BUY_ME_A_COFFEE_URL
ARG PUBLIC_GOOGLE_ANALYTICS_ID
ARG PUBLIC_GOOGLE_TAG_MANAGER_ID
ARG PUBLIC_ENABLE_HOMELABS
ARG PUBLIC_ENABLE_BLOG
ARG PUBLIC_ENABLE_CONTACT
ARG BACKEND_URL

# System packages (requires root)
RUN apk update && apk upgrade --no-cache && \
    apk add --no-cache curl

WORKDIR /app
RUN chown node:node /app

# Configure npm to skip optional dependencies for faster builds
ENV npm_config_omit=optional

# Make Astro-specific build arguments available as environment variables for the build process
ENV PUBLIC_ALLOWED_HOSTS=${PUBLIC_ALLOWED_HOSTS}
ENV PUBLIC_SITE_TITLE=${PUBLIC_SITE_TITLE}
ENV PUBLIC_SITE_DESCRIPTION=${PUBLIC_SITE_DESCRIPTION}
ENV PUBLIC_SITE_DOMAIN=${PUBLIC_SITE_DOMAIN}
ENV PUBLIC_SITE_URL=${PUBLIC_SITE_URL}
ENV PUBLIC_SITE_MAIL=${PUBLIC_SITE_MAIL}
ENV PUBLIC_SITE_AUTHOR=${PUBLIC_SITE_AUTHOR}
ENV PUBLIC_SITE_KEYWORDS=${PUBLIC_SITE_KEYWORDS}
ENV PUBLIC_TWITTER_URL=${PUBLIC_TWITTER_URL}
ENV PUBLIC_YOUTUBE_URL=${PUBLIC_YOUTUBE_URL}
ENV PUBLIC_GITHUB_URL=${PUBLIC_GITHUB_URL}
ENV PUBLIC_CALENDLY_URL=${PUBLIC_CALENDLY_URL}
ENV PUBLIC_BUY_ME_A_COFFEE_URL=${PUBLIC_BUY_ME_A_COFFEE_URL}
ENV PUBLIC_GOOGLE_ANALYTICS_ID=${PUBLIC_GOOGLE_ANALYTICS_ID}
ENV PUBLIC_GOOGLE_TAG_MANAGER_ID=${PUBLIC_GOOGLE_TAG_MANAGER_ID}
ENV PUBLIC_ENABLE_HOMELABS=${PUBLIC_ENABLE_HOMELABS}
ENV PUBLIC_ENABLE_BLOG=${PUBLIC_ENABLE_BLOG}
ENV PUBLIC_ENABLE_CONTACT=${PUBLIC_ENABLE_CONTACT}
ENV BACKEND_URL=${BACKEND_URL}

COPY --chown=node:node astro-site/package.json astro-site/package-lock.json ./

# Switch to non-root user (node:alpine ships with `node` user, UID/GID 1000)
USER node

# Install dependencies with cache
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 \
    npm ci

# Copy the rest of the source code
COPY --chown=node:node astro-site/ ./

# Environment variable (optional)
ARG BUILD_ENV=production
ENV NODE_ENV=${BUILD_ENV}

RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 \
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

# Build the application
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 npm run build \
 && npm audit --omit=dev --audit-level=high || true

#---------- Runtime Stage ----------
FROM node:22-alpine AS runtime

RUN apk update && apk upgrade --no-cache

WORKDIR /app

# Environment variables for runtime
ENV HOST=0.0.0.0 \
    NODE_ENV=production \
    npm_config_omit=optional \
    ROLLUP_NATIVE_DISABLE=true

# Copy built files and package files from build stage
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./
COPY --from=build /app/package-lock.json ./

#Install ONLY production dependencies
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev && \
    npm cache clean --force

# Install curl for health checks
RUN apk add --no-cache curl

# Create non-root user for security
RUN addgroup -g 1001 -S nodejs && \
    adduser -S astro -u 1001 -G nodejs && \
    chown -R astro:nodejs /app

USER astro

EXPOSE 4321

# Start the application
CMD ["node", "./dist/server/entry.mjs"]
