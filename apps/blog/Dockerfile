FROM ruby:3.3-slim AS dev

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/

WORKDIR /srv/jekyll

# Install gems
COPY jekyll-site/Gemfile jekyll-site/Gemfile.lock* ./

# Configure Bundler via ENV (Persists across volume mounts)
ENV BUNDLE_FORCE_RUBY_PLATFORM=true \
    BUNDLE_JOBS=4 \
    BUNDLE_RETRY=3

RUN gem install bundler && \
    bundle install

# Copy site content and build
COPY jekyll-site/ .

EXPOSE 4000

CMD ["bundle", "exec", "jekyll", "serve", "--host", "0.0.0.0", "--port", "4000"]
