"""Traefik reverse proxy configuration generator."""

from typing import Any

from toolkit.config.constants import COMPONENTS, MESSAGES, PATH_STRUCTURES
from toolkit.core.logging import logger
from toolkit.core.templating import create_renderer
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_base import BaseGenerator


class TraefikGenerator(BaseGenerator):
    """Handles Traefik configuration generation using Jinja2 templates."""

    def generate(self, env: str) -> dict[str, Any]:
        """Generate Traefik configuration using Jinja2 templates.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        logger.info(f"Generating Traefik configuration for {env}")

        # Use new path structure
        templates_dir = self.project_root / PATH_STRUCTURES.TRAEFIK_TEMPLATES_DIR
        output_base_dir = self.project_root / PATH_STRUCTURES.TRAEFIK_CONFIG_OUTPUT_DIR
        output_dir = output_base_dir / env

        if not templates_dir.exists():
            logger.error(f"Traefik templates directory not found: {templates_dir}")
            return {"success": False, "error": "Templates directory not found"}

        try:
            # Build context from environment variables
            context = self._build_context(env)

            # Create Jinja2 renderer
            renderer = create_renderer(templates_dir)

            generated_files = []

            # Generate static configuration (main traefik.yml)
            main_output = output_dir / "traefik.yml"
            if renderer.render_template("traefik.yml.j2", main_output, context):
                generated_files.append(str(main_output))
                logger.info(f"Generated static config: {main_output}")
            else:
                return {
                    "success": False,
                    "error": "Failed to render traefik.yml template",
                }

            # Generate dynamic configurations
            dynamic_templates = [
                ("apps.yml.j2", "apps.yml"),
                ("middlewares.yml.j2", "middlewares.yml"),
            ]

            # Generate TLS config if HTTPS is enabled
            disable_https = context.get("DISABLE_HTTPS", "false")
            if str(disable_https).lower() != "true":
                dynamic_templates.append(("tls.yml.j2", "tls.yml"))

            for template_name, output_name in dynamic_templates:
                output_file = output_dir / "dynamic" / output_name
                if renderer.render_template(template_name, output_file, context):
                    generated_files.append(str(output_file))
                    logger.info(f"Generated dynamic config: {output_file}")
                else:
                    logger.warning(f"Failed to render {template_name}")

            logger.success(f"Generated {len(generated_files)} Traefik configuration files")
            return {"success": True, "files": generated_files}

        except FileNotFoundError as e:
            logger.error(f"Template directory error: {e}")
            return {"success": False, "error": str(e)}

        except Exception as e:
            logger.error(f"Failed to generate Traefik config: {e}")
            return {"success": False, "error": str(e)}

    def validate(self) -> bool:
        """Validate Traefik configuration files.

        Returns:
            True if validation passes, False otherwise
        """
        try:
            from toolkit.config.settings import settings

            # Check compose files in stacks directory
            if not settings.traefik_dir.exists():
                logger.error(MESSAGES.ERROR_CONFIG_TRAEFIK_DIR_NOT_FOUND.format(settings.traefik_dir))
                return False

            compose_files = [
                "compose.base.yml",
                "compose.dev.yml",
                "compose.staging.yml",
                "compose.prod.yml",
            ]
            missing_files = [f for f in compose_files if not (settings.traefik_dir / f).exists()]

            # Check generated files in edge/traefik/generated/ (only for envs already generated)
            generated_dir = self.project_root / PATH_STRUCTURES.TRAEFIK_CONFIG_OUTPUT_DIR
            for env in ("dev", "staging", "prod"):
                env_dir = generated_dir / env
                if env_dir.exists():
                    generated_file = env_dir / "traefik.yml"
                    if not generated_file.exists():
                        missing_files.append(f"generated/{env}/traefik.yml")

            if missing_files:
                logger.warning(MESSAGES.WARNING_CONFIG_MISSING_TRAEFIK_FILES.format(", ".join(missing_files)))
                return False

            logger.success(MESSAGES.SUCCESS_CONFIG_TRAEFIK_VALIDATION_PASSED)
            return True
        except Exception:
            return False

    def _find_var(self, env_vars: dict[str, str], component: str, suffix: str) -> str | None:
        """Find variable value for a component by searching hierarchical paths.

        Args:
            env_vars: Environment variables dictionary
            component: Component name (e.g., 'api', 'grafana')
            suffix: Variable suffix (e.g., 'DOMAIN', 'DEFAULT_PORT')

        Returns:
            Variable value if found, None otherwise
        """
        component_upper = component.upper().replace("-", "_")

        # Search paths in order of preference
        search_paths = [
            f"APPS_PLATFORM_{component_upper}_{suffix}",  # apps.platform.*
            f"APPS_SERVICES_CORE_{component_upper}_{suffix}",  # apps.services.core.*
            f"APPS_SERVICES_DATA_{component_upper}_{suffix}",  # apps.services.data.*
            f"APPS_SERVICES_OBSERVABILITY_{component_upper}_{suffix}",  # apps.services.observability.*
            f"APPS_SERVICES_SECURITY_{component_upper}_{suffix}",  # apps.services.security.*
            f"APPS_SERVICES_AUTOMATION_{component_upper}_{suffix}",  # apps.services.automation.*
            f"APPS_SERVICES_MISC_{component_upper}_{suffix}",  # apps.services.misc.*
            f"APPS_SERVICES_AI_{component_upper}_{suffix}",  # apps.services.ai.*
            f"EDGE_{component_upper}_{suffix}",  # edge.*
        ]

        for path in search_paths:
            if path in env_vars:
                return env_vars[path]

        return None

    def _build_context(self, env: str) -> dict[str, Any]:
        """Build Jinja2 context for Traefik templates.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary containing all template variables
        """
        # Load environment files
        config_manager = ConfigurationManager(env, self.project_root)
        env_vars = config_manager.get_env_vars()

        # Build apps list with full metadata
        apps = []

        # Add special entry for Traefik Dashboard (always first)
        traefik_host = env_vars.get("EDGE_TRAEFIK_DOMAIN", "")
        apps.append(
            {
                "name": "traefik-dashboard",
                "host": traefik_host,
                "port": env_vars.get("EDGE_TRAEFIK_DASHBOARD_PORT", ""),
                "enable_auth": True,
                "enable_compress": False,
                "is_traefik_dashboard": True,
                "auth_level": "one_factor",
            }
        )

        # Combine all component types (platform apps + third-party services + edge)
        all_components = [
            *COMPONENTS.PLATFORM_APPS,
            *COMPONENTS.ALL_SERVICES,
            *COMPONENTS.EDGE,
        ]

        for component in all_components:
            # Skip traefik - already handled as traefik-dashboard
            if component == "traefik":
                continue

            # Get app_name (defaults to component name if not specified)
            app_name = self._find_var(env_vars, component, "NAME") or component

            # --- Special Case: MinIO Console ---
            if component == "minio":
                console_domain = self._find_var(env_vars, component, "CONSOLE_DOMAIN")
                console_port = self._find_var(env_vars, component, "DEFAULT_PORT_CONSOLE")

                if console_domain and console_port:
                    apps.append(
                        {
                            "name": f"{app_name}-console",
                            "host": console_domain,
                            "port": console_port,
                            "backend_host": app_name,  # Same container
                            "enable_auth": False,  # Let MinIO handle OIDC
                            "enable_compress": True,
                            "health_path": "/",
                            "auth_level": "bypass",
                        }
                    )

            # Determine host and port using hierarchical search
            host = ""
            port = ""

            # --- Determine Host ---
            # Try hierarchical search first
            host = self._find_var(env_vars, component, "DOMAIN") or self._find_var(env_vars, component, "HOST") or ""

            # Special cases for edge services
            if not host and component == "traefik":
                host = env_vars.get("EDGE_TRAEFIK_DOMAIN", "")
            elif not host and component == "authelia":
                # Authelia might be in APPS_SERVICES_SECURITY_AUTHELIA_DOMAIN
                host = self._find_var(env_vars, component, "DOMAIN") or app_name

            # Fallback to app_name (internal Docker hostname)
            if not host:
                host = app_name

            # --- Determine Port ---
            port = self._find_var(env_vars, component, "DEFAULT_PORT") or ""

            # Special case for minio (has both API and console ports)
            if not port and component == "minio":
                port = self._find_var(env_vars, component, "DEFAULT_PORT_API") or ""

            # Special case for traefik
            if not port and component == "traefik":
                port = self._find_var(env_vars, component, "DEFAULT_PORT") or "443"

            # Only include if both host and port exist and host is not just an
            # internal app_name (unless it's Authelia/Traefik)
            if not host or not port:
                logger.debug(f"Skipping app '{app_name}' due to missing host or port.")
                continue

            # Special filter to ensure apps without external domain don't get routers unless special
            if host == app_name and app_name not in ["authelia", "traefik"]:
                logger.debug(f"Skipping app '{app_name}' (internal-only service).")
                continue

            # Determine auth requirement (sensitive services)
            sensitive_services = {"traefik", "grafana", "kestra", "loki"}
            enable_auth = component.lower() in sensitive_services

            # Check for explicit override
            enable_auth_val = self._find_var(env_vars, component, "ENABLE_AUTH")
            if enable_auth_val:
                enable_auth = enable_auth_val.lower() in ("true", "1", "yes")

            # Compression enabled by default
            enable_compress = True
            enable_compress_val = self._find_var(env_vars, component, "ENABLE_COMPRESS")
            if enable_compress_val:
                enable_compress = enable_compress_val.lower() in ("true", "1", "yes")

            apps.append(
                {
                    "name": app_name,
                    "host": host,
                    "port": port,
                    "backend_host": app_name,  # Default backend_host to app_name (internal Docker service name)
                    "enable_auth": enable_auth,
                    "enable_compress": enable_compress,
                    "health_path": self._find_var(env_vars, component, "HEALTH_PATH"),
                    "auth_level": self._find_var(env_vars, component, "AUTH_LEVEL") or "bypass",
                }
            )

        logger.info(f"Built apps list with {len(apps)} components")

        # Build template context with variable name mapping
        # Templates expect specific names, map from EDGE_TRAEFIK_* to TRAEFIK_*
        context: dict[str, Any] = {}

        # Variables that need to keep TRAEFIK_ prefix in templates
        TRAEFIK_PREFIXED = {
            "DASHBOARD",
            "INSECURE",
            "ENTRYPOINT",
            "DASHBOARD_AUTH_MIDDLEWARE",
            "DASHBOARD_SECURITY_MIDDLEWARE",
        }

        # Map all EDGE_TRAEFIK_* vars for template compatibility
        for key, value in env_vars.items():
            if key.startswith("EDGE_TRAEFIK_"):
                # Extract the suffix after EDGE_TRAEFIK_
                suffix = key.replace("EDGE_TRAEFIK_", "")

                # Check if this var needs TRAEFIK_ prefix
                if suffix in TRAEFIK_PREFIXED:
                    template_key = f"TRAEFIK_{suffix}"
                else:
                    # Remove EDGE_TRAEFIK_ completely for most vars
                    # e.g., EDGE_TRAEFIK_ACCESS_LOG_FORMAT → ACCESS_LOG_FORMAT
                    template_key = suffix

                context[template_key] = value

            context[key] = value

        # Add special mappings for template compatibility
        context.update(
            {
                # Template uses DOMAIN, we have BASE_DOMAIN
                "DOMAIN": env_vars.get("BASE_DOMAIN", "") or env_vars.get("GLOBAL_BASE_DOMAIN", ""),
                # Template uses DOCKER_NETWORK, we have NETWORK_NAME
                "DOCKER_NETWORK": env_vars.get("NETWORK_NAME", ""),
                # Errors service reference (for error-pages middleware)
                "APP_ERRORS_NAME": env_vars.get("EDGE_ERRORS_NAME", ""),
                "APP_ERRORS_PORT": env_vars.get("EDGE_ERRORS_PORT", ""),
                "EDGE_TRAEFIK_DOMAIN": env_vars.get("EDGE_TRAEFIK_DOMAIN", ""),
                "EDGE_ERRORS_DOMAIN": env_vars.get("EDGE_ERRORS_DOMAIN", ""),
                # Authelia compatibility aliases (for middlewares template)
                "APPS_AUTHELIA_NAME": env_vars.get("APPS_SERVICES_SECURITY_AUTHELIA_NAME", "authelia"),
                "APPS_AUTHELIA_DEFAULT_PORT": env_vars.get("APPS_SERVICES_SECURITY_AUTHELIA_DEFAULT_PORT", "9091"),
                "APPS_AUTHELIA_DOMAIN": env_vars.get("APPS_SERVICES_SECURITY_AUTHELIA_DOMAIN", ""),
                # Apps list
                "apps": apps,
                "env": env,
            }
        )

        logger.debug(f"Context built with {len(context)} variables and {len(apps)} apps")
        return context


# Global instance
traefik_generator = TraefikGenerator()
