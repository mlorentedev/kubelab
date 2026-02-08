# Stage 1: Build the MkDocs site
FROM python:3.10-slim-buster AS builder

WORKDIR /app

# Install MkDocs and its theme
RUN pip install \
    mkdocs \
    mkdocs-material \
    pymdown-extensions \
    mkdocs-glightbox \
    mkdocs-minify-plugin \
    mkdocs-git-revision-date-localized-plugin

ARG CACHE_BREAKER=1 # Forced cache invalidation

# Copy source and generated mkdocs.yml
COPY ./generated_docs ./generated_docs
COPY mkdocs.yml .

# Build the site
RUN mkdocs build --verbose

# Stage 2: Serve the site with Nginx
FROM nginx:alpine

# Copy Nginx configuration
COPY default.conf /etc/nginx/conf.d/default.conf

# Copy the built site from the builder stage
COPY --from=builder /app/site /usr/share/nginx/html/

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
