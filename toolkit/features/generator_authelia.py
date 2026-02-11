# toolkit/features/generator_authelia.py
import os
from typing import Any

from toolkit.config.constants import AUTHELIA_CONFIG, COMPONENTS
from toolkit.core.logging import logger
from toolkit.core.templating import create_renderer
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_base import BaseGenerator


class AutheliaGenerator(BaseGenerator):
    """Handles Authelia configuration generation using Jinja2 templates."""

    def generate(self, env: str) -> dict[str, Any]:
        """Generate Authelia configuration files from templates.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        logger.info(f"Generating Authelia configuration for {env}")
        logger.debug(
            f"Effective UID: {os.geteuid()}, GID: {os.getegid()}"
        )  # Add this line

        templates_dir = (
            self.project_root / "infra" / "config" / "authelia" / "templates"
        )
        output_dir = (
            self.project_root / "infra" / "config" / "authelia" / "generated" / env
        )

        output_dir.mkdir(parents=True, exist_ok=True)  # Ensure output directory exists

        if not templates_dir.exists():
            logger.error(f"Authelia templates directory not found: {templates_dir}")
            return {"success": False, "error": "Templates directory not found"}

        try:
            # Build context for Authelia templates
            config_manager = ConfigurationManager(env, self.project_root)
            env_vars = config_manager.get_env_vars()  # All flat env vars

            # Build apps list with full metadata (similar to TraefikGenerator)
            apps = []
            all_components = [
                *COMPONENTS.APPS,
                *COMPONENTS.ALL_SERVICES,
            ]
            for component in all_components:
                component_upper = component.upper().replace("-", "_")
                host_key = f"APPS_{component_upper}_HOST"
                port_key = f"APPS_{component_upper}_DEFAULT_PORT"
                name_key = f"APPS_{component_upper}_NAME"

                if host_key not in env_vars or port_key not in env_vars:
                    continue

                app_name = env_vars.get(name_key, component)
                enable_auth = env_vars.get(
                    f"APPS_{component_upper}_ENABLE_AUTH", "false"
                ).lower() in ("true", "1", "yes")
                auth_level = env_vars.get(
                    f"APPS_{component_upper}_AUTH_LEVEL", "bypass"
                )

                # Check for special cases like Authelia itself
                if app_name == "authelia":
                    # Authelia does not protect itself with middleware
                    app_auth_level_for_config = "bypass"
                    app_host = env_vars.get(
                        f"APPS_{component_upper}_DOMAIN", ""
                    )  # Get its domain
                else:
                    app_auth_level_for_config = auth_level
                    app_host = env_vars[host_key]  # Use host for other apps

                apps.append(
                    {
                        "name": app_name,
                        "host": app_host,  # Use app_host, which can be app.domain for authelia
                        "port": env_vars[port_key],
                        # Use potentially overridden auth_level for authelia
                        "auth_level": app_auth_level_for_config,
                        "enable_auth": enable_auth,
                    }
                )

            # Read JWKS PEM key if it exists
            jwks_pem_path = (
                self.project_root
                / "infra"
                / "config"
                / "secrets"
                / f"{env}.oidc-jwks.pem"
            )
            jwks_key = ""
            if jwks_pem_path.exists():
                jwks_key = jwks_pem_path.read_text().strip()
            else:
                logger.warning(f"JWKS PEM not found: {jwks_pem_path}")
                logger.warning("Run 'toolkit credentials generate' to create it")

            # Get merged config (not flattened) to access user list and oidc clients
            merged_config = config_manager.get_merged_config()

            # Helper to get nested dict safely
            def get_nested(d: Any, keys: list[str], default: Any = None) -> Any:
                for key in keys:
                    if isinstance(d, dict):
                        d = d.get(key, default)
                    else:
                        return default
                return d

            authelia_config = get_nested(
                merged_config, ["apps", "services", "security", "authelia"], {}
            )

            # Access secrets directly (decrypted but not flattened) for precise key lookup
            # Note: config_manager.get_merged_config() already merges secrets into the config dict
            # So we can look for them in the same structure.

            # --- Build OIDC Clients List ---
            oidc_clients_config = authelia_config.get("oidc_clients", [])
            processed_oidc_clients = []

            # Use env_vars (flattened) to find secrets, as secrets structure (apps.authelia)
            # differs from config structure (apps.services.security.authelia)

            if not oidc_clients_config:
                # ... (Legacy fallback code remains the same) ...
                legacy_client_id = env_vars.get(
                    "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_ID"
                )
                legacy_secret_hash = env_vars.get(
                    "APPS_AUTHELIA_OIDC_CLIENT_SECRET_HASH"
                )
                legacy_redirect_uris = authelia_config.get(
                    "oidc_client_redirect_uri", []
                )
                if isinstance(legacy_redirect_uris, str):
                    legacy_redirect_uris = [legacy_redirect_uris]

                if legacy_client_id and legacy_secret_hash:
                    processed_oidc_clients.append(
                        {
                            "client_id": legacy_client_id,
                            "client_name": "CubeLab OIDC Client (Legacy)",
                            "client_secret_hash": legacy_secret_hash,
                            "redirect_uris": legacy_redirect_uris,
                            "scopes": ["openid", "profile", "email", "groups"],
                        }
                    )
            else:
                for client in oidc_clients_config:
                    client_id = client.get("client_id")
                    secret_suffix = (
                        client_id.replace("-oidc", "").replace("-", "_").upper()
                    )

                    # Construct expected env var keys for secrets using the LONG prefix found in debug
                    # Pattern: APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_{SUFFIX}_HASH

                    secret_hash_key = f"APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_{secret_suffix}_HASH"
                    secret_hash = env_vars.get(secret_hash_key)

                    # Fallback for 'cubelab-oidc' (main) to legacy/main var
                    if not secret_hash and (
                        secret_suffix == "CUBELAB" or secret_suffix == "MAIN"
                    ):
                        secret_hash = env_vars.get(
                            "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_HASH"
                        )

                    if not secret_hash:
                        logger.warning(
                            f"No secret hash found for OIDC client '{client_id}'. Expected env var: {secret_hash_key}"
                        )
                        # Use a placeholder to prevent template error, but log loudly
                        secret_hash = "hash_not_found_check_secrets"

                    processed_oidc_clients.append(
                        {
                            "client_id": client_id,
                            "client_name": client.get("client_name", client_id),
                            "client_secret_hash": secret_hash,
                            "redirect_uris": client.get("redirect_uris", []),
                            "scopes": client.get(
                                "scopes", ["openid", "profile", "email"]
                            ),
                        }
                    )

            # Build users list for template
            authelia_users = []
            users_config = authelia_config.get("users", [])

            for user in users_config:
                username = user.get("username", "")
                # Look for password hash in flattened env vars using the LONG prefix
                password_hash_key = f"APPS_SERVICES_SECURITY_AUTHELIA_USERS_{username.upper()}_PASSWORD_HASH"
                password_hash = env_vars.get(password_hash_key)

                if not password_hash:
                    logger.warning(
                        f"No password hash found for user '{username}'. Expected env var: {password_hash_key}"
                    )
                    password_hash = ""

                authelia_users.append(
                    {
                        "username": username,
                        "displayname": user.get("displayname", username.title()),
                        "email": user.get("email", ""),
                        "disabled": user.get("disabled", False),
                        "groups": user.get("groups", ["users"]),
                        "password_hash": password_hash,
                    }
                )

            # Final context combining env_vars, apps list, users, and Argon2 constants
            context = {
                **env_vars,
                "apps": apps,
                "authelia_users": authelia_users,
                "oidc_clients": processed_oidc_clients,  # Add the processed clients list
                "AUTHELIA_OIDC_JWKS_KEY": jwks_key,
                "ARGON2_TIME_COST": AUTHELIA_CONFIG.ARGON2_TIME_COST,
                "ARGON2_MEMORY_COST": AUTHELIA_CONFIG.ARGON2_MEMORY_COST,
                "ARGON2_PARALLELISM": AUTHELIA_CONFIG.ARGON2_PARALLELISM,
                "ARGON2_HASH_LENGTH": AUTHELIA_CONFIG.ARGON2_HASH_LENGTH,
                "ARGON2_SALT_LENGTH": AUTHELIA_CONFIG.ARGON2_SALT_LENGTH,
            }

            renderer = create_renderer(templates_dir)

            generated_files = []

            # Process configuration.yml.j2
            template_name_config = "configuration.yml.j2"
            output_name_config = "configuration.yml"
            output_file_config = output_dir / output_name_config

            if renderer.render_template(
                template_name_config, output_file_config, context
            ):
                generated_files.append(str(output_file_config))
                logger.info(f"Generated {output_name_config}: {output_file_config}")
            else:
                logger.warning(f"Failed to render {template_name_config}")
                return {
                    "success": False,
                    "error": f"Failed to render {template_name_config}",
                }

            # Process users_database.yml.j2 (existing logic)
            template_name_users = "users_database.yml.j2"
            output_name_users = "users_database.yml"
            output_file_users = output_dir / output_name_users

            if renderer.render_template(
                template_name_users, output_file_users, context
            ):
                generated_files.append(str(output_file_users))
                logger.info(f"Generated {output_name_users}: {output_file_users}")
            else:
                logger.warning(f"Failed to render {template_name_users}")
                return {
                    "success": False,
                    "error": f"Failed to render {template_name_users}",
                }

            logger.success(
                f"Generated {len(generated_files)} Authelia configuration files"
            )
            return {"success": True, "files": generated_files}

        except Exception as e:
            logger.error(f"Failed to generate Authelia config: {e}")
            return {"success": False, "error": str(e)}

    def validate(self) -> bool:
        """Validate Authelia configuration and structure.

        Returns:
            True if validation passes, False otherwise
        """
        templates_dir = (
            self.project_root / "infra" / "config" / "authelia" / "templates"
        )

        if not templates_dir.exists():
            logger.error(f"Authelia templates directory not found: {templates_dir}")
            return False

        required_templates = ["configuration.yml.j2", "users_database.yml.j2"]
        missing = [t for t in required_templates if not (templates_dir / t).exists()]

        if missing:
            logger.warning(f"Missing Authelia templates: {', '.join(missing)}")
            return False

        logger.success("Authelia configuration is valid")
        return True
