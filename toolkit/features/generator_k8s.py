"""Kubernetes manifest generator using Jinja2 templates."""

import hashlib
from typing import Any

from toolkit.config.constants import PATH_STRUCTURES, VALIDATION_RULES
from toolkit.core.logging import logger
from toolkit.core.templating import create_renderer
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_base import BaseGenerator
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, pull_secret_name
from toolkit.features.product_contract import JobClaim, VolumeClaim, validate_contract
from toolkit.features.product_registry import product
from toolkit.features.product_render import SNAPSHOT_DIR, snapshot_path


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
            "READINESS_PATH",
            "ENABLE_AUTH",
            "AUTH_LEVEL",
            "ENABLE_COMPRESS",
            # Routing topology, not runtime config. It is also the only entry
            # here whose value is a list rather than a string: `_flatten_dict`
            # keeps lists intact, so without this exclusion it would land in the
            # ConfigMap as a Python repr, changing the configMapGenerator hash
            # and rolling the pod on every deploy.
            "EXTRA_ROUTES",
        }
    )

    # Deploy-concern trailing tokens — image refs and version pins are never
    # runtime env. The _METADATA_SUFFIXES check above only fires on the
    # prefix-stripped (APPS_PLATFORM_*) form; shared INFRA_* keys reach this
    # method unstripped (e.g. INFRA_POSTGRES_IMAGE), so match the trailing
    # segment to keep a shared image pin (ADR-051 D4) out of every ConfigMap.
    _DEPLOY_CONCERN_SUFFIXES = frozenset({"IMAGE", "VERSION"})

    # Placement-classification keys (ADR-061). `state_promotion` and `location`
    # record where a stateful service's state may live; they are read by a
    # static gate, never by a running pod. Same category as the deploy concerns
    # above, but they cannot use the same mechanism — see `_placement_keys`.
    #
    # Seven of the eight classified services live under `apps.services.*`, which
    # this method never picks up (it only reads APPS_PLATFORM_* and INFRA_*), so
    # they need no exclusion. The eighth, `postgres`, is at `infra.postgres` per
    # ADR-051 — without this guard its two classification keys would be emitted
    # into EVERY component's ConfigMap as INFRA_POSTGRES_*, changing every
    # configMapGenerator hash and rolling every pod on the next deploy.
    _PROMOTION_SUFFIX = "STATE_PROMOTION"
    _LOCATION_SUFFIX = "LOCATION"

    # Template files to render (template_name, output_name)
    # kustomization.yaml is NOT generated — it's manual (ADR-027, NET-002)
    _TEMPLATE_MAP = [
        ("deployments.yaml.j2", "deployments.yaml"),
        ("services.yaml.j2", "services.yaml"),
        ("configmaps.yaml.j2", "configmaps.yaml"),
        ("migrations.yaml.j2", "migrations.yaml"),
        ("ingress.yaml.j2", "ingress.yaml"),
        ("hooks.yaml.j2", "hooks.yaml"),
        ("claims.yaml.j2", "claims.yaml"),
    ]

    # Where each env's contract snapshots live; a class attribute so a test can point it at a fixture tree.
    snapshot_dir = SNAPSHOT_DIR

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
        output_dir = self.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR / env / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)

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

        # Check overlay structure (ADR-021 Rev2: manual Kustomize overlays)
        overlays_dir = self.project_root / PATH_STRUCTURES.K8S_OVERLAYS_DIR
        missing_overlays = []
        for env in ("staging", "prod"):
            env_dir = overlays_dir / env
            if not env_dir.exists():
                missing_overlays.append(f"overlays/{env}/")
                continue
            if not (env_dir / "kustomization.yaml").exists():
                missing_overlays.append(f"overlays/{env}/kustomization.yaml")

        if missing_overlays:
            logger.warning(f"Missing K8s overlay files: {', '.join(missing_overlays)}")
            return False

        logger.success("K8s configuration validation passed")
        return True

    def _health_paths(self, env_vars: dict[str, str], component: str) -> tuple[str | None, str | None]:
        """Return (liveness path, readiness path) for a component.

        Liveness is `health_path`. Readiness is `readiness_path` when the app declares
        one and falls back to `health_path`, so only apps that distinguish "alive" from
        "ready" (api: `/health` vs `/ready`) render different probes. Keeping them apart
        matters: a dependency problem behind readiness must take the pod out of rotation,
        never restart it.
        """
        health_path = self._find_var(env_vars, component, "HEALTH_PATH")
        readiness_path = self._find_var(env_vars, component, "READINESS_PATH") or health_path
        return health_path, readiness_path

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

    def _resolve_pull_policy(self, version: str) -> str:
        """Explicit imagePullPolicy by tag mutability (ADR-046; lesson 2026-03-16).

        Mutable tags (``dev``, ``latest``, RC pre-releases) must re-pull on every
        rollout so the staging test bed actually refreshes; immutable tags (semver
        releases, ``sha-*`` build tags) never change, so ``IfNotPresent`` is correct
        and avoids needless registry round-trips. Never rely on Kubernetes'
        tag-name default (``latest`` -> Always, else -> IfNotPresent), which
        silently broke staging's mutable ``:dev`` strategy.
        """
        mutable = version in ("dev", "latest") or "-rc." in version or version.endswith("-rc")
        return "Always" if mutable else "IfNotPresent"

    def _build_context(self, env: str) -> dict[str, Any]:
        """Build Jinja2 context for K8s templates.

        Args:
            env: Environment name (staging, prod)

        Returns:
            Dictionary containing all template variables
        """
        config_manager = ConfigurationManager(env, self.project_root)
        env_vars = config_manager.get_env_vars()

        default_registry = env_vars.get("REGISTRY", "docker.io/mlorentedev")
        namespace = "kubelab"

        # Default resource limits from global config
        default_resources = {
            "memory_limit": self._normalize_memory(env_vars.get("RESOURCES_DEFAULT_MEMORY_LIMIT", "512Mi")),
            "memory_request": self._normalize_memory(env_vars.get("RESOURCES_DEFAULT_MEMORY_RESERVATION", "256Mi")),
            "cpu_limit": env_vars.get("RESOURCES_DEFAULT_CPU_LIMIT", "0.5"),
            "cpu_request": env_vars.get("RESOURCES_DEFAULT_CPU_RESERVATION", "0.25"),
        }

        apps = []
        # An app with no pin in this env is not deployed there (BaseGenerator.pinned_platform_apps).
        pinned = self.pinned_platform_apps(env_vars, env)
        for component in pinned:
            image_name = self._find_var(env_vars, component, "IMAGE_NAME")
            domain = self._find_var(env_vars, component, "DOMAIN")
            port = self._find_var(env_vars, component, "DEFAULT_PORT")

            # Skip apps without required fields (e.g., wiki removed, workers no domain)
            if not image_name or not domain or not port:
                logger.debug(f"Skipping {component}: missing image_name, domain, or port")
                continue

            version = pinned[component]
            health_path, readiness_path = self._health_paths(env_vars, component)
            enable_auth_val = self._find_var(env_vars, component, "ENABLE_AUTH")
            enable_auth = bool(enable_auth_val and enable_auth_val.lower() in ("true", "1", "yes"))

            # The registry is the product's own (IDP-053 D4); only an entry that names none uses the platform's.
            entry = product(component)
            registry = entry.image_registry or default_registry
            image = f"{registry}/{image_name}:{version}"
            image_pull_policy = self._resolve_pull_policy(version)
            # Only a private entry names the Secret `apply-secrets` renders for its registry host (D6,
            # `pull_secret_mappings`); a registry host alone does not make an image private.
            image_pull_secret = pull_secret_name(entry.image_host) if entry.private and entry.image_host else None

            # ConfigMap env vars (non-secret, non-metadata)
            app_env_vars = self._extract_app_env_vars(env_vars, component)
            app_env_vars["ENVIRONMENT"] = env

            # Mount <app>-secrets iff one is defined in the secrets SSOT.
            has_secrets = self._has_secret_vars(component)

            # Middleware list for IngressRoute
            middlewares = self._build_middlewares(env_vars, enable_auth)

            # Per-app resources (fall back to defaults)
            app_resources = self._build_resources(env_vars, component, default_resources)

            volumes, jobs = self._build_claims(component, env)

            apps.append(
                {
                    "name": component,
                    "image": image,
                    "image_pull_policy": image_pull_policy,
                    "image_pull_secret": image_pull_secret,
                    "port": int(port),
                    "domain": domain,
                    "health_path": health_path,
                    "readiness_path": readiness_path,
                    "enable_auth": enable_auth,
                    "has_secrets": has_secrets,
                    "env_vars": app_env_vars,
                    "resources": app_resources,
                    "middlewares": middlewares,
                    "extra_routes": self._build_extra_routes(env_vars, component),
                    "volumes": volumes,
                    "jobs": jobs,
                    "fs_group": self._fs_group(component, volumes),
                }
            )

        cert_resolver = env_vars.get("EDGE_TRAEFIK_CERT_RESOLVER", "letsencrypt")

        logger.info(f"Built K8s context with {len(apps)} apps for {env}")

        return {
            "env": env,
            "namespace": namespace,
            "apps": apps,
            "cert_resolver": cert_resolver,
            "route_probe_image": env_vars.get("ARGOCD_ROUTE_PROBE_IMAGE", ""),
            "migrations": self._build_migrations(env_vars),
        }

    def _build_claims(self, component: str, env: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The volume and job claims of ``component``'s contract snapshot for ``env``.

        Read from the snapshot and not through values (D6): ``_extract_app_env_vars`` would
        flatten a claim into pod environment variables. An app with no snapshot claims nothing.
        """
        path = snapshot_path(component, env, self.snapshot_dir)
        if not path.exists():
            return [], []
        resources = validate_contract(path).resources
        volumes = {
            name: {
                "name": name,
                "claim": f"{component}-{name}",
                "size": claim.params.size,
                "mount_path": claim.params.mount_path,
                "fs_group": claim.params.fs_group,
            }
            for name, claim in resources.items()
            if isinstance(claim, VolumeClaim)
        }
        jobs = [
            {
                "name": name,
                "schedule": claim.params.schedule,
                "command": claim.params.command,
                "active_deadline_seconds": claim.params.active_deadline_seconds,
                "volume": volumes[claim.params.volume],
            }
            for name, claim in resources.items()
            if isinstance(claim, JobClaim)
        ]
        return list(volumes.values()), jobs

    @staticmethod
    def _fs_group(component: str, volumes: list[dict[str, Any]]) -> int | None:
        """The one group every volume of the pod is owned by, or None when no claim names one.

        A pod has a single ``fsGroup``; two volumes asking for different ones cannot both be honoured.
        """
        groups = {v["fs_group"] for v in volumes if v["fs_group"]}
        if len(groups) > 1:
            raise ValueError(f"{component}: volume claims name different fs_group values {sorted(groups)}")
        return groups.pop() if groups else None

    def _build_migrations(self, env_vars: dict[str, str]) -> dict[str, Any]:
        """The API's Atlas migration directory, with a hash of everything the Job renders from.

        A Job's spec is immutable, so anything that changes the rendered Job has to change its
        name, or the sync that applies it is refused (DATA-007).
        """
        files = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted((self.project_root / "apps" / "api" / "migrations").iterdir())
            if path.is_file()
        }
        job = {
            "image": env_vars["INFRA_POSTGRES_ATLAS_IMAGE"],
            "tenant": env_vars["APPS_PLATFORM_API_POSTGRES_TENANT"],
            "host": env_vars["INFRA_POSTGRES_HOST"],
            "port": env_vars["INFRA_POSTGRES_PORT"],
        }
        template = self.project_root / "infra" / "k8s" / "templates" / "migrations.yaml.j2"
        digest = hashlib.sha256()
        for name, content in [*files.items(), *job.items(), ("template", template.read_text(encoding="utf-8"))]:
            digest.update(name.encode("utf-8"))
            digest.update(content.encode("utf-8"))
        return {"files": files, "hash": digest.hexdigest()[:10], **job}

    @classmethod
    def _placement_keys(cls, env_vars: dict[str, str]) -> frozenset[str]:
        """Exact env-var names carrying ADR-061 placement classification.

        `STATE_PROMOTION` is specific enough to exclude on its own. **`LOCATION`
        is not** — `INFRA_GEO_LOCATION` would be a perfectly ordinary runtime
        setting, and a suffix blocklist would silently drop it from every
        ConfigMap. Matching the full trailing suffix does not help: the false
        positive ends in `_LOCATION` exactly like the real key does.

        So the pair is resolved from the data instead of guessed from the name.
        ADR-061 D1 declares the two axes together on every classified service,
        so a `LOCATION` key is a classification key **iff its `STATE_PROMOTION`
        sibling travels with it**. That is derivable from the flat env map
        without knowing which services are classified, so no service list has
        to be maintained here in parallel with `common.yaml`.
        """
        excluded: set[str] = set()
        for key in env_vars:
            if key != cls._PROMOTION_SUFFIX and not key.endswith(f"_{cls._PROMOTION_SUFFIX}"):
                continue
            excluded.add(key)
            prefix = key[: -len(cls._PROMOTION_SUFFIX)]
            sibling = f"{prefix}{cls._LOCATION_SUFFIX}"
            if sibling in env_vars:
                excluded.add(sibling)
        return frozenset(excluded)

    def _extract_app_env_vars(self, env_vars: dict[str, str], component: str) -> dict[str, str]:
        """Extract non-secret, non-metadata env vars for a component's ConfigMap.

        Picks up two prefix classes (per ADR-036):
          - APPS_PLATFORM_<COMPONENT>_*  → suffix-stripped (component-local view).
            E.g. APPS_PLATFORM_API_HEALTH_PATH → HEALTH_PATH in the API pod.
          - INFRA_*                       → emitted as-is (shared infra services).
            E.g. INFRA_SMTP_USER stays INFRA_SMTP_USER in every component's
            ConfigMap. Lives at `infra.<service>.<attr>` in common.yaml.

        Args:
            env_vars: Flattened environment variables
            component: Component name

        Returns:
            Dictionary of env var name -> value for the ConfigMap
        """
        component_upper = component.upper().replace("-", "_")
        component_prefix = f"APPS_PLATFORM_{component_upper}_"
        shared_prefix = "INFRA_"

        placement_keys = self._placement_keys(env_vars)

        result: dict[str, str] = {}
        for key, value in env_vars.items():
            # Placement classification (ADR-061) — resolved on the raw key, so
            # the stripped and unstripped forms are handled by one rule.
            if key in placement_keys:
                continue

            if key.startswith(component_prefix):
                # Component-local: strip the prefix.
                name = key[len(component_prefix) :]
            elif key.startswith(shared_prefix):
                # Shared infra: keep the full name (ADR-036).
                name = key
            else:
                continue

            # Skip metadata keys (only meaningful for the stripped form)
            if name in self._METADATA_SUFFIXES:
                continue

            # Skip deploy-concern keys (image refs / version pins) in any form,
            # including unstripped INFRA_* (e.g. INFRA_POSTGRES_IMAGE). ADR-051 D4.
            if name.rsplit("_", 1)[-1] in self._DEPLOY_CONCERN_SUFFIXES:
                continue

            # Skip resource-related keys
            if name.startswith("RESOURCES_"):
                continue

            # Skip secret-pattern keys (exact word match, not substring)
            parts = name.split("_")
            if any(part in VALIDATION_RULES.SECRET_PATTERNS for part in parts):
                continue

            result[name] = str(value)

        return result

    def _build_extra_routes(self, env_vars: dict[str, Any], component: str) -> list[dict[str, Any]]:
        """Same-origin reverse-proxy routes on this app's own host (ADR-054).

        An app whose frontend calls an API at a *relative* path needs a second
        rule on the **same** host, matching that path prefix and pointing at a
        different service. Without it the request reaches the app itself — for a
        static site that means its own 404, which is exactly how the newsletter
        form broke (kubelab#774).

        Modelled in the SSOT rather than in the template on purpose. The
        alternative, `{% if app.name == 'web' %}`, has to be reopened for every
        future same-origin proxy and puts routing facts somewhere nobody greps.

        The target port is resolved from the target app's own `default_port`
        instead of being restated in the route entry: two places holding one
        port is how they drift.

        A route naming a service with no resolvable port is dropped with a
        warning rather than rendered half-formed — an IngressRoute pointing at
        port `None` fails at apply time, far from the typo that caused it.
        """
        raw: Any = self._find_var(env_vars, component, "EXTRA_ROUTES")
        if not raw:
            return []

        routes: list[dict[str, Any]] = []
        for entry in raw:
            service = entry["service"]
            port = self._find_var(env_vars, service, "DEFAULT_PORT")
            if not port:
                logger.warning(
                    f"Skipping extra_route {entry['path_prefix']} on {component}: "
                    f"no DEFAULT_PORT resolvable for target service '{service}'"
                )
                continue
            routes.append(
                {
                    "path_prefix": entry["path_prefix"],
                    "service": service,
                    "port": int(port),
                    # Must out-rank the host catch-all, and the number is not
                    # arbitrary. Traefik gives a router WITHOUT an explicit
                    # priority the LENGTH OF ITS RULE — so the bare
                    # `Host(`staging.mlorente.dev`)` catch-all sits at ~31, and
                    # an explicit `priority: 10` here put this route BELOW it.
                    # The route was generated, applied, and never matched.
                    #
                    # Anything comfortably above a realistic rule length works;
                    # 100 is that with room to spare. Lowering this below the
                    # catch-all's rule length silently disables the route.
                    "priority": int(entry.get("priority", 100)),
                }
            )
            if "probe" in entry:
                routes[-1]["probe"] = self._build_probe(entry["probe"], component, entry["path_prefix"])
        return routes

    _PROBE_FIELDS = ("method", "path", "expect_status", "expect_content_type")

    @classmethod
    def _build_probe(cls, raw: dict[str, Any], component: str, path_prefix: str) -> dict[str, Any]:
        """The request a route's `PostSync` hook sends, and the answer it requires (GITOPS-003 AC3).

        Every expectation is required: a probe missing one would pass on any
        answer, including the static site's, which is the failure it exists for.
        """
        missing = [f for f in cls._PROBE_FIELDS if f not in raw]
        if missing:
            raise ValueError(f"extra_route {path_prefix} on {component}: probe lacks {', '.join(missing)}")
        slug = path_prefix.strip("/").replace("/", "-") or "root"
        return {
            "name": f"{component}-route-probe-{slug}",
            "method": raw["method"],
            "path": raw["path"],
            "body": raw.get("body", ""),
            "expect_status": int(raw["expect_status"]),
            "expect_content_type": raw["expect_content_type"],
        }

    def _has_secret_vars(self, component: str) -> bool:
        """Whether a K8s Secret is defined for this component (→ mount it via envFrom).

        The single source of truth for which secrets exist is SECRET_DEFINITIONS
        (``k8s_secrets.py``). The deployment mounts ``<component>-secrets`` iff a
        mapping of that name is registered there.

        This deliberately replaces an env-var-pattern heuristic that was blind to
        *shared* ``INFRA_*`` secrets: ``INFRA_SMTP_PASS`` lives under the ``INFRA_``
        prefix, not ``APPS_PLATFORM_<COMPONENT>_``, so the heuristic returned False
        for ``api`` and the deployment never referenced ``api-secrets`` — the
        secret was provisioned but never injected, panicking images that require it
        at boot. Tying the mount to the registry keeps provisioning and consumption
        from silently diverging.

        Args:
            component: Component name

        Returns:
            True if a ``<component>-secrets`` mapping exists in SECRET_DEFINITIONS
        """
        secret_name = f"{component}-secrets"
        return any(mapping.name == secret_name for mapping in SECRET_DEFINITIONS)

    def _build_middlewares(self, env_vars: dict[str, str], enable_auth: bool) -> list[str]:
        """Build IngressRoute middleware list.

        Args:
            env_vars: Flattened environment variables
            enable_auth: Whether authentication is enabled for this app

        Returns:
            List of middleware references
        """
        # rate-limit sits between secure-headers and error-pages, matching the
        # VPS's own [secure-headers@file, rate-limit@file, error-pages] chain
        # (SEC-004 / kubelab#970). Blanket -- no enable_auth-style opt-out.
        middlewares = ["secure-headers", "rate-limit", "error-pages"]
        if enable_auth:
            authelia_name = env_vars.get("APPS_SERVICES_SECURITY_AUTHELIA_NAME", "authelia")
            # The Middleware object's own name (base/services/authelia.yaml), in the
            # routes' namespace. This emitted `<name>-auth@kubernetescrd`, an object that
            # never existed, unseen while no generated route asked for auth (CONSOLE-004).
            middlewares.append(authelia_name)
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
