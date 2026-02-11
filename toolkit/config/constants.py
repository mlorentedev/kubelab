"""Constants, messages, and configurations for the toolkit.

Single source of truth for all constants. To add new features, update this file.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

# =============================================================================
# ENUMS
# =============================================================================


class LogLevel(str, Enum):
    """Log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Environment(str, Enum):
    """Environments."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


# =============================================================================
# COMPONENTS
# =============================================================================


@dataclass(frozen=True)
class Components:
    """Component definitions.

    Note: These match the hierarchical structure in common.yaml:
    - PLATFORM_APPS: apps.platform.*
    - EDGE: edge.*
    - SERVICES_*: apps.services.*.*
    """

    # Platform apps (apps.platform.*)
    PLATFORM_APPS: Sequence[str] = ("api", "web", "blog", "wiki", "workers")

    # Edge services (edge.*)
    EDGE: Sequence[str] = ("traefik", "nginx", "dns-gateway", "cloudflared")

    # Core infrastructure services (apps.services.core.*)
    SERVICES_CORE: Sequence[str] = ("portainer", "n8n", "gitea", "vaultwarden")

    # Data services (apps.services.data.*)
    SERVICES_DATA: Sequence[str] = ("minio", "docmost")

    # Observability services (apps.services.observability.*)
    SERVICES_OBSERVABILITY: Sequence[str] = ("grafana", "loki", "uptime_kuma")

    # Security services (apps.services.security.*)
    SERVICES_SECURITY: Sequence[str] = ("authelia", "crowdsec")

    # Automation services (apps.services.automation.*)
    SERVICES_AUTOMATION: Sequence[str] = ("kestra", "github-runner")

    # Misc services (apps.services.misc.*)
    SERVICES_MISC: Sequence[str] = ("calcom", "immich", "nextcloud")

    # AI services (apps.services.ai.*)
    SERVICES_AI: Sequence[str] = ("ollama",)

    # Legacy compatibility alias
    @property
    def APPS(self) -> Sequence[str]:
        """Alias for PLATFORM_APPS for backward compatibility."""
        return self.PLATFORM_APPS

    @property
    def ALL_SERVICES(self) -> tuple[str, ...]:
        """All third-party services combined."""
        return (
            *self.SERVICES_CORE,
            *self.SERVICES_DATA,
            *self.SERVICES_OBSERVABILITY,
            *self.SERVICES_SECURITY,
            *self.SERVICES_AUTOMATION,
            *self.SERVICES_MISC,
            *self.SERVICES_AI,
        )


# =============================================================================
# FILE PATTERNS
# =============================================================================


@dataclass(frozen=True)
class FilePatterns:
    """File patterns and extensions."""

    # Docker Compose
    COMPOSE_FILE_TEMPLATE: str = "compose.{}.yml"

    # Config files
    CONFIG_EXTENSIONS: Sequence[str] = (".yml", ".yaml", ".json", ".toml")

    # Backups
    BACKUP_SUFFIX: str = ".bak"
    BACKUP_TIMESTAMP_FORMAT: str = "%Y%m%d%H%M%S"


# =============================================================================
# PATHS
# =============================================================================


@dataclass(frozen=True)
class PathStructures:
    """Directory paths."""

    # Source code
    APPS_DIR: str = "apps"
    WIKI: str = "apps/wiki"
    WIKI_DOCS: str = "apps/wiki/generated_docs"

    # Infrastructure
    INFRA_DIR: str = "infra"
    INFRA_ANSIBLE: str = "infra/ansible"
    INFRA_TERRAFORM: str = "infra/terraform"

    # Deployment stacks
    INFRA_STACKS: str = "infra/stacks"
    INFRA_STACKS_APPS: str = "infra/stacks/apps"
    INFRA_STACKS_SERVICES: str = "infra/stacks/services"
    INFRA_STACKS_EDGE: str = "infra/stacks/edge"

    # Edge services (within stacks)
    EDGE_DIR: str = "infra/stacks/edge"
    EDGE_TRAEFIK: str = "infra/stacks/edge/traefik"
    EDGE_NGINX: str = "infra/stacks/edge/nginx"

    # Templates (Jinja2)
    TRAEFIK_TEMPLATES_DIR: str = "edge/traefik/templates"
    TRAEFIK_CONFIG_OUTPUT_DIR: str = "edge/traefik/generated"


# =============================================================================
# DOCKER
# =============================================================================


@dataclass(frozen=True)
class DockerConfig:
    """Docker commands and flags."""

    # Commands
    DOCKER_COMPOSE_CMD: Sequence[str] = ("docker", "compose")
    COMPOSE_UP: str = "up"
    COMPOSE_DOWN: str = "down"
    COMPOSE_LOGS: str = "logs"
    COMPOSE_BUILD: str = "build"

    # Flags
    FLAG_DETACH: str = "-d"
    FLAG_FILE: str = "-f"
    FLAG_FOLLOW: str = "-f"
    FLAG_NO_CACHE: str = "--no-cache"


# =============================================================================
# VALIDATION
# =============================================================================


@dataclass(frozen=True)
class ValidationRules:
    """Validation patterns and rules."""

    # Patterns for sanitization
    SECRET_PATTERNS: Sequence[str] = (
        "PASSWORD",
        "SECRET",
        "TOKEN",
        "KEY",
        "CREDENTIALS",
        "AUTH",
        "JWT",
    )
    URL_PATTERNS: Sequence[str] = ("URL", "HOST", "DOMAIN")
    SAFE_PATTERNS: Sequence[str] = (
        "PORT",
        "ENVIRONMENT",
        "APP_NAME",
        "CONTAINER_NAME",
        "LOG_LEVEL",
    )

    # Values
    SANITIZE_PLACEHOLDER: str = "CHANGE_ME"
    SANITIZE_DOMAIN: str = "example.com"


# =============================================================================
# MESSAGES - SIMPLIFIED
# =============================================================================


@dataclass(frozen=True)
class Messages:
    """Centralized messages.

    Pattern: {LEVEL}_{CATEGORY}_{ACTION}
    - Use .format() for dynamic values
    - Keep messages generic where possible
    """

    # ========================================
    # CONSOLIDATED GENERIC MESSAGES (REUSE)
    # ========================================

    # Generic Operations (use for any component/service/app)
    INFO_STARTING: str = "Starting {}"
    INFO_STOPPING: str = "Stopping {}"
    INFO_RESTARTING: str = "Restarting {}"
    INFO_BUILDING: str = "Building {} for {}"
    INFO_SHOWING_LOGS: str = "Showing logs for {}"
    INFO_CHECKING: str = "Checking {}..."
    INFO_PROCESSING: str = "Processing {}"

    # Generic Success (use for any operation)
    SUCCESS: str = "{} successful"
    SUCCESS_COMPLETED: str = "{} completed successfully"
    SUCCESS_CREATED: str = "Created {}"
    SUCCESS_UPDATED: str = "{} updated successfully"
    SUCCESS_DELETED: str = "{} deleted successfully"
    SUCCESS_BACKED_UP: str = "{} backed up to {}"
    SUCCESS_RESTORED: str = "{} restored successfully"
    SUCCESS_BUILT: str = "{} built successfully"
    SUCCESS_STARTED: str = "{} started successfully"
    SUCCESS_STOPPED: str = "{} stopped successfully"
    SUCCESS_PASSED: str = "{} passed"

    # Generic Errors (use for any operation)
    ERROR_NOT_FOUND: str = "{} not found: {}"
    ERROR_FAILED: str = "Failed to {}"
    ERROR_FAILED_WITH_REASON: str = "{} failed: {}"
    ERROR_INVALID: str = "Invalid {}: {}"
    ERROR_MISSING: str = "Missing {}"
    ERROR_UNKNOWN_SERVICE: str = "Unknown service: {}"

    # Generic Warnings
    WARNING_NOT_FOUND: str = "{} not found"
    WARNING_NOT_CONFIGURED: str = "{} not configured for {}"
    WARNING_NOT_IMPLEMENTED: str = "{} not implemented for {}"
    WARNING_MISSING_FILES: str = "Missing {} files"
    WARNING_NOT_RUNNING: str = "{} is not running"
    WARNING_CANCELLED: str = "Operation cancelled"

    # Generic Info
    INFO_AVAILABLE: str = "Available {}:"
    INFO_FOUND: str = "Found {} {}"
    INFO_CANCELLED: str = "{} cancelled"
    INFO_RUNNING_COMMAND: str = "Running: {}"

    # ========================================
    # EXISTING MESSAGES (keeping for backwards compatibility)
    # ========================================

    INFO_RUNNING: str = "Running {} for {}"
    INFO_CLEANING: str = "Cleaning {} artifacts"
    INFO_GENERATING: str = "Generating {} configuration..."
    INFO_VALIDATING: str = "Validating {}..."
    INFO_SEARCHING: str = "Searching for files matching pattern: {}"
    INFO_INITIALIZING: str = "Initializing {} files from templates..."
    INFO_BACKING_UP: str = "Backing up {} to: {}"
    INFO_SKIPPED: str = "Skipping {} (already exists, use --force)"

    WARNING_NO_FILES: str = "No {} files found"
    WARNING_MISSING: str = "Missing {}: {}"

    ERROR_VALIDATION_FAILED: str = "Found {} validation errors"

    # ========================================
    # SPECIFIC MESSAGES (when generic won't work)
    # ========================================

    # Component/Service specific
    ERROR_COMPONENT_NOT_FOUND: str = "Component not found: {}"
    INFO_USE_DOCKER_CONTAINER: str = (
        "Use 'toolkit services up {}' to start in Docker container"
    )
    WARNING_NO_VOLUMES_FOUND: str = "No volumes found for {}"

    # Environment specific
    ERROR_INVALID_ENVIRONMENT: str = "Invalid environment: {}. Must be one of: {}"
    INFO_TARGET_ENVIRONMENT: str = "Target environment: {}"

    # File operations
    ERROR_COMPOSE_FILE_NOT_FOUND: str = "Compose file not found: {}"
    ERROR_TEMPLATE_NOT_FOUND: str = "Template not found: {}"
    ERROR_DIR_NOT_FOUND: str = "Directory not found: {}"

    # Specific messages (when pattern doesn't fit)
    SUCCESS_SERVICE_STARTED: str = "Service '{}' started successfully"
    SUCCESS_SERVICE_STOPPED: str = "Service '{}' stopped successfully"
    SUCCESS_DOCKER_IMAGE_BUILT: str = "Docker image built: {}"
    SUCCESS_DOCKER_IMAGE_PUSHED: str = "Docker image pushed: {}"
    SUCCESS_FILES_VALIDATED: str = "All {} files are valid"
    SUCCESS_BUILD_GO: str = "Go application built successfully"
    SUCCESS_BUILD_ASTRO: str = "Astro application built successfully"
    SUCCESS_BUILD_JEKYLL: str = "Jekyll site built successfully"
    SUCCESS_TESTS_PASSED: str = "Tests passed for '{}'"
    SUCCESS_LINT_PASSED: str = "Linting passed for '{}'"
    SUCCESS_BACKUP_CREATED: str = "Backup created: {}"

    INFO_BUILDING_APP: str = "Building {} for {} environment"
    INFO_TESTING_APP: str = "Running tests for {}"
    INFO_LINTING_APP: str = "Running linter for {}"
    INFO_CLEANING_APP: str = "Cleaning {} artifacts"
    INFO_BUILDING_DOCKER_IMAGE: str = "Building Docker image for {}"
    INFO_PUSHING_DOCKER_IMAGE: str = "Pushing Docker image for {}"
    INFO_VALIDATING_CONFIG_FILES: str = "Validating configuration files..."
    INFO_FILE_FOUND: str = "Found {} files:"
    INFO_FILE_COPIED: str = "✓ {}"
    INFO_FILE_CREATED: str = "Created {}"
    INFO_FILE_SKIPPED: str = "Skipping {} (already exists, use --force to overwrite)"
    INFO_FILE_EMPTY: str = "Skipping empty file: {}"

    WARNING_FILE_NOT_FOUND: str = "File {} does not exist"
    WARNING_DEPLOYING_STAGING: str = "Deploying to STAGING environment"
    WARNING_NO_FILES_FOUND: str = "No files found matching pattern: {}"
    WARNING_NO_TESTS_CONFIGURED: str = "No tests configured for {}"
    WARNING_NO_LINTING_CONFIGURED: str = "No linting configured for {}"

    ERROR_MISSING_REQUIRED_VARS: str = "Missing required variables:"
    ERROR_FAILED_BACKUP: str = "Failed to create backup of {}: {}"
    ERROR_SERVICE_START_FAILED: str = "Failed to start service"
    ERROR_SERVICE_STOP_FAILED: str = "Failed to stop service"
    ERROR_FILE_COPY_FAILED: str = "Failed to copy {} to {}: {}"
    ERROR_FILE_CREATE_FAILED: str = "Failed to create {} from {}: {}"
    ERROR_FILE_CREATE_EXAMPLE_FAILED: str = "Failed to create example file for {}: {}"
    ERROR_FILE_LOAD_FAILED: str = "Failed to load {}: {}"
    ERROR_YAML_INVALID: str = "✗ {} has invalid YAML: {}"
    ERROR_YAML_VALIDATION_FAILED: str = "? Could not validate {}: {}"
    ERROR_INVALID_LINE_FORMAT: str = "{}:{} - Invalid line format: {}"
    ERROR_INVALID_FILE: str = "✗ Invalid: {} - {}"
    ERROR_FAILED_OPERATION: str = "Failed to {}: {}"

    # =============================================================================
    # TERRAFORM
    # =============================================================================
    ERROR_TERRAFORM_NOT_FOUND: str = (
        "Terraform not found. Please install Terraform first."
    )
    ERROR_TERRAFORM_DIR_NOT_FOUND: str = "Terraform directory not found: {}"
    ERROR_TERRAFORM_INIT_FAILED: str = "Terraform init failed"
    ERROR_TERRAFORM_INIT_FAILED_WITH_ERROR: str = "Terraform init failed: {}"
    ERROR_TERRAFORM_PLAN_FAILED: str = "Terraform plan failed: {}"
    ERROR_TERRAFORM_APPLY_FAILED: str = "Terraform apply failed: {}"
    ERROR_TERRAFORM_DESTROY_FAILED: str = "Terraform destroy failed: {}"
    ERROR_TERRAFORM_VALIDATION_FAILED: str = "Terraform validation failed: {}"
    ERROR_TERRAFORM_GENERATION_FAILED: str = (
        "Failed to generate Terraform configuration"
    )
    ERROR_TERRAFORM_CONFIG_GENERATION_FAILED: str = (
        "Terraform configuration generation failed: {}"
    )
    ERROR_DEPLOYMENT_FAILED: str = "Deployment failed"
    INFO_TERRAFORM_APPLY_CANCELLED: str = "Terraform apply cancelled"
    INFO_TERRAFORM_DESTROY_CANCELLED: str = "Terraform destroy cancelled"
    INFO_TERRAFORM_RUNNING_APPLY: str = "Running apply without pre-generated plan"
    INFO_TERRAFORM_APPLY_WITHOUT_PLAN: str = "Applying without pre-generated plan"
    WARNING_TERRAFORM_PLAN_NOT_FOUND: str = (
        "Terraform plan file not found for environment: {}"
    )
    WARNING_TERRAFORM_DESTROY_DANGER: str = (
        "  DANGER: This will destroy infrastructure!"
    )
    WARNING_TERRAFORM_FORMAT_ISSUES: str = "Terraform files are not properly formatted"
    WARNING_TERRAFORM_FORMAT_NEEDED: str = "Terraform files need formatting"
    INFO_TERRAFORM_FIX_FORMAT: str = "Run 'terraform fmt' to fix formatting issues"
    INFO_TERRAFORM_FMT_COMMAND: str = (
        "Run 'terraform fmt -recursive .' to fix formatting"
    )
    SUCCESS_TERRAFORM_VALID: str = "Terraform configuration is valid"
    SUCCESS_TERRAFORM_FORMATTED: str = "Terraform configuration is properly formatted"
    SUCCESS_TERRAFORM_INIT: str = "Terraform initialized for {} environment"
    SUCCESS_TERRAFORM_PLAN_CREATED: str = "Terraform plan created for {} environment"
    SUCCESS_TERRAFORM_APPLY: str = "Terraform applied successfully for {} environment"
    SUCCESS_TERRAFORM_DESTROY: str = (
        "Terraform destroyed successfully for {} environment"
    )

    # =============================================================================
    # CREDENTIALS
    # =============================================================================
    ERROR_CREDENTIALS_REQUIRED: str = "Username and password are required"
    ERROR_CREDENTIALS_GENERATION_FAILED: str = "Failed to generate credentials: {}"
    ERROR_CREDENTIALS_CONFIG_NOT_FOUND: str = (
        "Configuration not found for credentials sync: {}"
    )
    ERROR_CREDENTIALS_SECRET_SET_FAILED: str = "Failed to set secret '{}': {}"
    ERROR_CREDENTIALS_SECRET_DELETE_FAILED: str = "Failed to delete secret '{}': {}"
    ERROR_PASSWORD_EMPTY: str = "Password cannot be empty"
    ERROR_PASSWORD_MISMATCH: str = "Passwords do not match"
    ERROR_GITHUB_CLI_NOT_FOUND: str = (
        "GitHub CLI not found. Please install gh CLI and authenticate."
    )
    INFO_CREDENTIALS_GENERATING: str = "Generating main authentication credentials..."
    INFO_CREDENTIALS_GENERATED: str = "Generated credentials successfully"
    INFO_CREDENTIALS_SECRET_DELETION_CANCELLED: str = "Secret deletion cancelled"
    INFO_SECRET_DELETION_CANCELLED: str = "Secret deletion cancelled"
    INFO_NO_UNUSED_SECRETS: str = "No unused secrets found"
    INFO_PASSWORD_HIDDEN: str = "Password: ********"
    INFO_SAVE_CREDENTIALS: str = "Please save these credentials securely."
    SUCCESS_CREDENTIALS_MAIN: str = (
        "Main authentication credentials generated and updated successfully!"
    )
    SUCCESS_CREDENTIALS_DISPLAY: str = (
        "Generated credentials from provided username and password"
    )
    SUCCESS_CREDENTIALS_SECRETS_SYNCED: str = "Synced {} secrets to GitHub"
    SUCCESS_CREDENTIALS_SECRET_SET: str = "Secret '{}' set successfully"
    SUCCESS_CREDENTIALS_SECRET_DELETED: str = "Secret '{}' deleted successfully"
    WARNING_CREDENTIALS_NO_SECRETS_SYNCED: str = "No secrets were synced"
    WARNING_CREDENTIALS_NO_GITHUB_SECRETS: str = (
        "No GitHub secrets configured in values files"
    )
    WARNING_NO_SECRETS_SYNCED: str = "No secrets were synced"
    WARNING_NO_GH_SECRETS: str = "No GitHub secrets configured"
    WARNING_NO_ENV_VARS: str = "No environment variables found to sync"
    WARNING_NO_SENSITIVE_VARS: str = "No sensitive variables found to sync as secrets"

    # =============================================================================
    # WIKI
    # =============================================================================
    INFO_WIKI_COLLECTING_DOCS: str = "Collecting documentation from monorepo..."
    INFO_WIKI_GENERATING_CONFIG: str = "Generating MkDocs configuration..."
    INFO_WIKI_BUILDING: str = "Building wiki with MkDocs..."
    INFO_WIKI_GENERATING_COMPLETE: str = "Generating complete wiki..."
    INFO_WIKI_SERVER_STOPPED: str = "Wiki server stopped"
    INFO_WIKI_COLLECTED_APP: str = "Collected app documentation: {}"
    INFO_WIKI_COLLECTED_EDGE: str = "Collected edge documentation: {}"
    INFO_WIKI_COLLECTED_INFRA: str = "Collected infra documentation: {}"
    INFO_WIKI_COLLECTED_SERVICE: str = "Collected service documentation: {}"
    INFO_WIKI_COLLECTED_GUIDE: str = "Collected guide: {}"
    INFO_WIKI_COLLECTED_ADR: str = "Collected ADR: {}"
    INFO_WIKI_COLLECTED_SCRIPTS: str = "Created scripts documentation"
    INFO_WIKI_ASSETS_COPIED: str = "Wiki assets copied successfully"
    SUCCESS_WIKI_BUILT: str = "Wiki built successfully"
    SUCCESS_WIKI_COMPLETED: str = "Wiki generation completed successfully"
    SUCCESS_WIKI_GENERATED: str = "Wiki generated successfully for {} environment"
    SUCCESS_SCRIPTS_DOCS_CREATED: str = "Created scripts documentation"
    WARNING_ADR_DIR_NOT_FOUND: str = "ADR directory not found: docs/adr/"
    ERROR_WIKI_FAILED: str = "Wiki generation failed"
    ERROR_WIKI_COLLECTION_FAILED: str = "Wiki collection failed: {}"
    ERROR_WIKI_GENERATION_FAILED: str = "Wiki generation failed: {}"
    ERROR_WIKI_BUILD_FAILED: str = "Wiki build failed: {}"
    ERROR_MKDOCS_NOT_FOUND: str = (
        "MkDocs not found. Please install it: pip install mkdocs mkdocs-material"
    )

    # =============================================================================
    # CONFIG
    # =============================================================================
    INFO_CONFIG_GENERATION_CANCELLED: str = "Configuration generation cancelled"
    SUCCESS_ALL_CONFIGS_GENERATED: str = "All configurations generated successfully"
    SUCCESS_ALL_VALIDATIONS_PASSED: str = "All validations passed"
    SUCCESS_TRAEFIK_VALID: str = "Traefik validation passed"
    SUCCESS_ANSIBLE_VALID: str = "Ansible validation passed"
    WARNING_CONFIG_GENERATION_FAILED: str = "Configuration generation failed: {}"
    WARNING_FAILED: str = "{} operation(s) failed"

    # Configuration validation
    SUCCESS_CONFIG_VALIDATION_PASSED: str = "{} validation passed"
    SUCCESS_CONFIG_ALL_VALIDATIONS_PASSED: str = "All configuration validations passed"
    SUCCESS_CONFIG_TRAEFIK_VALIDATION_PASSED: str = "Traefik configuration is valid"
    SUCCESS_CONFIG_ANSIBLE_VALIDATION_PASSED: str = "Ansible configuration is valid"
    WARNING_CONFIG_VALIDATION_FAILED: str = "{} validation failed"
    WARNING_CONFIG_SOME_VALIDATIONS_FAILED: str = (
        "{}/{} configuration validations passed"
    )
    WARNING_CONFIG_MISSING_TRAEFIK_FILES: str = (
        "Missing Traefik configuration files: {}"
    )
    WARNING_CONFIG_MISSING_ANSIBLE_FILES: str = (
        "Missing Ansible configuration files: {}"
    )
    ERROR_CONFIG_VALIDATION_ERROR: str = "Error validating {}: {}"
    ERROR_CONFIG_VALIDATION_FAILED_WITH_ERROR: str = (
        "Configuration validation failed: {}"
    )
    ERROR_CONFIG_TRAEFIK_DIR_NOT_FOUND: str = "Traefik directory not found: {}"
    ERROR_CONFIG_ANSIBLE_DIR_NOT_FOUND: str = "Ansible directory not found: {}"

    # =============================================================================
    # ANSIBLE
    # =============================================================================
    ERROR_ANSIBLE_NO_INVENTORY: str = (
        "No Ansible inventory configured for {} environment"
    )
    ERROR_ANSIBLE_INVENTORY_NOT_FOUND: str = "Ansible inventory not found: {}"
    ERROR_ANSIBLE_DEPLOYMENT_FAILED: str = "Ansible deployment failed"
    ERROR_ANSIBLE_DEPLOYMENT_FAILED_WITH_ERROR: str = "Ansible deployment failed: {}"
    SUCCESS_ANSIBLE_DEPLOYMENT: str = "Ansible deployment completed for {} environment"

    # =============================================================================
    # DEPLOYMENT
    # =============================================================================
    INFO_DEPLOYMENT_CANCELLED: str = "Deployment cancelled"
    INFO_ENVIRONMENT_SETUP_CANCELLED: str = "Environment setup cancelled"
    INFO_RESTORE_CANCELLED: str = "Restore cancelled"
    INFO_ROLLBACK_CANCELLED: str = "Rollback cancelled"
    WARNING_DEV_BACKUP_UNNECESSARY: str = (
        "Backups for development environment are typically not necessary"
    )
    INFO_DEV_USES_LOCAL: str = "Development uses local Docker containers"

    # =============================================================================
    # INFRASTRUCTURE
    # =============================================================================
    INFO_AVAILABLE_SERVICES: str = "Available services: {}"
    INFO_SERVICE_DISCOVERY_STATUS: str = "Service discovery status:"
    INFO_STATUS_CHECK_COMPLETED: str = "Status check completed for all services"
    INFO_INFRASTRUCTURE_AVAILABLE_SERVICES: str = "Available services: traefik, all"
    INFO_INFRASTRUCTURE_STATUS_CHECK_COMPLETED: str = "Status check completed"
    SUCCESS_TRAEFIK_RUNNING: str = "Traefik is running:"
    SUCCESS_TRAEFIK_API_RESPONDING: str = " Traefik API is responding"
    SUCCESS_INFRASTRUCTURE_TRAEFIK_RUNNING: str = "Traefik is running"
    SUCCESS_INFRASTRUCTURE_TRAEFIK_API_RESPONDING: str = "Traefik API is responding"
    SUCCESS_INFRASTRUCTURE_SERVICE_STATUS_CHECKED: str = "{} status checked"
    WARNING_TRAEFIK_NOT_RUNNING: str = "Traefik is not running"
    WARNING_INFRASTRUCTURE_TRAEFIK_NOT_RUNNING: str = "Traefik container is not running"
    WARNING_INFRASTRUCTURE_TRAEFIK_API_NOT_RESPONDING: str = (
        "Traefik API not responding (HTTP {})"
    )
    WARNING_INFRASTRUCTURE_HEALTH_CHECK_FAILED: str = "Health check failed: {}"
    WARNING_INFRASTRUCTURE_SERVICE_CHECK_FAILED: str = "Failed to check {} status"
    ERROR_INFRASTRUCTURE_STATUS_CHECK_FAILED: str = "Status check failed: {}"

    # =============================================================================
    # ORCHESTRATOR
    # =============================================================================
    INFO_CREATING_BACKUPS: str = "Creating local Docker volume backups..."
    INFO_RESTART_TO_ROLLBACK: str = (
        "Use `docker-compose down && docker-compose up` to restart with previous images"
    )
    WARNING_RESTORE_NOT_IMPLEMENTED: str = (
        "Local restore functionality not yet fully implemented"
    )
    WARNING_HEALTH_CHECKS_FAILED: str = "Health checks failed, trying basic ping..."

    # =============================================================================
    # SERVICES
    # =============================================================================
    INFO_AVAILABLE_COMPONENTS: str = "Available components"
    ERROR_GITEA_BACKUP_FAILED: str = "Gitea backup failed"
    ERROR_GITEA_RESTORE_FAILED: str = "Gitea restore failed"
    SUCCESS_GITEA_RESTORED: str = "Gitea data restored successfully"
    WARNING_VAULTWARDEN_RESTORE_NOT_IMPL: str = (
        "Vaultwarden restore not yet implemented"
    )
    SUCCESS_CLEANED_RESOURCES: str = "Cleaned {} resources"

    # Confirmation prompts
    CONFIRM_PRODUCTION_DEPLOY: str = (
        "You are about to deploy to PRODUCTION. This will affect live services. Continue?"
    )
    CONFIRM_DESTROY_SERVICES: str = (
        "You are about to DESTROY services in {} environment. This action cannot be undone. Continue?"
    )

    VALIDATION_FILE_EXISTS: str = "✓ {} exists"
    VALIDATION_YAML_VALID: str = "✓ {} is valid YAML"
    VALIDATION_CONFIG_VALID: str = "✓ Valid: {}"


# =============================================================================
# AUTHELIA CONFIGURATION
# =============================================================================


@dataclass(frozen=True)
class AutheliaConfig:
    """Authelia-specific configuration constants.

    These parameters MUST match between:
    - toolkit/features/credentials.py (hash generation)
    - infra/config/authelia/templates/configuration.yml.j2 (validation)
    """

    # Argon2 password hashing parameters
    ARGON2_TIME_COST: int = 3  # iterations
    ARGON2_MEMORY_COST: int = 65536  # 64MB in KB
    ARGON2_PARALLELISM: int = 4  # threads
    ARGON2_HASH_LENGTH: int = 32  # bytes
    ARGON2_SALT_LENGTH: int = 16  # bytes

    # RSA key generation
    RSA_KEY_SIZE: int = 4096

    # Secrets file paths (relative to project root)
    SECRETS_DIR: str = "infra/config/secrets"
    JWKS_FILE_TEMPLATE: str = "{env}.oidc-jwks.pem"
    ENCRYPTED_SECRETS_TEMPLATE: str = "{env}.enc.yaml"


# =============================================================================
# DEFAULTS
# =============================================================================


@dataclass(frozen=True)
class DefaultConfig:
    """Default values."""

    # Environment
    DEFAULT_ENVIRONMENT: str = "dev"
    VALID_ENVIRONMENTS: Sequence[str] = ("dev", "staging", "prod")

    # Tools
    REQUIRED_TOOLS: Sequence[str] = ("docker", "docker-compose")
    CHECK_TOOLS: Sequence[str] = ("docker", "docker-compose", "git", "gh", "jq")

    # File permissions
    SECURE_FILE_PERMISSIONS: str = "600"
    DEFAULT_FILE_PERMISSIONS: str = "644"

    # Backup
    BACKUP_TIMESTAMP_FORMAT: str = "%Y%m%d%H%M%S"
    BACKUP_DIR: str = ".tmp"

    # SSH
    SSH_CONNECT_TIMEOUT: int = 5
    SSH_TIMEOUT: int = 10


@dataclass(frozen=True)
class NetworkDefaults:
    """Network and connection defaults."""

    DEFAULT_HOST: str = "127.0.0.1"
    BIND_ALL_HOST: str = "0.0.0.0"
    CONNECTION_SUCCESS_CODES: Sequence[str] = ("200", "401")
    CURL_TIMEOUT: int = 5
    HEALTHCHECK_TIMEOUT: int = 30
    HEALTHCHECK_INTERVAL: int = 10


# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

COMPONENTS = Components()
FILE_PATTERNS = FilePatterns()
PATH_STRUCTURES = PathStructures()
DOCKER_CONFIG = DockerConfig()
VALIDATION_RULES = ValidationRules()
MESSAGES = Messages()
DEFAULT_CONFIG = DefaultConfig()
NETWORK_DEFAULTS = NetworkDefaults()
AUTHELIA_CONFIG = AutheliaConfig()

__all__ = [
    "COMPONENTS",
    "FILE_PATTERNS",
    "PATH_STRUCTURES",
    "DOCKER_CONFIG",
    "VALIDATION_RULES",
    "MESSAGES",
    "DEFAULT_CONFIG",
    "NETWORK_DEFAULTS",
    "AUTHELIA_CONFIG",
    "Environment",
    "LogLevel",
]
