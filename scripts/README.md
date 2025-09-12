# Project Scripts and Tools

Hey there! Here you'll find all the scripts that help me keep this project running without headaches. They're my little automated helpers that take care of the heavy lifting.

## What you'll find here

### **wiki.sh** - The documentation generator

My favorite script for automatically generating the wiki. It collects all the markdown content from the monorepo and organizes it nicely.

**What does it do?**

- Collects all README and markdown documents
- Organizes them by sections (apps, infra, guides)
- Automatically generates indices with sequential numbering
- Creates the static site with MkDocs Material

**How to use it:**

```bash
# Generate the complete wiki
./scripts/wiki.sh build-all

# Just a specific branch
./scripts/wiki.sh build-one my-branch

# Clean everything and start fresh
./scripts/wiki.sh clean
```

### **utils.sh** - Common functions

The shared brain of all the other scripts. Here I have useful functions that I use in various places.

**Includes:**

- Logging functions with pretty colors
- Environment variable loading
- Common validations
- File handling utilities

### **env-setup.sh** - Initial setup

Sets up your entire development environment in one go. Perfect for when you're starting from scratch.

**Installs:**

- Node.js and npm
- Ruby and Bundler for Jekyll
- Go for the API
- Docker and Docker Compose
- Other necessary tools

```bash
./scripts/env-setup.sh
```

### **generate-traefik-config.sh** - Traefik configuration

Generates all Traefik configuration based on templates. Very useful when I add new services.

**Generates:**

- Dynamic configuration
- SSL certificates
- Routes and middleware
- Environment-specific configuration

### **generate-ansible-config.sh** - Ansible configuration

Creates Ansible inventories and configurations for deployments.

**Generates:**

- Inventories per environment
- Group variables
- Server-specific configurations

### **setup-gh-secrets.sh** - GitHub secrets

Syncs variables from the `.env` file with GitHub Actions secrets. Very handy for CI/CD.

```bash
./scripts/setup-gh-secrets.sh production
```

### **create-env-example.sh** - Configuration examples

Generates `.env.example` files based on the real `.env` files, but without the sensitive values.

### **generate-traefik-credentials.sh** - Traefik credentials

Generates basic credentials to securely access the Traefik dashboard.

### **replace-placeholders.sh** - Replace placeholders

Utility to substitute placeholders in configuration files. I use it in several scripts.

## 🚀 How to use the scripts

### Prepare the environment (first time)

```bash
# Install all necessary tools
./scripts/env-setup.sh

# Generate initial configurations
./scripts/generate-traefik-config.sh
./scripts/generate-ansible-config.sh
```

### Generate documentation

```bash
# Complete wiki
./scripts/wiki.sh build-all

# Just a specific branch
./scripts/wiki.sh build-one develop
```

### Set up CI/CD

```bash
# Upload secrets to GitHub
./scripts/setup-gh-secrets.sh production

# Create example files
./scripts/create-env-example.sh
```

## 💡 Tips and tricks

**For developers:**

- All scripts use `set -euo pipefail` to be more robust
- They load environment variables automatically
- They have colored logging to make debugging easier
- They're internally documented with comments

**For users:**

- If a script fails, check that you have all environment variables configured
- Colored logs help you understand what's happening
- You can run `./script.sh --help` on most of them to see options

## 🔧 Dependencies

Most scripts need:

- **zsh** - Default shell
- **Docker** and **Docker Compose**
- **jq** - For processing JSON
- **gh CLI** - To interact with GitHub (optional)

## 📝 Important notes

- **Always check environment variables** before running scripts
- **Scripts modify files** - make backups if it's critical
- **Some require administrator permissions** to install packages
- **They're optimized for Ubuntu/Debian** but should work on other distributions

---

> **Pro tip:** If you're going to modify any script, take a look at `utils.sh` first. I probably already have a function that does what you need.
