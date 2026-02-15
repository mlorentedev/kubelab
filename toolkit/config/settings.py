"""Application settings - single source of truth from ConfigurationManager (YAML/SOPS)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    COMPONENTS,
    DEFAULT_CONFIG,
    NETWORK_DEFAULTS,
    PATH_STRUCTURES,
)

# =============================================================================
# PACKAGE METADATA
# =============================================================================

try:
    from importlib.metadata import metadata, version

    PKG_NAME = "toolkit"
    PKG_VERSION = version(PKG_NAME)
    PKG_METADATA = metadata(PKG_NAME)
except Exception:
    PKG_NAME = "toolkit"
    PKG_VERSION = "0.1.0"
    PKG_METADATA = {}  # type: ignore[assignment]

# =============================================================================
# BASE PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================

ENVIRONMENT_KEYS = ("ENVIRONMENT", "ENV", "DEFAULT_ENVIRONMENT")


def _resolve_environment() -> str:
    """Detect environment from env vars, default to 'dev'."""
    for key in ENVIRONMENT_KEYS:
        value = os.getenv(key)
        if value:
            return value
    return DEFAULT_CONFIG.DEFAULT_ENVIRONMENT


def _list_from_env(var_name: str, default: list[str]) -> list[str]:
    """Parse list from env var (JSON or comma-separated)."""
    raw = os.getenv(var_name)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in raw.split(",") if item.strip()]


# =============================================================================
# ENVIRONMENT CONFIG
# =============================================================================


class EnvironmentConfig(BaseModel):
    """Per-environment configuration."""

    name: str
    description: str
    requires_confirmation: bool = False
    ansible_inventory: str | None = None
    terraform_workspace: str | None = None


def _load_environments() -> dict[str, EnvironmentConfig]:
    """Load environment configs from ENVIRONMENTS_JSON or defaults."""
    config_json = os.getenv("ENVIRONMENTS_JSON")

    if config_json:
        try:
            data = json.loads(config_json)
            if isinstance(data, dict):
                return {
                    name: EnvironmentConfig(name=name, **payload)
                    for name, payload in data.items()
                    if isinstance(payload, dict)
                }
        except json.JSONDecodeError:
            pass

    # Defaults
    return {
        "dev": EnvironmentConfig(name="dev", description="Local development"),
        "staging": EnvironmentConfig(
            name="staging",
            description="Staging environment",
            requires_confirmation=True,
            ansible_inventory="inventories/staging.yml",
            terraform_workspace="staging",
        ),
        "prod": EnvironmentConfig(
            name="prod",
            description="Production environment",
            requires_confirmation=True,
            ansible_inventory="inventories/prod.yml",
            terraform_workspace="prod",
        ),
    }


# =============================================================================
# MAIN SETTINGS
# =============================================================================


class PlatformSettings(BaseSettings):
    """Application settings from ConfigurationManager (YAML/SOPS).

    All values can be overridden via environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )

    # =============================================================================
    # METADATA (not from env)
    # =============================================================================

    version: str = PKG_VERSION
    author: str = PKG_METADATA.get("Author", "unknown")
    email: str = PKG_METADATA.get("Author-email", "unknown")

    # =============================================================================
    # ENVIRONMENT
    # =============================================================================

    environment: str
    environments: dict[str, EnvironmentConfig] = Field(default_factory=_load_environments)

    # =============================================================================
    # PATHS (from constants)
    # =============================================================================

    project_root: Path = PROJECT_ROOT

    def get_app_path(self, app_name: str) -> Path:
        """Get app path dynamically."""
        return self.project_root / PATH_STRUCTURES.APPS_DIR / app_name

    def get_service_path(self, service_name: str, category: str = "") -> Path:
        """Get service path dynamically."""
        if category:
            return self.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES / category / service_name
        # Auto-detect category from COMPONENTS
        for cat_name in (
            "core",
            "data",
            "observability",
            "security",
            "automation",
            "misc",
            "ai",
        ):
            cat_services = getattr(COMPONENTS, f"SERVICES_{cat_name.upper()}", ())
            if service_name in cat_services:
                return self.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES / cat_name / service_name
        return self.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES / service_name

    def get_edge_path(self, edge_name: str) -> Path:
        """Get edge service path."""
        return self.project_root / PATH_STRUCTURES.EDGE_DIR / edge_name

    @property
    def apps_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.APPS_DIR

    @property
    def infra_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.INFRA_DIR

    @property
    def edge_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.EDGE_DIR

    @property
    def services_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES

    @property
    def terraform_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.INFRA_TERRAFORM

    @property
    def ansible_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.INFRA_ANSIBLE

    @property
    def traefik_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.EDGE_TRAEFIK

    @property
    def nginx_dir(self) -> Path:
        return self.project_root / PATH_STRUCTURES.EDGE_NGINX

    @property
    def tmp_dir(self) -> Path:
        return self.project_root / DEFAULT_CONFIG.BACKUP_DIR

    # =============================================================================
    # PROJECT METADATA (from env)
    # =============================================================================

    python_version: str = "3.12"
    project_name: str = PKG_NAME
    debug_mode: bool = False

    # =============================================================================
    # DOCKER (from env)
    # =============================================================================

    registry: str = "docker.io"
    docker_network: str = "cubelab"
    dockerhub_username: str | None = None
    dockerhub_token: str | None = None
    restart_policy: str = "unless-stopped"
    default_memory_limit: str = "512M"
    default_cpu_limit: str = "0.5"

    @property
    def docker_registry(self) -> str:
        """Alias for registry."""
        return self.registry

    # =============================================================================
    # LOGGING (from env)
    # =============================================================================

    log_level: str = "INFO"
    log_format: str = "%(message)s"

    # =============================================================================
    # NETWORK (from env)
    # =============================================================================

    base_domain: str = "localhost"
    protocol: str = "http"

    # Ports (from env)
    api_port: int = 8080
    web_port: int = 3000
    blog_port: int = 4000
    wiki_port: int = 8000

    # Endpoints (computed)
    @property
    def api_endpoint(self) -> str:
        return f"{self.protocol}://api.{self.base_domain}"

    @property
    def web_endpoint(self) -> str:
        return f"{self.protocol}://{self.base_domain}"

    @property
    def blog_endpoint(self) -> str:
        return f"{self.protocol}://blog.{self.base_domain}"

    @property
    def wiki_endpoint(self) -> str:
        return f"{self.protocol}://wiki.{self.base_domain}"

    # =============================================================================
    # TOOLS (from env or defaults)
    # =============================================================================

    check_tools: list[str] = Field(
        default_factory=lambda: _list_from_env("CHECK_TOOLS", list(DEFAULT_CONFIG.CHECK_TOOLS))
    )
    required_tools: list[str] = Field(
        default_factory=lambda: _list_from_env("REQUIRED_TOOLS", list(DEFAULT_CONFIG.REQUIRED_TOOLS))
    )

    # =============================================================================
    # VALIDATION
    # =============================================================================

    @model_validator(mode="after")
    def validate_environment_settings(self) -> "PlatformSettings":
        """Validate environment on initialization."""
        self.validate_environment(self.environment)

        # Optional: You might want to relax these checks in dev if credentials are not needed yet
        # But if your app needs them, keep them strict.
        if not self.dockerhub_username or not self.dockerhub_token:
            # Warn instead of crash for dev? Or strict?
            # Let's keep it strict if that's your policy, or relax if you don't always need dockerhub.
            pass

        if self.protocol not in ("http", "https"):
            raise ValueError("Protocol must be either 'http' or 'https'.")
        return self

    # =============================================================================
    # TIMEOUTS (from constants)
    # =============================================================================

    ssh_timeout: int = DEFAULT_CONFIG.SSH_TIMEOUT
    ssh_connect_timeout: int = DEFAULT_CONFIG.SSH_CONNECT_TIMEOUT
    curl_timeout: int = NETWORK_DEFAULTS.CURL_TIMEOUT

    # =============================================================================
    # HELPER PROPERTIES
    # =============================================================================

    @property
    def security(self) -> dict[str, Any]:
        """Security settings."""
        return {
            "enabled": True,
            "ssh_connect_timeout": self.ssh_connect_timeout,
            "ssh_timeout": self.ssh_timeout,
            "secure_file_permissions": DEFAULT_CONFIG.SECURE_FILE_PERMISSIONS,
        }

    @property
    def backup(self) -> dict[str, Any]:
        """Backup settings."""
        return {
            "enabled": True,
            "retention": 30,
            "timestamp_format": DEFAULT_CONFIG.BACKUP_TIMESTAMP_FORMAT,
        }

    def get_environment(self, env_name: str) -> EnvironmentConfig:
        """Get environment config."""
        if env_name not in self.environments:
            raise ValueError(f"Unknown environment: {env_name}")
        return self.environments[env_name]

    def validate_environment(self, env_name: str | None = None) -> str:
        """Validate environment name."""
        env_to_validate = env_name or self.environment
        if env_to_validate not in self.environments:
            raise ValueError(
                f"Invalid environment '{env_to_validate}'. Must be one of: {', '.join(self.environments.keys())}"
            )
        return env_to_validate


# =============================================================================
# SETTINGS FACTORY
# =============================================================================

_settings_cache: dict[str, PlatformSettings] = {}
_cache_lock = Lock()


def get_settings(env: str | None = None) -> PlatformSettings:
    """Get settings for environment (cached, thread-safe).

    Loads config from ConfigurationManager (YAML+SOPS) only.

    Args:
        env: Target environment ('dev', 'staging', 'prod'). Auto-detected if None.

    Returns:
        PlatformSettings instance for the environment.
    """
    target_env = env or _resolve_environment()

    with _cache_lock:
        if target_env in _settings_cache:
            return _settings_cache[target_env]

        # Load from ConfigurationManager (New Architecture)
        # Import here to avoid circular dependency
        from toolkit.features.configuration import ConfigurationManager

        config_manager = ConfigurationManager(target_env, PROJECT_ROOT)
        project_vars = config_manager.get_env_vars()

        # Inject into os.environ so Pydantic can see them
        # Only update environment with string values
        string_vars = {k: v for k, v in project_vars.items() if isinstance(v, str)}
        os.environ.update(string_vars)

        # Create base settings
        # Filter out non-primitive types that Pydantic BaseSettings might choke on via **kwargs if not defined in model
        # Actually, we should just pass everything and let Pydantic ignore extras or valid fields handle it.
        # But specifically for the NameError fix:
        base_settings = PlatformSettings(
            project_root=PROJECT_ROOT,
            environment=target_env,
            **project_vars,  # type: ignore[arg-type]
        )

        _settings_cache[target_env] = base_settings
        return base_settings


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

settings = get_settings()
