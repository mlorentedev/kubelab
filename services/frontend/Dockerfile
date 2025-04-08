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

# Set the working directory inside the container
WORKDIR /srv/jekyll

# Copy Gemfile first and install dependencies
COPY Gemfile* ./
RUN bundle config set --local force_ruby_platform true && \
    bundle install

# Copy the entire Jekyll site into the container
COPY . .

# Expose port for the Jekyll site
EXPOSE 4000

# Command to run the Jekyll server
CMD ["bundle", "exec", "jekyll", "serve", "--host", "0.0.0.0", "--port", "4000"]