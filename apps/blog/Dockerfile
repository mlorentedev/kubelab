FROM ruby:3.1-alpine

# Add Jekyll dependencies to Alpine
RUN apk update && \
    apk add --no-cache \
        build-base \
        gcc \
        cmake \
        git \
        musl-dev \
        linux-headers \
        libffi-dev \
        && gem update bundler \
        && gem install bundler -v 2.5.22

WORKDIR /srv/jekyll

# Copy only Gemfile(s) first
COPY jekyll-site/Gemfile* ./

RUN bundle config set --local force_ruby_platform true && \
    bundle install

COPY jekyll-site/ .

EXPOSE 4000

CMD ["bundle", "exec", "jekyll", "serve", "--host", "0.0.0.0", "--port", "4000"]
