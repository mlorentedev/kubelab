 Toolkit - Modern Infrastructure Management CLI

A Python-based CLI for orchestrating the KubeLab ecosystem with centralized configuration and clean architecture.

 Philosophy

- Centralized Configuration: Single source of truth in `infra/config/env/`
- Environment-Aware: Dynamic configuration based on target environment
- Clean Architecture: Clear separation between commands, core, libs, and utils
- Type Safety: Full type hints with Pydantic for configuration management
- Maintainability: Well-organized modules with clear responsibilities

 Architecture

```text
toolkit/
├── commands/                  CLI Command Modules ( commands)
│   ├── apps.py               Application lifecycle management
│   ├── config.py             Configuration generation orchestration
│   ├── credentials.py        Secrets and credentials management
│   ├── deployment.py         Multi-environment deployment workflows
│   ├── edge.py               Edge services (DNS, proxy) management
│   ├── infra.py              Infrastructure health checks and status
│   ├── services.py           Service lifecycle management
│   ├── terraform.py          Terraform workflow wrapper
│   └── tools.py              Development utilities (env, templates, wiki)
├── config/                   Configuration Management System
│   ├── constants.py          Static constants, messages, and patterns
│   ├── environment.py        Environment-specific configuration loader
│   └── settings.py           Unified settings with environment integration
├── core/                     Core Framework Components
│   └── logging.py            Rich logging with environment awareness
├── lib/                      Shared Libraries
│   ├── generators.py         Config file generation (Traefik, Ansible, etc.)
│   └── system.py             System operations and validation utilities
├── utils/                    Utility Modules
│   ├── credentials.py        Authentication credential utilities
│   ├── env_manager.py        Environment file management and validation
│   ├── github_secrets.py     GitHub secrets synchronization
│   ├── template_processor.py  Jinja template processing engine
│   └── wiki_generator.py     MkDocs documentation generation
├── main.py                   CLI entry point with Typer
└── __init__.py               Package metadata and version
```

 Centralized Configuration System

 Environment Configuration (`infra/config/env/`)

The toolkit uses a centralized configuration system organized by domains:

```text
infra/config/env/
├── env.dev           Development (http://kubelab.test)
├── env.staging       Staging (https://staging.kubelab.live)
└── env.prod          Production (https://kubelab.live)
```

 Configuration Domains

Each environment file is organized by logical domains:

```bash
 === PROJECT & ENVIRONMENT ===
PYTHON_VERSION=.
ENVIRONMENT=dev
PROJECT_NAME=kubelab
LOG_LEVEL=info
DEBUG_MODE=true

 === NETWORKING & DOMAINS ===
BASE_DOMAIN=kubelab.test
PROTOCOL=http
DOCKER_NETWORK=proxy-dev

 === AUTHENTICATION & SECURITY ===
USERNAME=manu
PASSWORD=
ACME_SERVER=https://acme-staging-v.api.letsencrypt.org/directory
SSH_TIMEOUT=

 === DOCKER & REGISTRY ===
DOCKERHUB_USERNAME=mlorentedev
REGISTRY=docker.io/${DOCKERHUB_USERNAME}
RESTART_POLICY=always

 === APPLICATION SERVICES ===
API_PORT=
WEB_PORT=
BLOG_PORT=
WIKI_PORT=

 === SERVICE ENDPOINTS ===
API_ENDPOINT=http://localhost:/api/entrypoints
WEB_ENDPOINT=http://localhost:
BLOG_ENDPOINT=http://localhost:

 === APPLICATION PATHS ===
API_PATH=./apps/api
WEB_PATH=./apps/web
BLOG_PATH=./apps/blog

 === CORE SERVICES PATHS ===
GITEA_PATH=./services/core/gitea
PORTAINER_PATH=./services/core/portainer

 === EDGE SERVICES PATHS ===
ERRORS_PATH=./infra/stacks/edge/errors
TRAEFIK_PATH=./edge/traefik
```

 Configuration Loading

The toolkit automatically loads environment-specific configuration:

```python
 Automatic environment detection and loading
from toolkit.config.environment import get_env_config

 Get configuration for current environment
env_config = get_env_config()   Uses ENVIRONMENT variable
env_config = get_env_config("staging")   Explicit environment

 Access typed configuration properties
api_endpoint = env_config.api_endpoint
base_domain = env_config.base_domain
restart_policy = env_config.restart_policy
```

 Usage

 Configuration Management

```bash
 Generate all configurations for target environment
poetry run toolkit config generate --env dev
poetry run toolkit config generate --env staging
poetry run toolkit config generate --env prod

 Generate specific service configurations
poetry run toolkit config traefik --env dev
poetry run toolkit config ansible --env staging
poetry run toolkit config terraform --env prod

 Validate configurations
poetry run toolkit config validate
```

 Application Management

```bash
 Application lifecycle
poetry run toolkit apps build api --env dev
poetry run toolkit apps up web --env dev
poetry run toolkit apps down blog --env dev
poetry run toolkit apps logs wiki --env dev

 Docker operations
poetry run toolkit apps docker-build api --env staging
poetry run toolkit apps docker-push api --env staging
```

 Service Management

```bash
 Service lifecycle
poetry run toolkit services up portainer --env dev
poetry run toolkit services down grafana --env dev
poetry run toolkit services logs loki --env dev
poetry run toolkit services status all --env dev
```

 Deployment Workflows

```bash
 Environment setup
poetry run toolkit deployment setup --env staging
poetry run toolkit deployment setup --env prod

 Full deployment
poetry run toolkit deployment deploy --env staging
poetry run toolkit deployment deploy --env prod

 Health checks
poetry run toolkit deployment status --env dev
```

 Infrastructure Operations

```bash
 Infrastructure deployment
poetry run toolkit infra deploy --env staging
poetry run toolkit infra status --env prod

 Terraform operations
poetry run toolkit terraform init --env dev
poetry run toolkit terraform plan --env staging
poetry run toolkit terraform apply --env prod
```

 Development Tools

```bash
 Environment file management
poetry run toolkit tools env-backup
poetry run toolkit tools env-validate
poetry run toolkit tools env-list
poetry run toolkit tools env-init --env dev

 Template processing
poetry run toolkit tools template-process input.yml output.yml infra/config/env/env.dev
poetry run toolkit tools template-process-dir templates/ generated/ infra/config/env/env.dev

 Wiki management
poetry run toolkit tools wiki-collect
poetry run toolkit tools wiki-build
poetry run toolkit tools wiki-serve --port 

 Credential management
poetry run toolkit credentials generate username password
poetry run toolkit credentials github-sync infra/config/env/env.prod
```

 Integration with Task Runner

The toolkit integrates seamlessly with the project's Taskfile system:

```yaml
 Taskfile.yml
dotenv:
  - 'infra/config/env/env.{{.ENVIRONMENT | default "dev"}}'

tasks:
  deploy:
    cmds:
      - poetry run toolkit deployment deploy --env {{.ENVIRONMENT}}
```

All Taskfiles (main, apps, services, edge) use the same centralized configuration:

```bash
 Taskfile commands automatically use environment variables
task api:up ENVIRONMENT=staging
task traefik:generate ENVIRONMENT=prod
task deploy ENVIRONMENT=staging
```

 Module Responsibilities

 Commands (`commands/`)
- CLI interface layer - Typer-based command definitions
- User interaction - Input validation, confirmations, help text
- Workflow orchestration - Calls core libs and utils
- Error handling - User-friendly error messages and exit codes

 Config (`config/`)
- Environment loading - Reads from `infra/config/env/env.{environment}`
- Settings management - Pydantic-based configuration with validation
- Constants - Static values, messages, file patterns
- Type safety - Full type hints for all configuration properties

 Core (`core/`)
- Logging system - Rich console output with environment awareness
- Exception handling - Custom exceptions with proper error codes
- Framework components - Shared functionality for all commands

 Lib (`lib/`)
- Config generators - Template processing for Traefik, Ansible, Terraform
- System operations - File operations, shell commands, validation
- Business logic - Core functionality shared across commands

 Utils (`utils/`)
- Specialized utilities - Environment management, template processing
- External integrations - GitHub secrets, credential generation
- Documentation tools - Wiki generation, documentation collection

 Data Flow

```text
. User runs CLI command
   ↓
. Command loads environment config from infra/config/env/env.{env}
   ↓
. Configuration system provides typed properties
   ↓
. Command calls lib/ functions with config
   ↓
. Lib/ functions use utils/ for specialized operations
   ↓
. Results logged and returned to user
```

 Command Reference

| Command | Purpose | Key Features |
|---------|---------|--------------|
| apps | Application lifecycle | Build, test, deploy, logs with environment awareness |
| services | Service management | Up/down, logs, status for all infrastructure services |
| deployment | Full deployments | Multi-environment deployment workflows |
| config | Configuration generation | Template processing for all infrastructure configs |
| infra | Infrastructure ops | Health checks, status monitoring, deployment |
| terraform | Terraform wrapper | Plan, apply, destroy with environment context |
| edge | Edge services | DNS gateway, proxy management |
| credentials | Secrets management | Generate, sync with GitHub secrets |
| tools | Development utilities | Env management, templates, wiki, logging |

 Type Safety & Validation

The toolkit uses Pydantic for type-safe configuration:

```python
 All configuration properties are typed
@property
def api_endpoint(self) -> str:
    """Get the API endpoint URL."""
    return os.getenv("API_ENDPOINT", f"http://localhost:{self.api_port}")

@property
def ssh_timeout(self) -> int:
    """Get the SSH timeout in seconds."""
    return int(os.getenv("SSH_TIMEOUT", ""))

@property
def restart_policy(self) -> str:
    """Get the Docker restart policy."""
    return os.getenv("RESTART_POLICY", "always")
```

 Environment Workflows

 Development (`env.dev`)
```bash
 Local development with hot reload
poetry run toolkit apps up api --env dev
poetry run toolkit services up traefik --env dev
poetry run toolkit tools wiki-serve
```

 Staging (`env.staging`)
```bash
 Deploy to homelab for testing
poetry run toolkit deployment setup --env staging
poetry run toolkit config generate --env staging
poetry run toolkit deployment deploy --env staging
```

 Production (`env.prod`)
```bash
 Production deployment
poetry run toolkit deployment setup --env prod
poetry run toolkit terraform plan --env prod
poetry run toolkit deployment deploy --env prod
```

 Adding New Features

 New Command
. Create `commands/new_command.py`
. Import in `main.py`
. Use existing config and logging patterns
. Add environment-specific behavior via `get_env_config()`

 New Configuration
. Add variables to `infra/config/env/env.` files
. Add typed properties to `config/environment.py`
. Use in commands via `env_config.property_name`

 New Service
. Add service path to environment files
. Add property to `environment.py`
. Create Taskfile with environment variables
. Add to main Taskfile includes

 Benefits of Current Architecture

- Single Source of Truth: All configuration in `infra/config/env/`
- Environment Consistency: Same structure across dev/staging/prod
- Clean Separation: Commands → Config → Core → Lib → Utils
- Type Safety: Full type hints with Pydantic validation
- Integration: Seamless Taskfile integration with same variables
- Maintainability: Clear responsibilities and well-organized modules
- Performance: Efficient configuration loading and caching
- Testability: Pure functions with clear dependencies

The toolkit provides a modern, type-safe, and maintainable foundation for infrastructure management.
