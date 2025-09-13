# 1.2 Web - Frontend Portfolio

The main frontend website for [mlorente.dev](https://mlorente.dev) - my personal portfolio and landing page. Built with Astro for maximum performance and developer experience.

## What it is

This is my personal website where I showcase my portfolio, share downloadable resources, and provide information about what I do. I chose Astro because it handles SSR and SSG perfectly, it's fast, and doesn't ship unnecessary JavaScript to users.

The site includes my portfolio projects, lead magnets like DevOps checklists, newsletter signup forms, and contact information - all integrated with my Go API backend.

## Tech stack

- **Astro 5.5.2** - Modern meta-framework for content-focused sites
- **TypeScript** - Static typing for better development experience  
- **Tailwind CSS** - Utility-first CSS framework for rapid styling
- **MDX** - Markdown with JSX for dynamic content creation
- **Docker** - Containerized for consistent deployment

## Project structure

```
astro-site/
├── astro.config.mjs          # Astro configuration
├── package.json              # Dependencies and scripts
├── tailwind.config.mjs       # Tailwind customization
├── public/                   # Static assets
├── src/
│   ├── components/           # Reusable UI components
│   │   ├── forms/           # Contact and subscription forms
│   │   ├── sections/        # Page sections
│   │   └── ui/             # Base UI components
│   ├── content/            # Content collections
│   │   ├── projects/       # Portfolio projects
│   │   └── resources/      # Downloadable resources
│   ├── layouts/            # Page layouts
│   ├── pages/              # Routes and pages
│   └── styles/             # Global styles
└── Dockerfile              # Container definition
```

## Key features

### For visitors
- **Lightning fast loading** - Thanks to Astro's partial hydration
- **Interactive portfolio** - Projects with demos and GitHub links
- **Free resources** - Lead magnets with integrated download forms
- **Newsletter signup** - Connected to my API for subscriptions
- **Fully responsive** - Works great on mobile, tablet, and desktop

### For development
- **Full TypeScript** - Type safety across the entire codebase
- **Content collections** - Projects and resources are typed and validated
- **Modern architecture** - Astro components without the complexity
- **Automatic optimization** - Image compression and multiple formats
- **Smart caching** - Static assets cache efficiently

## Configuration

### Environment variables

```bash
# Server configuration
PORT=4321
HOST=0.0.0.0
NODE_ENV=production

# API integration
API_BASE_URL=https://api.mlorente.dev
API_TIMEOUT=5000

# Feature flags
ENABLE_ANALYTICS=true
ENABLE_NEWSLETTER=true
```

## Running the website

### Development mode

```bash
# Navigate to the web app
cd apps/web/astro-site

# Install dependencies
npm install

# Copy environment configuration
cp .env.example .env

# Start development server
npm run dev

# Access at http://localhost:4321
```

### With Docker

```bash
# Development with hot reload
make up-web

# Production build
docker-compose -f docker-compose.prod.yml up -d
```

### Available commands

```bash
# Development with hot reload
npm run dev

# Production build
npm run build

# Preview production build
npm run preview

# Type checking
npm run type-check

# Code quality
npm run lint
npm run format
```

## Adding content

### New portfolio project

Create a new MDX file in `src/content/projects/`:

```markdown
---
title: "My Awesome Project"
description: "A brief description that sells the project"
technologies: ["Astro", "TypeScript", "Tailwind"]
github: "https://github.com/mlorentedev/project"
demo: "https://project.mlorente.dev"
image: "/images/projects/project.jpg"
featured: true
date: 2024-01-15
---

## What the project does

Here I explain what it does, why I built it, and how it works...

### What I'm most proud of

- Key feature 1
- Key feature 2  
- Key feature 3

### Technical challenges I solved

There's always some interesting problem to tackle...
```

### New downloadable resource

Create a new MDX file in `src/content/resources/`:

```markdown
---
title: "DevOps Checklist"
description: "Everything you need to check before deployment"
category: "DevOps"
fileType: "PDF"
fileSize: "2.3 MB"
downloadCount: 0
tags: ["devops", "checklist", "automation"]
featured: true
gated: true  # Requires email for download
---

Description of what they'll download and why it's useful...
```

## Design system

I use Tailwind with custom configurations:

```javascript
// tailwind.config.mjs
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          500: '#3b82f6',
          900: '#1e3a8a'
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif']
      }
    }
  }
}
```

### Reusable components

```astro
---
// src/components/ui/Button.astro
interface Props {
  variant?: 'primary' | 'secondary';
  size?: 'sm' | 'md' | 'lg';
}

const { variant = 'primary', size = 'md' } = Astro.props;
---

<button 
  class:list={[
    'font-semibold rounded-lg transition-colors',
    {
      'bg-primary-500 text-white hover:bg-primary-600': variant === 'primary',
      'bg-gray-200 text-gray-900 hover:bg-gray-300': variant === 'secondary',
      'px-3 py-2 text-sm': size === 'sm',
      'px-4 py-2': size === 'md',
      'px-6 py-3 text-lg': size === 'lg'
    }
  ]}
>
  <slot />
</button>
```

## Analytics and tracking

The website includes comprehensive tracking:

- **Google Analytics** - Traffic and user behavior analysis
- **Form tracking** - Download and conversion metrics
- **Newsletter metrics** - Subscription rates and sources
- **Core Web Vitals** - Performance monitoring

## Security measures

- **Server-side validation** - All forms validate through the API
- **Security headers** - CSP, HSTS, and other protection headers
- **Rate limiting** - Prevents form spam and abuse
- **Input sanitization** - All user input is cleaned and validated

## SEO optimization

- **Dynamic meta tags** - Each page has unique titles and descriptions
- **Structured data** - JSON-LD for better search engine understanding
- **Automatic sitemap** - Generated during build process
- **Canonical URLs** - Prevents duplicate content issues
- **Image alt text** - Accessibility and SEO compliance

## API integration

Forms connect to my Go API backend:

```typescript
// Newsletter subscription
POST /api/subscribe
{
  "email": "user@example.com",
  "tags": ["newsletter", "website"]
}

// Resource download
POST /api/lead-magnet  
{
  "email": "user@example.com",
  "resource_id": "devops-checklist",
  "utm_source": "website"
}

// Contact form
POST /api/contact
{
  "name": "Name",
  "email": "email@example.com", 
  "message": "The message"
}
```

## Contributing

1. Fork the repository
2. Make changes following TypeScript/Astro conventions
3. Test everything locally
4. Update documentation for new features
5. Ensure Docker build works
6. Submit pull request

## Key dependencies

### Core framework
- **@astrojs/node** - Node.js adapter for server-side rendering
- **astro** - The meta-framework itself
- **typescript** - Static type checking

### Styling and UI
- **@astrojs/tailwind** - Tailwind CSS integration
- **tailwindcss** - Utility-first CSS framework

### Content management
- **@astrojs/mdx** - MDX support for dynamic content
- **zod** - Runtime type validation for content collections

## Local development URLs

When running locally with `make up-web`:
- Website: http://mlorentedev.test
- Development server: http://localhost:4321

Add `127.0.0.1 mlorentedev.test` to your `/etc/hosts` file for local domain access.