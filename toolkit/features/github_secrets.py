"""GitHub secrets management utilities."""

import json
import subprocess
from typing import Any

from toolkit.config.constants import MESSAGES
from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager


class GitHubSecretsManager:
    """Manager for GitHub secrets synchronization."""

    def __init__(self) -> None:
        """Initialize the GitHub secrets manager."""
        self.project_root = settings.project_root

        self.repo_info = self.get_repository_info()

        if not self.repo_info:
            raise RuntimeError(
                "Failed to get GitHub repository information. "
                "Check 'gh auth status' and ensure you are in a valid git repo."
            )

        self.repo_slug = f"{self.repo_info['owner']['login']}/{self.repo_info['name']}"
        logger.debug(f"Operating on repository: {self.repo_slug}")

    def check_gh_cli(self) -> bool:
        """Check if GitHub CLI is available and authenticated."""
        try:
            # Check if gh is installed
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug(f"GitHub CLI version: {result.stdout.strip()}")

            # Check if authenticated
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug("GitHub CLI authentication status: OK")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"GitHub CLI authentication failed: {e.stderr.strip()}")
            return False
        except FileNotFoundError:
            logger.error(MESSAGES.ERROR_GITHUB_CLI_NOT_FOUND)
            return False

    def get_repository_info(self) -> dict[str, Any] | None:
        """Get repository information from GitHub CLI."""
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "name,owner"],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_root,
            )
            return dict(json.loads(result.stdout))
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get repository info: {e.stderr.strip()}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse repository info: {e}")
            return None

    def list_secrets(self) -> list[str]:
        """List existing repository secrets."""
        try:
            result = subprocess.run(
                ["gh", "secret", "list", "--repo", self.repo_slug, "--json", "name"],
                capture_output=True,
                text=True,
                check=True,
            )
            secrets_data = json.loads(result.stdout)
            return [secret["name"] for secret in secrets_data]
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to list secrets: {e.stderr.strip()}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse secrets list: {e}")
            return []

    def set_secret(self, name: str, value: str) -> bool:
        """Set a repository secret."""
        try:
            subprocess.run(
                [
                    "gh",
                    "secret",
                    "set",
                    name,
                    "--repo",
                    self.repo_slug,
                    "--body",
                    value,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug(f"Set secret: {name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to set secret {name}: {e.stderr.strip()}")
            return False

    def delete_secret(self, name: str) -> bool:
        """Delete a repository secret."""
        try:
            subprocess.run(
                ["gh", "secret", "delete", name, "--repo", self.repo_slug],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug(f"Deleted secret: {name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to delete secret {name}: {e.stderr.strip()}")
            return False

    def sync_env_to_secrets(self, env: str) -> int:
        """Sync environment configuration to GitHub secrets.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Number of secrets synced
        """
        if not self.check_gh_cli():
            return 0

        logger.info(f"Syncing {env} environment configuration to GitHub secrets")

        # Load environment variables from YAML+SOPS
        config_manager = ConfigurationManager(env, self.project_root)
        env_vars = config_manager.get_env_vars()

        if not env_vars:
            logger.warning(MESSAGES.WARNING_NO_ENV_VARS)
            return 0

        # Filter sensitive variables that should be secrets
        secret_vars = self._filter_secret_variables(env_vars)

        if not secret_vars:
            logger.warning(MESSAGES.WARNING_NO_SENSITIVE_VARS)
            return 0

        # Get existing secrets
        existing_secrets = self.list_secrets()

        synced_count = 0
        errors = 0

        for var_name, var_value in secret_vars.items():
            if not var_value:  # Skip empty values
                continue

            secret_name = var_name.upper()

            try:
                if self.set_secret(secret_name, var_value):
                    if secret_name in existing_secrets:
                        logger.info(f"Updated secret: {secret_name}")
                    else:
                        logger.info(f"Created secret: {secret_name}")
                    synced_count += 1
                else:
                    errors += 1

            except Exception as e:
                error_msg = getattr(e, "stderr", str(e)).strip()
                logger.error(f"Failed to sync {var_name}: {error_msg}")
                errors += 1

        # Summary
        if synced_count > 0:
            logger.success(f"Synced {synced_count} secrets to GitHub")

        if errors > 0:
            logger.warning(f"Failed to sync {errors} variables")

        return synced_count

    def _filter_secret_variables(self, env_vars: dict[str, str]) -> dict[str, str]:
        """Filter variables that should be treated as secrets."""
        secret_patterns = [
            "password",
            "secret",
            "key",
            "token",
            "credential",
            "api_key",
            "private",
            "auth",
            "cert",
            "ssl",
        ]

        public_patterns = [
            "host",
            "port",
            "url",
            "domain",
            "name",
            "user",
            "environment",
            "debug",
            "log",
            "timeout",
            "enable",
            "input",
            "path",
        ]

        secrets = {}

        for var_name, var_value in env_vars.items():
            var_name_lower = var_name.lower()

            # Skip obviously public variables
            if any(pattern in var_name_lower for pattern in public_patterns):
                continue

            # Include variables that match secret patterns
            if any(pattern in var_name_lower for pattern in secret_patterns):
                secrets[var_name] = var_value
                continue

            # Include variables with long, complex values (likely secrets)
            if len(var_value) > 20 and any(c in var_value for c in "!@#$%^&*+="):
                secrets[var_name] = var_value

        return secrets

    def cleanup_unused_secrets(self, env: str, dry_run: bool = True) -> int:
        """Remove secrets that are not in the environment configuration.

        Args:
            env: Environment name (dev, staging, prod)
            dry_run: If True, only show what would be deleted without actually deleting

        Returns:
            Number of secrets cleaned up (or would be cleaned up if dry_run=True)
        """
        if not self.check_gh_cli():
            return 0

        logger.info(f"Cleaning up unused secrets for {env} (dry_run={dry_run})...")

        # Load environment variables from YAML+SOPS
        config_manager = ConfigurationManager(env, self.project_root)
        env_vars = config_manager.get_env_vars()
        expected_secrets = set(self._filter_secret_variables(env_vars).keys())

        # Get existing secrets
        existing_secrets = set(self.list_secrets())

        # Find unused secrets
        unused_secrets = existing_secrets - expected_secrets

        if not unused_secrets:
            logger.info(MESSAGES.INFO_NO_UNUSED_SECRETS)
            return 0

        deleted_count = 0

        for secret_name in unused_secrets:
            if dry_run:
                logger.info(f"Would delete unused secret: {secret_name}")
            else:
                if self.delete_secret(secret_name):
                    logger.success(f"Deleted unused secret: {secret_name}")
                    deleted_count += 1

        if dry_run:
            logger.info(f"Found {len(unused_secrets)} unused secrets (use --no-dry-run to delete)")
        else:
            logger.success(f"Deleted {deleted_count} unused secrets")

        return len(unused_secrets) if dry_run else deleted_count


# Global GitHub secrets manager instance
github_secrets_manager = GitHubSecretsManager()
