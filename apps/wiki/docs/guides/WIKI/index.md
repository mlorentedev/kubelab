# 4.9 Wiki Management - Documentation Index

Complete guide for managing and maintaining the documentation wiki system.

## What it is

This section covers how to manage the MkDocs-powered documentation wiki, including content organization, generation processes, and maintenance procedures. The wiki system automatically collects content from across the monorepo and presents it in a unified, searchable format.

## Wiki structure

### Content sources
- **Application docs** - README files from `apps/*/`
- **Infrastructure docs** - README files from `infra/*/`
- **Guide documents** - Markdown files from `docs/`
- **Script documentation** - Auto-generated from script headers

### Generated structure
```
apps/wiki/docs/
├── index.md                 # Main landing page
├── apps/                    # Application documentation
├── infra/                   # Infrastructure documentation
├── guides/                  # User guides and tutorials
└── scripts/                 # Script documentation
```

## Management commands

### Generate wiki content

```bash
# Build complete wiki site
./scripts/generate-wiki.sh build

# Generate MkDocs config only
./scripts/generate-wiki.sh config

# Collect documentation without building
./scripts/generate-wiki.sh collect
```

### Local development

```bash
# Start wiki server
make up-wiki

# Access wiki
open http://wiki.mlorentedev.test

# Watch for changes
cd apps/wiki && mkdocs serve --watch-theme
```

## Content organization

### Writing guidelines
- Use clear, descriptive headers
- Include numbered sections for navigation
- Add practical examples and code blocks
- Cross-reference related documentation
- Keep content conversational and human

### File naming conventions
- Use kebab-case for file names
- Include `index.md` for section landing pages
- Use descriptive, searchable titles
- Organize by logical hierarchy

### Navigation structure
1. **Applications (1.x)** - All application documentation
2. **Infrastructure (2.x)** - Infrastructure and deployment
3. **Scripts (3.x)** - Automation and utility scripts
4. **Guides (4.x)** - Tutorials and how-to guides

## Automated processes

### Content collection
The wiki generation script automatically:
- Copies README files from apps and infra directories
- Transforms relative links to work in wiki context
- Generates navigation structure
- Creates index pages for each section

### MkDocs configuration
Auto-generated `mkdocs.yml` includes:
- Navigation hierarchy based on numbered sections
- Material Design theme configuration
- Search functionality
- Syntax highlighting
- Social sharing features

## Troubleshooting

### Wiki not building
1. Check MkDocs installation: `mkdocs --version`
2. Verify Python dependencies: `pip install -r requirements.txt`
3. Check for syntax errors: `mkdocs build --strict`
4. Review generation script logs

### Broken links
1. Use relative paths in source documents
2. Ensure target files exist
3. Check navigation structure in `mkdocs.yml`
4. Run link checker: `mkdocs build --strict`

### Content not updating
1. Regenerate wiki: `./scripts/generate-wiki.sh build`
2. Clear browser cache
3. Check file permissions
4. Restart MkDocs server

## Best practices

### Content maintenance
- Review documentation regularly for accuracy
- Update examples when code changes
- Fix broken links promptly
- Keep navigation structure logical

### Performance optimization
- Optimize images before including
- Use appropriate heading levels
- Limit page length for readability
- Use search-friendly titles

### SEO and discoverability
- Include relevant keywords in titles
- Use descriptive meta descriptions
- Add alt text to images
- Create logical internal linking

## Integration with development workflow

### Pre-commit hooks
Documentation updates are automatically checked for:
- Markdown formatting
- Broken links
- Image optimization
- Spelling errors

### CI/CD integration
Wiki generation is integrated into the deployment pipeline:
- Automatic builds on documentation changes
- Link validation in pull requests
- Performance testing for large sites
- SEO optimization checks

The wiki system provides a comprehensive, automatically-maintained documentation platform that scales with the project.