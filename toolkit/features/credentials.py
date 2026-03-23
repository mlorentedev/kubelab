"""
Credentials management utilities.
"""

import json  # Added for parsing cscli output
import secrets
import string
import subprocess
from pathlib import Path
from typing import Any, TypedDict

import typer
from argon2 import PasswordHasher

from toolkit.config.constants import AUTHELIA_CONFIG, PATH_STRUCTURES
from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.docker_service import DockerService

# Mapping from secret key prefix to service component names that need restarting
CREDENTIAL_SERVICE_MAP: dict[str, list[str]] = {
    "basic_auth": ["traefik"],
    "apps.services.security.authelia": ["authelia"],
    "apps.services.observability.grafana": ["grafana"],
    "apps.services.data.minio": ["minio"],
    "apps.services.security.crowdsec": ["crowdsec"],
}

# RSA key generation requires cryptography library
try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


class AuthConfig(TypedDict):
    """Configuration for authentication updates."""

    base_dir: Path
    vars: dict[str, str]


class CredentialsManager:
    """Manager for generating and updating credentials across the project."""

    def __init__(self) -> None:
        """Initialize the credentials manager."""
        self.project_root = settings.project_root
        # Initialize ConfigurationManager with default environment.
        # It's reassigned in methods if a specific env is passed.
        self.config_manager = ConfigurationManager(settings.environment)

    def generate_password(self, length: int = 16) -> str:
        """Generate a secure random password."""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def generate_argon2_hash(self, password: str) -> str:
        """Generate an Argon2 password hash using shared constants."""
        ph = PasswordHasher(
            time_cost=AUTHELIA_CONFIG.ARGON2_TIME_COST,
            memory_cost=AUTHELIA_CONFIG.ARGON2_MEMORY_COST,
            parallelism=AUTHELIA_CONFIG.ARGON2_PARALLELISM,
            hash_len=AUTHELIA_CONFIG.ARGON2_HASH_LENGTH,
            salt_len=AUTHELIA_CONFIG.ARGON2_SALT_LENGTH,
        )
        return ph.hash(password)

    def _generate_htpasswd_bcrypt_hash(self, username: str, password: str) -> str:
        """
        Generates an htpasswd-compatible bcrypt hash (username:hash) using a Docker image.
        """
        try:
            command = [
                "docker",
                "run",
                "--rm",
                "httpd",
                "htpasswd",
                "-nb",
                username,
                password,
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            # htpasswd -Bn outputs "username:hash", we want "username:{BLOWFISH}hash" for Traefik.
            # The -Bn option outputs the bcrypt hash directly.
            # So, the output will be like "username:$2y$10$.."
            return result.stdout.strip()
        except FileNotFoundError:
            logger.error("Docker command not found. Is Docker installed and running?")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate htpasswd bcrypt hash: {e.stderr}")
            raise

    def generate_jwks_rsa_key(self, key_size: int | None = None) -> str:
        """
        Generate an RSA private key for Authelia OIDC JWKS.

        Args:
            key_size: RSA key size in bits (default from AUTHELIA_CONFIG)

        Returns:
            PEM-encoded RSA private key as string
        """
        if not HAS_CRYPTOGRAPHY:
            logger.error("cryptography library not installed. Run: poetry add cryptography")
            raise RuntimeError("cryptography library required for JWKS generation")

        if key_size is None:
            key_size = AUTHELIA_CONFIG.RSA_KEY_SIZE

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size, backend=default_backend())

        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return pem.decode("utf-8")

    def generate_oidc_client_secret_hash(self, secret: str) -> str:
        """
        Generate Authelia OIDC client secret hash using Docker.
        Authelia 4.38+ requires hashed client secrets.

        Args:
            secret: The plaintext client secret

        Returns:
            Argon2 hash of the secret in Authelia format
        """
        try:
            command = [
                "docker",
                "run",
                "--rm",
                "authelia/authelia:latest",
                "authelia",
                "crypto",
                "hash",
                "generate",
                "argon2",
                "--password",
                secret,
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            # Output format: "Digest: $argon2id$.."
            output = result.stdout.strip()
            if "Digest:" in output:
                return output.split("Digest:")[1].strip()
            return output
        except FileNotFoundError:
            logger.error("Docker command not found. Is Docker installed and running?")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate OIDC client secret hash: {e.stderr}")
            raise

    def update_hashed_secret(self, key_path: str, env: str) -> None:
        """
        Interactively prompts for a password, generates its Argon2 hash,
        and prints it for manual update in the SOPS-encrypted secrets file.

        Args:
            key_path: The dot-separated path to the key in the secrets file
                      (e.g., "apps.authelia.users_admin_password_hash").
            env: The target environment (e.g., "dev").
        """
        logger.section(f"Generate Hashed Secret for '{key_path}' - {env.upper()}")

        # Ensure config_manager is set to the correct environment for this operation
        self.config_manager.env = env

        # 1. Prompt for password securely
        password = typer.prompt("Enter new password", hide_input=True, confirmation_prompt=True)
        if not password:
            logger.error("Password cannot be empty.")
            raise typer.Exit(1)

        # 2. Generate Argon2 hash
        logger.info("Generating Argon2 hash for the new password...")
        try:
            password_hash = self.generate_argon2_hash(password)
            logger.success("Password hash generated successfully.")
        except Exception as e:
            logger.error(f"Failed to generate password hash: {e}")
            raise typer.Exit(1) from e

        # 3. Print for manual update
        logger.info("")
        logger.warning(f"Please manually update the secret '{key_path}' in:")
        logger.warning(f"  {self.config_manager.secrets_path / f'{env}.enc.yaml'}")
        logger.info("")
        print(f"Key:   {key_path}")
        print(f"Value: {password_hash}")
        logger.info("")
        logger.info("Then run 'toolkit config generate' to apply changes to templated files.")

    def _get_crowdsec_bouncer_api_key(self, bouncer_name: str, env: str) -> str:
        """
        Gets or generates the CrowdSec bouncer API key from the CrowdSec agent.
        Ensures the CrowdSec agent is running for this operation.
        """
        logger.info(f"Checking CrowdSec bouncer API key for '{bouncer_name}'...")

        # Determine the CrowdSec agent container name dynamically
        cm = ConfigurationManager(env, self.project_root)
        env_vars = cm.get_env_vars()
        crowdsec_agent_container_name = env_vars.get("APPS_SERVICES_SECURITY_CROWDSEC_NAME", "crowdsec")

        # Ensure CrowdSec agent is running
        docker_service = DockerService(settings)
        # Path to CrowdSec agent's compose files
        crowdsec_agent_dir = Path("infra/stacks/services/security/crowdsec")

        # Temporarily start CrowdSec agent if not running
        try:
            result = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={crowdsec_agent_container_name}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if not result.stdout.strip():
                logger.warning(
                    f"CrowdSec agent '{crowdsec_agent_container_name}' is not running. Starting it temporarily..."
                )
                docker_service.start_service(crowdsec_agent_dir, env)
                import time

                time.sleep(10)  # Give it time to start
        except Exception as e:
            logger.error(f"Failed to check/start CrowdSec agent: {e}")
            raise typer.Exit(1) from e

        try:
            # Check if bouncer already exists
            list_bouncers_cmd = [
                "docker",
                "exec",
                crowdsec_agent_container_name,
                "cscli",
                "bouncers",
                "list",
                "-o",
                "json",
            ]
            result = subprocess.run(list_bouncers_cmd, capture_output=True, text=True, check=True)
            bouncers_list = json.loads(result.stdout)

            for bouncer in bouncers_list:
                if bouncer.get("name") == bouncer_name:
                    logger.info(f"CrowdSec bouncer '{bouncer_name}' exists. Rotating key (delete/re-create)...")
                    delete_cmd = [
                        "docker",
                        "exec",
                        crowdsec_agent_container_name,
                        "cscli",
                        "bouncers",
                        "delete",
                        bouncer_name,
                    ]
                    subprocess.run(delete_cmd, check=True, capture_output=True)
                    break

            # Create bouncer and get new key
            add_bouncer_cmd = [
                "docker",
                "exec",
                crowdsec_agent_container_name,
                "cscli",
                "bouncers",
                "add",
                bouncer_name,
                "-o",
                "raw",
            ]
            result = subprocess.run(add_bouncer_cmd, capture_output=True, text=True, check=True)
            api_key = result.stdout.strip()
            logger.success(f"CrowdSec bouncer API key generated/rotated for '{bouncer_name}'.")
            return api_key

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to manage CrowdSec bouncer '{bouncer_name}': {e.stderr}")
            raise typer.Exit(1) from e
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse CrowdSec bouncer list: {e}")
            raise typer.Exit(1) from e
        finally:
            # If we started agent temporarily, we should stop it.
            # However, for development, it's often kept running.
            pass

    def setup_authelia_secrets(self, env: str, auto_update: bool = False) -> None:
        """
        Generates all Authelia-related secrets, including basic auth secrets.
        Also generates Grafana admin credentials and its OIDC client secret.
        And CrowdSec bouncer API key.

        Args:
            env: Target environment (dev, staging, prod)
            auto_update: If True, automatically update SOPS file. If False, print for manual copy.
        """
        logger.section(f"Setup Authelia Secrets - {env.upper()}")

        # Ensure config_manager is set to the correct environment for this operation
        self.config_manager.env = env

        # 1. Prompt for common username and password
        logger.info("Setting up common username and password for Authelia and Basic Auth...")
        common_username = typer.prompt("Enter common username (default: admin)", default="admin").strip()
        if not common_username:
            logger.error("Username cannot be empty.")
            raise typer.Exit(1)
        if len(common_username) < 4:
            logger.error("Username must be at least 4 characters long.")
            raise typer.Exit(1)

        common_password = typer.prompt("Enter common password", hide_input=True, confirmation_prompt=True)
        if not common_password:
            logger.error("Password cannot be empty.")
            raise typer.Exit(1)
        if len(common_password) < 8:
            logger.error("Password must be at least 8 characters long.")
            raise typer.Exit(1)

        # 2. Generate Authelia admin password hash (Argon2)
        logger.info("Generating Authelia admin password hash (Argon2)...")
        try:
            authelia_admin_password_hash = self.generate_argon2_hash(common_password)
            logger.success("Authelia admin password hash generated.")
        except Exception as e:
            logger.error(f"Failed to generate Authelia admin password hash: {e}")
            raise typer.Exit(1) from e

        # 3. Generate OIDC HMAC secret
        logger.info("Generating Authelia OIDC HMAC secret...")
        oidc_hmac_secret = secrets.token_urlsafe(64)
        logger.success("Authelia OIDC HMAC secret generated.")

        # 4. Generate Session secret
        logger.info("Generating Authelia Session secret...")
        session_secret = secrets.token_urlsafe(64)
        logger.success("Authelia Session secret generated.")

        # 5. Generate Storage Encryption key
        logger.info("Generating Authelia Storage Encryption key...")
        storage_encryption_key = secrets.token_urlsafe(64)
        logger.success("Authelia Storage Encryption key generated.")

        # 6. Generate JWT Secret for password reset
        logger.info("Generating JWT Secret for password reset...")
        jwt_secret_reset_password = secrets.token_urlsafe(64)
        logger.success("JWT Secret for password reset generated.")

        # 7. Generate OIDC Client Secret and its hash (General Authelia client)
        logger.info("Generating OIDC Client Secret (General Authelia client)...")
        oidc_client_secret = secrets.token_urlsafe(64)
        logger.success("OIDC Client Secret generated.")

        logger.info("Generating OIDC Client Secret hash (Authelia 4.38+ requires hashed secrets)...")
        try:
            oidc_client_secret_hash = self.generate_oidc_client_secret_hash(oidc_client_secret)
            logger.success("OIDC Client Secret hash generated.")
        except Exception as e:
            logger.warning(f"Could not generate OIDC client secret hash via Docker: {e}")
            logger.warning("Using Argon2 hash from local library instead...")
            oidc_client_secret_hash = self.generate_argon2_hash(oidc_client_secret)

        # 8. Generate JWKS RSA key for OIDC (saved as file, not in SOPS)
        logger.info(f"Generating JWKS RSA private key ({AUTHELIA_CONFIG.RSA_KEY_SIZE} bits)...")
        jwks_path = (
            self.project_root / PATH_STRUCTURES.CONFIG_SECRETS_DIR / AUTHELIA_CONFIG.JWKS_FILE_TEMPLATE.format(env=env)
        )
        try:
            jwks_private_key = self.generate_jwks_rsa_key()
            jwks_path.parent.mkdir(parents=True, exist_ok=True)
            jwks_path.write_text(jwks_private_key)
            logger.success(f"JWKS RSA private key saved to: {jwks_path}")
        except Exception as e:
            logger.error(f"Failed to generate JWKS RSA key: {e}")
            logger.warning("Install cryptography: poetry add cryptography")

        # 9. Setup Basic Auth Credentials (htpasswd compatible bcrypt)
        logger.info("Generating Basic Auth credentials (htpasswd compatible bcrypt)...")
        try:
            basic_auth_credentials_hash = self._generate_htpasswd_bcrypt_hash(common_username, common_password)
            logger.success("Basic Auth credentials (htpasswd compatible) generated.")
        except Exception as e:
            logger.error(f"Failed to generate Basic Auth credentials: {e}")
            raise typer.Exit(1) from e

        # 10. Generate Grafana OIDC Client Secret and its hash
        logger.info("Generating Grafana OIDC Client Secret...")
        grafana_oidc_client_secret = secrets.token_urlsafe(64)
        logger.success("Grafana OIDC Client Secret generated.")

        logger.info("Generating Grafana OIDC Client Secret hash...")
        try:
            grafana_oidc_client_secret_hash = self.generate_oidc_client_secret_hash(grafana_oidc_client_secret)
            logger.success("Grafana OIDC Client Secret hash generated.")
        except Exception as e:
            logger.warning(f"Could not generate Grafana OIDC client secret hash via Docker: {e}")
            logger.warning("Using Argon2 hash from local library instead...")
            grafana_oidc_client_secret_hash = self.generate_argon2_hash(grafana_oidc_client_secret)

        # 11. Generate MinIO OIDC Client Secret and its hash
        logger.info("Generating MinIO OIDC Client Secret...")
        minio_oidc_client_secret = secrets.token_urlsafe(64)
        logger.success("MinIO OIDC Client Secret generated.")

        logger.info("Generating MinIO OIDC Client Secret hash...")
        try:
            minio_oidc_client_secret_hash = self.generate_oidc_client_secret_hash(minio_oidc_client_secret)
            logger.success("MinIO OIDC Client Secret hash generated.")
        except Exception as e:
            logger.warning(f"Could not generate MinIO OIDC client secret hash via Docker: {e}")
            logger.warning("Using Argon2 hash from local library instead...")
            minio_oidc_client_secret_hash = self.generate_argon2_hash(minio_oidc_client_secret)

        # 11b. Generate Gitea OIDC Client Secret and its hash
        logger.info("Generating Gitea OIDC Client Secret...")
        gitea_oidc_client_secret = secrets.token_urlsafe(64)
        logger.success("Gitea OIDC Client Secret generated.")

        logger.info("Generating Gitea OIDC Client Secret hash...")
        try:
            gitea_oidc_client_secret_hash = self.generate_oidc_client_secret_hash(gitea_oidc_client_secret)
            logger.success("Gitea OIDC Client Secret hash generated.")
        except Exception as e:
            logger.warning(f"Could not generate Gitea OIDC client secret hash via Docker: {e}")
            logger.warning("Using Argon2 hash from local library instead...")
            gitea_oidc_client_secret_hash = self.generate_argon2_hash(gitea_oidc_client_secret)

        # 12. Generate CrowdSec Bouncer API Key
        # Determine bouncer name from config (e.g., crowdsec-bouncer-traefik)
        cm = ConfigurationManager(env, self.project_root)
        env_vars = cm.get_env_vars()
        bouncer_name = env_vars.get("APPS_SERVICES_SECURITY_CROWDSEC_BOUNCER_NAME", "crowdsec-bouncer-traefik")

        try:
            crowdsec_bouncer_api_key = self._get_crowdsec_bouncer_api_key(bouncer_name, env)
        except Exception as e:
            logger.error(f"Failed to get CrowdSec bouncer API key: {e}")
            raise typer.Exit(1) from e

        # Build secrets dictionary
        # Key paths MUST match the structure in common.yaml (apps.services.security.authelia.*)
        _auth = "apps.services.security.authelia"
        generated_secrets = {
            "basic_auth.user": common_username,
            "basic_auth.password": common_password,
            "basic_auth.credentials": basic_auth_credentials_hash,
            # Authelia secrets
            f"{_auth}.users_admin_password_hash": authelia_admin_password_hash,
            f"{_auth}.oidc_hmac_secret": oidc_hmac_secret,
            f"{_auth}.session_secret": session_secret,
            f"{_auth}.storage_encryption_key": storage_encryption_key,
            f"{_auth}.jwt_secret_reset_password": jwt_secret_reset_password,
            f"{_auth}.oidc_client_secret": oidc_client_secret,
            f"{_auth}.oidc_client_secret_hash": oidc_client_secret_hash,
            f"{_auth}.oidc_client_secret_grafana": grafana_oidc_client_secret,
            f"{_auth}.oidc_client_secret_grafana_hash": grafana_oidc_client_secret_hash,
            f"{_auth}.oidc_client_secret_minio_hash": minio_oidc_client_secret_hash,
            f"{_auth}.oidc_client_secret_gitea_hash": gitea_oidc_client_secret_hash,
            # Grafana secrets
            "apps.services.observability.grafana.admin_user": common_username,
            "apps.services.observability.grafana.admin_password": common_password,
            # MinIO secrets
            "apps.services.data.minio.root_user": common_username,
            "apps.services.data.minio.root_password": common_password,
            "apps.services.data.minio.oidc_client_secret": minio_oidc_client_secret,
            # Gitea secrets
            "apps.services.core.gitea.oidc_client_secret": gitea_oidc_client_secret,
            # CrowdSec secrets
            "apps.services.security.crowdsec.bouncer_api_key": crowdsec_bouncer_api_key,
        }

        if auto_update:
            # Batch update: single decrypt/encrypt cycle
            logger.section("Auto-updating SOPS secrets file...")

            if self.config_manager.batch_update_secrets(generated_secrets):
                logger.success(f"All {len(generated_secrets)} secrets updated in SOPS successfully!")
                # Only reconcile Docker services for dev (staging/prod use K8s)
                if env == "dev":
                    self._reconcile_services(list(generated_secrets.keys()), env)
                else:
                    logger.info(f"Skipping Docker reconciliation for {env} (use K8s deploy instead)")
                    logger.info("Next: toolkit infra k8s apply-secrets --env " + env)
            else:
                logger.warning("Batch update failed. Falling back to manual output...")
                self._print_secrets_for_manual_copy(env, generated_secrets)
        else:
            # Print for manual copy (original behavior)
            self._print_secrets_for_manual_copy(env, generated_secrets)

    def _reconcile_services(self, updated_keys: list[str], env: str) -> None:
        """Restart services affected by credential changes.

        Matches updated secret keys against CREDENTIAL_SERVICE_MAP to determine
        which services need restarting. If traefik is affected (e.g. basic_auth
        changed), regenerates Traefik config first since bcrypt hashes live in
        the dynamic config.

        Args:
            updated_keys: List of dot-separated secret key paths that were updated.
            env: Target environment.
        """
        affected_services: set[str] = set()

        for key in updated_keys:
            for prefix, services in CREDENTIAL_SERVICE_MAP.items():
                if key.startswith(prefix):
                    affected_services.update(services)

        if not affected_services:
            logger.info("No services affected by credential changes.")
            return

        logger.section("Reconciling affected services")
        logger.info(f"Services to restart: {', '.join(sorted(affected_services))}")

        # If traefik is affected, regenerate config first (bcrypt hash in dynamic config)
        if "traefik" in affected_services:
            logger.info("Regenerating Traefik config (basic_auth hash updated)...")
            try:
                from toolkit.features.generator_traefik import TraefikGenerator

                generator = TraefikGenerator()
                generator.generate(env)
                logger.success("Traefik config regenerated.")
            except Exception as e:
                logger.error(f"Failed to regenerate Traefik config: {e}")
                logger.warning("Traefik may use stale credentials until config is regenerated.")

        # Restart each affected service via docker compose up -d
        from toolkit.config.settings import get_settings

        docker_service = DockerService(get_settings(env))

        for service_name in sorted(affected_services):
            try:
                logger.info(f"Restarting {service_name}...")
                docker_service.start_component(service_name, env)
            except Exception as e:
                logger.error(f"Failed to restart {service_name}: {e}")

        logger.success(f"Reconciliation complete. Restarted {len(affected_services)} service(s).")

    def _print_secrets_for_manual_copy(self, env: str, secrets_dict: dict[str, str]) -> None:
        """Print generated secrets in YAML format for manual copy to SOPS."""
        logger.section(f"Generated Secrets for {env.upper()}")
        logger.warning("Copy these values to your SOPS file:")
        logger.warning(f"  sops infra/config/secrets/{env}.enc.yaml\n")

        print("basic_auth:")
        print(f"    user: {secrets_dict['basic_auth.user']}")
        print(f'    password: "{secrets_dict["basic_auth.password"]}"')
        print(f'    credentials: "{secrets_dict["basic_auth.credentials"]}"')
        print("apps:")
        print("    services:")
        print("        data:")
        print("            minio:")
        print(f'                root_user: "{secrets_dict["apps.services.data.minio.root_user"]}"')
        print(f'                root_password: "{secrets_dict["apps.services.data.minio.root_password"]}"')
        print(f'                oidc_client_secret: "{secrets_dict["apps.services.data.minio.oidc_client_secret"]}"')
        print("        observability:")
        print("            grafana:")
        admin_user = secrets_dict["apps.services.observability.grafana.admin_user"]
        admin_password = secrets_dict["apps.services.observability.grafana.admin_password"]
        print(f'                admin_user: "{admin_user}"')
        print(f'                admin_password: "{admin_password}"')
        print("        security:")
        print("            crowdsec:")
        bouncer_key = secrets_dict["apps.services.security.crowdsec.bouncer_api_key"]
        print(f'                bouncer_api_key: "{bouncer_key}"')
        print("            authelia:")
        _a = "apps.services.security.authelia"
        users_hash = secrets_dict[f"{_a}.users_admin_password_hash"]
        print(f'                users_admin_password_hash: "{users_hash}"')
        oidc_hmac = secrets_dict[f"{_a}.oidc_hmac_secret"]
        print(f'                oidc_hmac_secret: "{oidc_hmac}"')
        session = secrets_dict[f"{_a}.session_secret"]
        print(f'                session_secret: "{session}"')
        storage_key = secrets_dict[f"{_a}.storage_encryption_key"]
        print(f'                storage_encryption_key: "{storage_key}"')
        jwt_secret = secrets_dict[f"{_a}.jwt_secret_reset_password"]
        print(f'                jwt_secret_reset_password: "{jwt_secret}"')
        oidc_secret = secrets_dict[f"{_a}.oidc_client_secret"]
        print(f'                oidc_client_secret: "{oidc_secret}"')
        oidc_hash = secrets_dict[f"{_a}.oidc_client_secret_hash"]
        print(f'                oidc_client_secret_hash: "{oidc_hash}"')
        grafana_secret = secrets_dict[f"{_a}.oidc_client_secret_grafana"]
        print(f'                oidc_client_secret_grafana: "{grafana_secret}"')
        grafana_hash = secrets_dict[f"{_a}.oidc_client_secret_grafana_hash"]
        print(f'                oidc_client_secret_grafana_hash: "{grafana_hash}"')
        minio_hash = secrets_dict[f"{_a}.oidc_client_secret_minio_hash"]
        print(f'                oidc_client_secret_minio_hash: "{minio_hash}"')
        gitea_hash = secrets_dict[f"{_a}.oidc_client_secret_gitea_hash"]
        print(f'                oidc_client_secret_gitea_hash: "{gitea_hash}"')
        print("        core:")
        print("            gitea:")
        gitea_oidc = secrets_dict["apps.services.core.gitea.oidc_client_secret"]
        print(f'                oidc_client_secret: "{gitea_oidc}"')
        print("")

        logger.success("Secrets generated. Copy above to SOPS, then run 'toolkit config generate'.")

    def extract_common_secrets(self, source_env: str, clean_source: bool = False) -> bool:
        """Extract shared secrets from a per-env SOPS file into common.enc.yaml.

        Shared secrets = external infrastructure credentials that are the same
        across all environments (Cloudflare, DockerHub, Gmail, Hetzner, etc.).

        Args:
            source_env: Environment to extract from (typically "dev").
            clean_source: If True, remove extracted keys from source file.

        Returns:
            True if successful.
        """
        logger.section(f"Extract Shared Secrets → common.enc.yaml (from {source_env})")

        cm = ConfigurationManager(source_env, self.project_root)

        # 1. Decrypt source
        source_file = cm.secrets_path / f"{source_env}.enc.yaml"
        source_data = cm._decrypt_sops(source_file)
        if not source_data:
            logger.error(f"Failed to decrypt {source_file}")
            return False

        # 2. Partition into shared vs env-specific
        shared, env_only = self._partition_secrets(source_data)
        if not shared:
            logger.warning("No shared secrets found")
            return False

        # 3. Write common.enc.yaml
        common_file = cm.secrets_path / "common.enc.yaml"
        if not cm._check_sops():
            return False
        if not cm._ensure_sops_file(common_file):
            return False

        existing_common = cm._decrypt_sops(common_file) or {}
        cm._deep_update(existing_common, shared)

        if not cm._encrypt_sops_file(common_file, existing_common):
            return False

        flat_shared = cm._flatten_dict(shared)
        logger.success(f"Wrote {len(flat_shared)} values to common.enc.yaml:")
        for key in shared:
            logger.info(f"  ✓ {key}")

        # 4. Optionally clean source
        if clean_source and env_only:
            if not cm._encrypt_sops_file(source_file, env_only):
                logger.error(f"Failed to clean {source_file}")
                return False
            flat_remaining = cm._flatten_dict(env_only)
            logger.success(f"Cleaned {source_env}.enc.yaml — {len(flat_remaining)} env-specific values remain")

        return True

    @staticmethod
    def _partition_secrets(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split a secrets dict into shared (cross-env) and env-specific parts.

        Returns:
            (shared, env_specific) — two dicts with no overlap.
        """
        import copy

        # Top-level keys that are shared across all environments
        SHARED_TOP_KEYS = {"dockerhub", "hetzner", "cloudflare", "webhooks"}

        # Nested subtrees that are shared (external service credentials)
        # Format: tuple of keys to traverse
        SHARED_NESTED = [
            ("apps", "platform", "api", "email"),
            ("apps", "platform", "api", "zoho"),
            ("apps", "platform", "api", "beehiiv"),
            ("apps", "services", "automation"),
        ]

        shared: dict[str, Any] = {}
        env_only = copy.deepcopy(data)

        # Extract top-level shared keys
        for key in SHARED_TOP_KEYS:
            if key in data:
                shared[key] = data[key]
                env_only.pop(key, None)

        # Extract nested shared keys
        for path_parts in SHARED_NESTED:
            # Read from source
            current_src: Any = data
            found = True
            for part in path_parts:
                if isinstance(current_src, dict) and part in current_src:
                    current_src = current_src[part]
                else:
                    found = False
                    break

            if not found:
                continue

            # Write to shared (rebuild nested path)
            current_dst: dict[str, Any] = shared
            for part in path_parts[:-1]:
                current_dst = current_dst.setdefault(part, {})
            current_dst[path_parts[-1]] = current_src

            # Remove from env_only
            current_rm: Any = env_only
            for part in path_parts[:-1]:
                if isinstance(current_rm, dict) and part in current_rm:
                    current_rm = current_rm[part]
                else:
                    current_rm = None
                    break
            if isinstance(current_rm, dict):
                current_rm.pop(path_parts[-1], None)

        # Prune empty dicts left behind (e.g. apps.platform.api: {})
        # so they don't overwrite common.enc.yaml data during merge
        _prune_empty_dicts(env_only)

        return shared, env_only


def _prune_empty_dicts(d: dict[str, Any]) -> None:
    """Recursively remove keys whose value is an empty dict."""
    keys_to_delete = []
    for k, v in d.items():
        if isinstance(v, dict):
            _prune_empty_dicts(v)
            if not v:
                keys_to_delete.append(k)
    for k in keys_to_delete:
        del d[k]


# Global credentials manager instance
credentials_manager = CredentialsManager()
