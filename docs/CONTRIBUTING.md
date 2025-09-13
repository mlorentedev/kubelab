# 4.5 Contributing

Guidelines for contributing to mlorente.dev.

## Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Setup development environment: `make install-precommit-hooks && make up`
4. Make your changes
5. Test locally: `make test`
6. Submit a pull request

## Development Setup

```bash
# Clone and setup
git clone <your-fork>
cd mlorente.dev
make install-precommit-hooks

# Start services
make up

# Development with hot reload
make api-dev     # Go API
make web-dev     # Astro frontend  
make blog-dev    # Jekyll blog
```

## Code Standards

### Commit Messages

Use [Conventional Commits](https://conventionalcommits.org/):

```
feat: add new feature
fix: resolve bug
docs: update documentation
style: format code
refactor: restructure code
test: add tests
chore: update dependencies
```

### Branch Naming

```
feature/short-description
fix/bug-description  
docs/what-changed
refactor/component-name
```

### Code Style

**Go (API):**
- Use `gofmt` and `golint`
- Follow standard Go conventions
- Add tests for new features

**JavaScript/TypeScript (Web):**
- Use Prettier and ESLint
- Follow existing component patterns
- Add TypeScript types

**Jekyll (Blog):**
- Use Jekyll conventions
- Test locally before submitting
- Follow markdown style guide

## Pull Requests

### Before Submitting

- [ ] Code follows style guidelines
- [ ] Tests pass locally: `make test`
- [ ] Pre-commit hooks pass
- [ ] Documentation updated if needed
- [ ] Commit messages follow conventional format

### PR Description

Include:
- What changed and why
- How to test the changes
- Any breaking changes
- Screenshots if UI changes

## Testing

```bash
# Run all tests
make test

# Test specific app
make api-test
make web-test  
make blog-test

# Integration tests
make test-integration
```

## Docker Guidelines

### Dockerfile Best Practices

- Use multi-stage builds
- Minimize layer count
- Use specific base image tags
- Don't run as root user
- Clean up package caches

Example:
```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

FROM node:20-alpine
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001
WORKDIR /app
COPY --from=builder --chown=nodejs:nodejs /app .
USER nodejs
EXPOSE 3000
CMD ["node", "server.js"]
```

## Documentation

- Update relevant docs when changing functionality
- Use clear, concise language
- Include code examples
- Test documentation steps

## Environment Variables

Add new environment variables to:
- `.env.example`
- `docker-compose.yml`
- Documentation
- Ansible playbooks if needed

## Release Process

1. Changes are automatically built on merge to main
2. Images are tagged and pushed to registry
3. Deployment is manual: `make deploy ENV=production`
4. Create GitHub release for major versions

## Questions?

- Check existing [issues](https://github.com/user/repo/issues)
- Review documentation in `docs/`
- Create a new issue for bugs or feature requests

Thank you for contributing! 🚀