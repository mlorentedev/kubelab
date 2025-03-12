# Project Scripts

## Overview

This directory contains utility scripts for managing the development, deployment, and configuration of the mlorente.dev project.

## Prerequisites

- Bash shell
- GitHub CLI (`gh`)
- Docker
- Docker Compose
- SSH key pair

## Scripts

### 1. `dev-setup.sh`

Configures local development environment for the project.

#### Usage

```bash
./dev-setup.sh
```

#### Features

- Checks Docker and Docker Compose installation
- Creates `.env.dev` file
- Generates development Docker Compose configuration
- Prepares Dockerfiles for frontend and backend
- Configures hot-reload for backend

### 2. `setup-github-secrets.sh`

Helps configure GitHub repository secrets.

#### Prerequisites

- Authenticated GitHub CLI (`gh auth login`)
- Access to repository

#### Usage

```bash
./setup-github-secrets.sh
```

#### Features

- Interactively set GitHub secrets
- Supports configuration for different environments
- Covers various secret types (SSH, DockerHub, server configs)

### 3. `setup-hetzner.sh`

Configures Hetzner server for staging or production.

#### Usage

```bash
./setup-hetzner.sh [production|staging]
```

#### Features

- Server configuration for different environments
- Firewall and security setup
- Docker and deployment user configuration
- SSL certificate generation option

### 4. `ssh-key-management.sh`

Comprehensive SSH key management tool.

#### Usage

```bash
./ssh-key-management.sh
```

#### Features

- Generate SSH keys
- Add keys to servers
- Configure GitHub secrets
- Generate SSH config
- Interactive menu-driven interface

## Security Recommendations

- Use strong, unique passphrases for SSH keys
- Limit SSH key permissions
- Regularly rotate SSH keys
- Use key-based authentication
- Disable password login on servers

## Troubleshooting

- Ensure all scripts have executable permissions: `chmod +x *.sh`
- Verify dependencies are installed
- Check GitHub CLI authentication
- Confirm server connectivity before setup

## Contributing

- Do not modify scripts without careful review
- Test changes in a staging environment
- Update documentation when making modifications

## Contact

Manuel Lorente - mlorentedev@gmail.com