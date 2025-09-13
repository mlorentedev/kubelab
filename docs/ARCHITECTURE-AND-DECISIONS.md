# 4.1 Architecture and Decision Records

This document captures the architectural decisions made for the mlorente.dev project. These decisions help understand why the system is built this way and provide context for future changes.

## Decision Records Index

| ADR | Title | Status | Date | Impact |
|-----|--------|--------|-------|---------|
| ADR-001 | Monorepo Structure | Accepted | 2024-01 | High |
| ADR-002 | Docker Containerization | Accepted | 2024-01 | High |
| ADR-003 | Traefik as Reverse Proxy | Accepted | 2024-02 | High |
| ADR-004 | GitHub Actions for CI/CD | Accepted | 2024-02 | High |
| ADR-005 | Multi-Architecture Builds | Accepted | 2024-03 | Medium |
| ADR-006 | Manual CD Strategy | Accepted | 2024-03 | Medium |
| ADR-007 | Ansible for Deployments | Accepted | 2024-04 | High |
| ADR-008 | Selective App Builds | Accepted | 2024-04 | Medium |
| ADR-009 | Automatic Semantic Versioning | Accepted | 2024-05 | Medium |
| ADR-010 | Makefile as Unified Interface | Accepted | 2024-05 | Low |

## Current Technology Stack

### Frontend
- **Web App:** Astro + TypeScript + Tailwind CSS
- **Blog:** Jekyll + Beautiful Jekyll theme
- **Reverse Proxy:** Traefik with automatic SSL

### Backend
- **API:** Go 1.21 with standard library
- **Database:** File-based storage
- **Authentication:** JWT tokens

### Infrastructure
- **Containerization:** Docker + Docker Compose
- **Orchestration:** Ansible playbooks
- **CI/CD:** GitHub Actions (6 workflows, 1,388+ lines)
- **Registry:** Docker Hub with multi-arch builds

### Operations
- **Monitoring:** Vector + Prometheus + Grafana
- **Automation:** n8n for workflows
- **Management:** Portainer for container supervision
- **Networking:** Traefik for routing and SSL

## ADR-001: Monorepo Structure

**Status:** Accepted  
**Date:** 2024-01  
**Decision Makers:** mlorente

### Context
The project includes multiple applications (web, blog, API, wiki) and infrastructure components. We needed to decide between a monorepo or separate repositories.

### Decision
We chose a monorepo structure with all applications and infrastructure in a single repository.

### Reasons
- Simplified dependency management across services
- Easier to maintain consistent tooling and CI/CD
- Better visibility of changes across the entire system
- Simplified deployment coordination

### Consequences
**Positive:**
- Single source of truth for all project code
- Easier to implement cross-cutting changes
- Simplified CI/CD pipeline setup

**Negative:**
- Larger repository size
- Need careful CI/CD optimization to avoid building all apps on every change

## ADR-002: Docker Containerization

**Status:** Accepted  
**Date:** 2024-01  
**Decision Makers:** mlorente

### Context
Applications needed to be packaged for consistent deployment across development and production environments.

### Decision
All applications are containerized using Docker with multi-stage builds.

### Reasons
- Consistent runtime environment across all stages
- Simplified deployment process
- Better resource isolation
- Easy local development setup

### Consequences
**Positive:**
- Eliminated "works on my machine" problems
- Simplified production deployment
- Better resource management

**Negative:**
- Additional complexity in development setup
- Need Docker knowledge for contributors

## ADR-003: Traefik as Reverse Proxy

**Status:** Accepted  
**Date:** 2024-02  
**Decision Makers:** mlorente

### Context
Multiple services needed to be exposed through a single entry point with SSL termination.

### Decision
Use Traefik as the reverse proxy instead of Nginx or other alternatives.

### Reasons
- Automatic service discovery
- Automatic SSL certificate management with Let's Encrypt
- Better Docker integration
- Built-in load balancing

### Consequences
**Positive:**
- Zero-downtime SSL certificate renewal
- Automatic routing based on Docker labels
- Excellent monitoring and metrics

**Negative:**
- Learning curve for Traefik-specific configuration
- Dependency on Traefik for all traffic

## ADR-004: GitHub Actions for CI/CD

**Status:** Accepted  
**Date:** 2024-02  
**Decision Makers:** mlorente

### Context
The project needed automated testing, building, and deployment pipelines.

### Decision
Use GitHub Actions for all CI/CD processes instead of Jenkins, GitLab CI, or other solutions.

### Reasons
- Native integration with GitHub repository
- No additional infrastructure to maintain
- Rich ecosystem of pre-built actions
- Good performance and reliability

### Consequences
**Positive:**
- Simplified setup and maintenance
- Excellent integration with pull requests
- Free for public repositories

**Negative:**
- Vendor lock-in to GitHub
- Limited customization compared to self-hosted solutions

## ADR-005: Multi-Architecture Builds

**Status:** Accepted  
**Date:** 2024-03  
**Decision Makers:** mlorente

### Context
Applications needed to run on both AMD64 and ARM64 architectures for broader compatibility.

### Decision
Build Docker images for both AMD64 and ARM64 architectures using Docker Buildx.

### Reasons
- Support for Apple Silicon development machines
- Future-proofing for ARM-based server deployments
- Better development experience for all team members

### Consequences
**Positive:**
- Universal compatibility
- Better developer experience
- Prepared for ARM server migration

**Negative:**
- Longer build times
- Increased complexity in CI/CD

## ADR-006: Manual CD Strategy

**Status:** Accepted  
**Date:** 2024-03  
**Decision Makers:** mlorente

### Context
We needed to decide between automatic deployment to production or manual deployment.

### Decision
Images are built automatically, but deployment to production is manual.

### Reasons
- Better control over production deployments
- Ability to coordinate deployments with maintenance windows
- Reduced risk of problematic automatic deployments

### Consequences
**Positive:**
- Full control over when changes go live
- Ability to batch multiple changes
- Reduced risk of production issues

**Negative:**
- Requires manual intervention for deployments
- Potential for delayed releases

## ADR-007: Ansible for Deployments

**Status:** Accepted  
**Date:** 2024-04  
**Decision Makers:** mlorente

### Context
Production deployments needed to be automated and repeatable.

### Decision
Use Ansible for server configuration and application deployment.

### Reasons
- Idempotent operations
- Good Docker integration
- Readable YAML configuration
- Strong community support

### Consequences
**Positive:**
- Consistent server configurations
- Automated deployment process
- Easy to version control deployment procedures

**Negative:**
- Additional tool to learn and maintain
- SSH dependency for remote execution

## ADR-008: Selective App Builds

**Status:** Accepted  
**Date:** 2024-04  
**Decision Makers:** mlorente

### Context
Building all applications on every change was wasteful and slow.

### Decision
Implement selective building based on changed files and directories.

### Reasons
- Faster CI/CD pipeline execution
- Reduced resource usage
- Better developer experience

### Consequences
**Positive:**
- Significantly faster build times
- Reduced CI/CD costs
- More responsive development workflow

**Negative:**
- Complex change detection logic
- Risk of missing dependencies between apps

## ADR-009: Automatic Semantic Versioning

**Status:** Accepted  
**Date:** 2024-05  
**Decision Makers:** mlorente

### Context
Manual versioning was error-prone and inconsistent across applications.

### Decision
Implement automatic semantic versioning based on conventional commits.

### Reasons
- Consistent versioning across all applications
- Automatic changelog generation
- Clear communication of change impact

### Consequences
**Positive:**
- Consistent version numbering
- Automatic documentation of changes
- Clear breaking change communication

**Negative:**
- Requires discipline in commit message formatting
- Complex version calculation logic

## ADR-010: Makefile as Unified Interface

**Status:** Accepted  
**Date:** 2024-05  
**Decision Makers:** mlorente

### Context
Multiple tools and scripts needed a unified interface for common operations.

### Decision
Use a Makefile to provide a consistent interface for all common operations.

### Reasons
- Universal availability of make
- Simple syntax for common operations
- Self-documenting through help target

### Consequences
**Positive:**
- Consistent command interface
- Easy onboarding for new developers
- Self-documenting operations

**Negative:**
- Make syntax limitations
- Platform-specific behavior differences