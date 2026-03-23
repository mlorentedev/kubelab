"""Kubernetes manifest generator using Jinja2 templates."""

from typing import Any

from toolkit.config.constants import COMPONENTS, PATH_STRUCTURES, VALIDATION_RULES
from toolkit.core.logging import logger
from toolkit.core.templating import create_renderer
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_base import BaseGenerator


class K8sGenerator(BaseGenerator):
    """Generates Kubernetes manifests from Jinja2 templates.

    Same pattern as TraefikGenerator: reads config from values/*.yaml,
    builds structured context, renders templates to generated/{env}/.
    Dev environment is skipped (uses Docker Compose).
    """

    # Metadata suffixes to skip when building ConfigMap env vars
    _METADATA_SUFFIXES = frozenset(
        {
            "NAME",
            "DOMAIN",
            "IMAGE_NAME",
            "VERSION",
            "DEFAULT_PORT",
            "HEALTH_PATH",
            "ENABLE_AUTH",
            "AUTH_LEVEL",
            "ENABLE_COMPRESS",
        }
    )

    # Template files to render (template_name, output_name)
    _TEMPLATE_MAP = [
        ("kustomization.yaml.j2", "kustomization.yaml"),
        ("deployments.yaml.j2", "deployments.yaml"),
        ("services.yaml.j2", "services.yaml"),
        ("configmaps.yaml.j2", "configmaps.yaml"),
        ("ingress.yaml.j2", "ingress.yaml"),
    ]

    def generate(self, env: str) -> dict[str, Any]:
        """Generate K8s manifests for the specified environment.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        if env == "dev":
            logger.info("Skipping K8s generation for dev (uses Docker Compose)")
            return {"success": True, "files": []}

        logger.info(f"Generating K8s manifests for {env}")

        templates_dir = self.project_root / PATH_STRUCTURES.K8S_TEMPLATES_DIR
        output_dir = self.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR / env

        if not templates_dir.exists():
            logger.error(f"K8s templates directory not found: {templates_dir}")
            return {"success": False, "error": "Templates directory not found"}

        try:
            context = self._build_context(env)
            renderer = create_renderer(templates_dir)
            generated_files = []

            for template_name, output_name in self._TEMPLATE_MAP:
                output_file = output_dir / output_name
                if renderer.render_template(template_name, output_file, context):
                    generated_files.append(str(output_file))
                    logger.info(f"Generated: {output_file}")
                else:
                    return {"success": False, "error": f"Failed to render {template_name}"}

            logger.success(f"Generated {len(generated_files)} K8s manifest files")
            return {"success": True, "files": generated_files}

        except FileNotFoundError as e:
            logger.error(f"Template directory error: {e}")
            return {"success": False, "error": str(e)}

        except Exception as e:
            logger.error(f"Failed to generate K8s manifests: {e}")
            return {"success": False, "error": str(e)}

    def validate(self) -> bool:
        """Validate K8s templates and generated files exist.

        Returns:
            True if validation passes, False otherwise
        """
        templates_dir = self.project_root / PATH_STRUCTURES.K8S_TEMPLATES_DIR
        if not templates_dir.exists():
            logger.error(f"K8s templates directory not found: {templates_dir}")
            return False

        required_templates = [t for t, _ in self._TEMPLATE_MAP]
        missing = [t for t in required_templates if not (templates_dir / t).exists()]
        if missing:
            logger.warning(f"Missing K8s templates: {', '.join(missing)}")
            return False

        # Check overlay files for staging/prod
        overlays_dir = self.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR
        missing_overlays = []
        for env in ("staging", "prod"):
            env_dir = overlays_dir / env
            if not env_dir.exists():
                missing_overlays.append(f"overlays/{env}/")
                continue
            for _, output_name in self._TEMPLATE_MAP:
                if not (env_dir / output_name).exists():
                    missing_overlays.append(f"overlays/{env}/{output_name}")

        if missing_overlays:
            logger.warning(f"Missing K8s overlay files: {', '.join(missing_overlays)}")
            return False

        logger.success("K8s configuration validation passed")
        return True

    def _find_var(self, env_vars: dict[str, str], component: str, suffix: str) -> str | None:
        """Find variable value for a component by searching hierarchical paths.

        Same logic as TraefikGenerator._find_var — duplicated intentionally
        per "3 uses" rule (extract to shared util on third consumer).

        Args:
            env_vars: Flattened environment variables dictionary
            component: Component name (e.g., 'api', 'grafana')
            suffix: Variable suffix (e.g., 'DOMAIN', 'DEFAULT_PORT')

        Returns:
            Variable value if found, None otherwise
        """
        component_upper = component.upper().replace("-", "_")

        search_paths = [
            f"APPS_PLATFORM_{component_upper}_{suffix}",
            f"APPS_SERVICES_CORE_{component_upper}_{suffix}",
            f"APPS_SERVICES_DATA_{component_upper}_{suffix}",
            f"APPS_SERVICES_OBSERVABILITY_{component_upper}_{suffix}",
            f"APPS_SERVICES_SECURITY_{component_upper}_{suffix}",
            f"APPS_SERVICES_AUTOMATION_{component_upper}_{suffix}",
            f"APPS_SERVICES_MISC_{component_upper}_{suffix}",
            f"APPS_SERVICES_AI_{component_upper}_{suffix}",
            f"EDGE_{component_upper}_{suffix}",
        ]

        for path in search_paths:
            if path in env_vars:
                return env_vars[path]
        return None

    def _build_context(self, env: str) -> dict[str, Any]:
        """Build Jinja2 context for K8s templates.

        Args:
            env: Environment name (staging, prod)

        Returns:
            Dictionary containing all template variables
        """
        config_manager = ConfigurationManager(env, self.project_root)
        env_vars = config_manager.get_env_vars()

        registry = env_vars.get("REGISTRY", "docker.io/mlorentedev")
        namespace = "kubelab"

        # Default resource limits from global config
        default_resources = {
            "memory_limit": self._normalize_memory(env_vars.get("RESOURCES_DEFAULT_MEMORY_LIMIT", "512Mi")),
            "memory_request": self._normalize_memory(env_vars.get("RESOURCES_DEFAULT_MEMORY_RESERVATION", "256Mi")),
            "cpu_limit": env_vars.get("RESOURCES_DEFAULT_CPU_LIMIT", "0.5"),
            "cpu_request": env_vars.get("RESOURCES_DEFAULT_CPU_RESERVATION", "0.25"),
        }

        apps = []
        for component in COMPONENTS.PLATFORM_APPS:
            image_name = self._find_var(env_vars, component, "IMAGE_NAME")
            domain = self._find_var(env_vars, component, "DOMAIN")
            port = self._find_var(env_vars, component, "DEFAULT_PORT")

            # Skip apps without required fields (e.g., wiki removed, workers no domain)
            if not image_name or not domain or not port:
                logger.debug(f"Skipping {component}: missing image_name, domain, or port")
                continue

            version = self._find_var(env_vars, component, "VERSION") or "latest"
            health_path = self._find_var(env_vars, component, "HEALTH_PATH")
            enable_auth_val = self._find_var(env_vars, component, "ENABLE_AUTH")
            enable_auth = bool(enable_auth_val and enable_auth_val.lower() in ("true", "1", "yes"))

            image = f"{registry}/{image_name}:{version}"

            # ConfigMap env vars (non-secret, non-metadata)
            app_env_vars = self._extract_app_env_vars(env_vars, component)
            app_env_vars["ENVIRONMENT"] = env

            # Check if app has secret-pattern vars (needs a K8s Secret)
            has_secrets = self._has_secret_vars(env_vars, component)

            # Middleware list for IngressRoute
            middlewares = self._build_middlewares(env_vars, enable_auth)

            # Per-app resources (fall back to defaults)
            app_resources = self._build_resources(env_vars, component, default_resources)

            apps.append(
                {
                    "name": component,
                    "image": image,
                    "port": int(port),
                    "domain": domain,
                    "health_path": health_path,
                    "enable_auth": enable_auth,
                    "has_secrets": has_secrets,
                    "env_vars": app_env_vars,
                    "resources": app_resources,
                    "middlewares": middlewares,
                }
            )

        cert_resolver = env_vars.get("EDGE_TRAEFIK_CERT_RESOLVER", "letsencrypt")

        logger.info(f"Built K8s context with {len(apps)} apps for {env}")

        return {
            "env": env,
            "namespace": namespace,
            "apps": apps,
            "cert_resolver": cert_resolver,
        }

    def _extract_app_env_vars(self, env_vars: dict[str, str], component: str) -> dict[str, str]:
        """Extract non-secret, non-metadata env vars for a component's ConfigMap.

        Args:
            env_vars: Flattened environment variables
            component: Component name

        Returns:
            Dictionary of env var name -> value for the ConfigMap
        """
        component_upper = component.upper().replace("-", "_")
        prefix = f"APPS_PLATFORM_{component_upper}_"

        result: dict[str, str] = {}
        for key, value in env_vars.items():
            if not key.startswith(prefix):
                continue

            suffix = key[len(prefix) :]

            # Skip metadata keys
            if suffix in self._METADATA_SUFFIXES:
                continue

            # Skip resource-related keys
            if suffix.startswith("RESOURCES_"):
                continue

            # Skip secret-pattern keys (exact word match, not substring)
            parts = suffix.split("_")
            if any(part in VALIDATION_RULES.SECRET_PATTERNS for part in parts):
                continue

            result[suffix] = str(value)

        return result

    def _has_secret_vars(self, env_vars: dict[str, str], component: str) -> bool:
        """Check if a component has any secret-pattern environment variables.

        Args:
            env_vars: Flattened environment variables
            component: Component name

        Returns:
            True if the component has vars matching SECRET_PATTERNS
        """
        component_upper = component.upper().replace("-", "_")
        prefix = f"APPS_PLATFORM_{component_upper}_"

        for key in env_vars:
            if not key.startswith(prefix):
                continue
            suffix = key[len(prefix) :]
            if suffix in self._METADATA_SUFFIXES or suffix.startswith("RESOURCES_"):
                continue
            parts = suffix.split("_")
            if any(part in VALIDATION_RULES.SECRET_PATTERNS for part in parts):
                return True
        return False

    def _build_middlewares(self, env_vars: dict[str, str], enable_auth: bool) -> list[str]:
        """Build IngressRoute middleware list.

        Args:
            env_vars: Flattened environment variables
            enable_auth: Whether authentication is enabled for this app

        Returns:
            List of middleware references
        """
        middlewares = []
        if enable_auth:
            authelia_name = env_vars.get("APPS_SERVICES_SECURITY_AUTHELIA_NAME", "authelia")
            middlewares.append(f"{authelia_name}-auth@kubernetescrd")
        return middlewares

    def _build_resources(
        self,
        env_vars: dict[str, str],
        component: str,
        defaults: dict[str, str],
    ) -> dict[str, str]:
        """Build resource limits/requests for a component.

        Args:
            env_vars: Flattened environment variables
            component: Component name
            defaults: Default resource values

        Returns:
            Dictionary with memory_limit, memory_request, cpu_limit, cpu_request
        """
        resources = dict(defaults)

        overrides = {
            "memory_limit": ("RESOURCES_MEMORY_LIMIT", True),
            "memory_request": ("RESOURCES_MEMORY_RESERVATION", True),
            "cpu_limit": ("RESOURCES_CPU_LIMIT", False),
            "cpu_request": ("RESOURCES_CPU_RESERVATION", False),
        }

        for key, (suffix, is_memory) in overrides.items():
            value = self._find_var(env_vars, component, suffix)
            if value:
                resources[key] = self._normalize_memory(value) if is_memory else value

        return resources

    @staticmethod
    def _normalize_memory(value: str) -> str:
        """Normalize memory values from Docker format to K8s format.

        Docker uses '512m', K8s uses '512Mi'.

        Args:
            value: Memory value string (e.g., '512m', '256M', '1G')

        Returns:
            K8s-compatible memory string
        """
        value = value.strip()
        # Docker lowercase 'm' (megabytes) -> K8s 'Mi' (mebibytes)
        if value.endswith("m") and not value.endswith("Mi"):
            return value[:-1] + "Mi"
        # Docker lowercase 'g' (gigabytes) -> K8s 'Gi' (gibibytes)
        if value.endswith("g") and not value.endswith("Gi"):
            return value[:-1] + "Gi"
        return value
