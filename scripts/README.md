# mlorente.dev Deployment & Management Scripts

This directory contains a comprehensive set of scripts for managing the mlorente.dev project throughout its lifecycle - from initial development setup to production deployment and monitoring.

## Common Utilities

All scripts use a shared utilities library that provides consistent functions for:

- Logging and colors
- Environment validation
- Server connectivity checks
- Dependency verification
- User confirmation prompts
- SSH key management
- Error handling

## Setup Scripts

### Development Environment

- **`setup-dev.sh`** - Sets up the local development environment
  - Creates development configuration files (.env.*, docker-compose.dev.yml)
  - Creates Docker configuration for frontend and backend
  - Initializes basic project structure
  - Starts development services
  - **Usage:** `./setup-dev.sh`

### CI/CD Configuration

- **`setup-secrets.sh`** - Configures GitHub repository secrets for CI/CD
  - Sets up deployment credentials
  - Configures environment variables for all environments
  - Sets API keys and integration tokens
  - **Usage:** `./setup-secrets.sh`

- **`setup-ssh.sh`** - Comprehensive SSH key management
  - Generates SSH keys for deployment
  - Adds keys to servers
  - Configures GitHub secrets for SSH keys
  - Creates SSH config entries
  - **Usage:** `./setup-ssh.sh`

### Server Configuration

- **`setup-server.sh`** - Configures a new server for deployment
  - Installs required packages (Docker, Nginx, etc.)
  - Sets up security (firewall, fail2ban)
  - Creates deployment user with proper permissions
  - Configures SSL with Let's Encrypt
  - Creates application directory structure
  - **Usage:** `./setup-server.sh <server_ip> <environment>`
  - **Example:** `./setup-server.sh 123.456.789.0 production`


## Deployment Scripts

### Deployment Management

- **`deploy-app.sh`** - Deploys the application to staging or production
  - Pulls the latest code from the repository
  - Backs up existing configuration
  - Updates Docker containers
  - Verifies deployment success
  - **Usage:** `./deploy-app.sh <environment> [version]`
  - **Example:** `./deploy-app.sh production v1.2.3`

- **`deploy-rollback.sh`** - Rolls back to a previous version
  - Lists available versions if none specified
  - Creates backups before rollback
  - Verifies successful rollback
  - **Usage:** `./deploy-rollback.sh <environment> [version]`
  - **Example:** `./deploy-rollback.sh production v1.1.0`

### Configuration Management

- **`config-update.sh`** - Updates environment variables on the server
  - Validates critical variables
  - Creates a backup of previous configuration
  - Restarts services after updating
  - **Usage:** `./config-update.sh <environment>`
  - **Example:** `./config-update.sh staging`

## Monitoring & Diagnostic Scripts

### Status Monitoring

- **`monitor-status.sh`** - Checks the status of all services
  - Displays system information (CPU, memory, disk)
  - Shows container status and health
  - Displays recent logs
  - Verifies application accessibility
  - **Usage:** `./monitor-status.sh <environment>`
  - **Example:** `./monitor-status.sh production`

### Log Analysis

- **`monitor-logs.sh`** - Analyzes application logs
  - Shows most visited URLs
  - Displays error summaries
  - Analyzes API endpoint usage
  - Identifies error patterns
  - **Usage:** `./monitor-logs.sh <environment> [service]`
  - **Example:** `./monitor-logs.sh production nginx`

### Security Checks

- **`monitor-security.sh`** - Performs comprehensive security audit
  - Checks server configuration (firewall, SSH, etc.)
  - Validates SSL certificates
  - Tests HTTP security headers
  - Identifies potential vulnerabilities
  - **Usage:** `./monitor-security.sh <environment>`
  - **Example:** `./monitor-security.sh production`

### Performance Testing

- **`monitor-performance.sh`** - Runs performance tests against the application
  - Measures response times and latency
  - Performs load testing with various concurrency levels
  - Generates detailed performance reports
  - **Usage:** `./monitor-performance.sh <environment> [path]`
  - **Example:** `./monitor-performance.sh staging /api/subscribe`

## Workflow Examples

### New Project Setup

1. Initial setup:

   ```bash
   # Set up development environment
   ./setup-dev.sh
   
   # Develop and test locally
   cd frontend
   npm run dev
   ```

2. Server preparation:

   ```bash
   # Generate SSH keys
   ./setup-ssh.sh
   
   # Configure new server
   ./setup-server.sh 123.456.789.0 staging
   
   # Configure GitHub secrets for CI/CD
   ./setup-secrets.sh
   ```

3. Initial deployment:

   ```bash
   # Update environment configuration
   ./config-update.sh staging
   
   # Deploy application
   ./deploy-app.sh staging
   ```

### Regular Operations

1. Deployment:

   ```bash
   # Deploy to staging
   ./deploy-app.sh staging
   
   # Check status after deployment
   ./monitor-status.sh staging
   
   # Deploy to production
   ./deploy-app.sh production
   ```

2. Monitoring:

   ```bash
   # Check service status
   ./monitor-status.sh production
   
   # Analyze logs
   ./monitor-logs.sh production
   
   # Check security
   ./monitor-security.sh production
   
   # Test performance
   ./monitor-performance.sh production
   ```

3. Troubleshooting:

   ```bash
   # Check for errors
   ./monitor-logs.sh production
   
   # Rollback if necessary
   ./deploy-rollback.sh production v1.2.0
   ```

## Requirements

- Bash 4.0+
- SSH access to servers
- Git
- Docker and Docker Compose
- Apache Benchmark (`ab`) for performance testing
- GitHub CLI (`gh`) for secrets management

## Script Naming Convention

The scripts follow a consistent naming pattern for easier navigation:

- **`setup-*`**: Scripts for setting up environments and infrastructure
- **`deploy-*`**: Scripts for deployment and release management
- **`config-*`**: Scripts for configuration management
- **`monitor-*`**: Scripts for monitoring, diagnostics, and testing

## Best Practices

1. Always run scripts from the project root directory
2. Keep a log of deployment versions for easy rollback
3. Regularly check security and performance
4. Review and update environment variables when needed
5. Always back up configuration before making changes

## Maintenance

These scripts are designed to be maintainable and extensible:

- Common functions are in `utils.sh` to reduce duplication
- All scripts use a consistent parameter validation pattern
- Error handling is implemented throughout
- Clear documentation within each script

## License

These scripts are part of the mlorente.dev project and are licensed under the same terms as the project itself.
