FROM ruby:3.1-slim

# Evita prompts interactivos
ENV DEBIAN_FRONTEND=noninteractive

# Instala dependencias de Jekyll
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    cmake \
    libffi-dev \
    libyaml-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Bundler moderno
RUN gem install bundler -v 2.5.22

WORKDIR /srv/jekyll

# Instala gems antes de copiar todo el proyecto (mejor cacheo)
COPY jekyll-site/Gemfile* ./

RUN bundle config set --local force_ruby_platform true && \
    bundle config set --local deployment false && \
    bundle install --jobs 4 --retry 3 --verbose

COPY jekyll-site/ .

EXPOSE 4000

CMD ["bundle", "exec", "jekyll", "serve", "--host", "0.0.0.0", "--port", "4000"]
