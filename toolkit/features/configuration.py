import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Removed top-level logger import to avoid circular dependency
# from toolkit.core.logging import logger


class ConfigurationManager:
    """Manages application configuration using YAML values and SOPS secrets."""

    def __init__(self, env: str, project_root: Optional[Path] = None):
        if project_root:
            self.project_root = project_root
        else:
            # Calculate project root relative to this file (toolkit/features/configuration.py)
            self.project_root = Path(__file__).resolve().parent.parent.parent

        self.env = env
        self.infra_path = self.project_root / "infra"
        self.config_path = self.infra_path / "config"
        self.secrets_path = self.config_path / "secrets"
        self.values_path = self.config_path / "values"
        self.certs_path = self.config_path / "certs"

    def _get_logger(self) -> Any:
        """Lazy load logger to avoid circular imports."""
        from toolkit.core.logging import logger

        return logger

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load a YAML file silently."""
        if not path.exists():
            # It is okay if specific env override doesn't exist, but warn for debugging
            # self._get_logger().debug(f"Configuration file not found: {path}")
            return {}

        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self._get_logger().error(f"Failed to load {path}: {e}")
            return {}

    def _decrypt_sops(self, path: Path) -> Dict[str, Any]:
        """Decrypt a SOPS file and return its content as dict."""
        if not path.exists():
            return {}

        # Check if sops is installed
        if subprocess.run(["which", "sops"], capture_output=True).returncode != 0:
            self._get_logger().warning("SOPS is not installed. Skipping secret decryption.")
            return {}

        try:
            result = subprocess.run(
                ["sops", "-d", "--output-type", "yaml", str(path)],
                capture_output=True,
                text=True,
                check=True,
                env=os.environ,  # Inherit current environment variables
            )
            return yaml.safe_load(result.stdout) or {}
        except subprocess.CalledProcessError as e:
            self._get_logger().error(f"Failed to decrypt {path}: {e.stderr}")
            return {}

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        """Flatten nested dict keys to UPPERCASE_ENV_VARS."""
        items: List[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                # Keep lists as lists for template iteration
                items.append((new_key.upper(), v))
            else:
                # Convert all other values to string for env vars
                val_str = str(v)
                if isinstance(v, bool):
                    val_str = str(v).lower()  # true/false for yaml standard
                items.append((new_key.upper(), val_str))
        return dict(items)

    def _deep_update(self, source: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Recursive dict update."""
        for key, value in overrides.items():
            if isinstance(value, dict) and value:
                returned = self._deep_update(source.get(key, {}), value)
                source[key] = returned
            else:
                source[key] = overrides[key]
        return source

    def get_merged_config(self) -> Dict[str, Any]:
        """
        Merge: Values(Common) + Values(Env) + Secrets(Env)
        Returns the merged config WITHOUT flattening (preserves nested structure).
        """
        # 1. Load Common Values
        config = self._load_yaml(self.values_path / "common.yaml")

        # 2. Load Env Values (Deep merge)
        env_values = self._load_yaml(self.values_path / f"{self.env}.yaml")
        self._deep_update(config, env_values)

        # 3. Load Secrets (Decrypt)
        secrets = self._decrypt_sops(self.secrets_path / f"{self.env}.enc.yaml")
        self._deep_update(config, secrets)

        return config

    def get_env_vars(self) -> Dict[str, str]:
        """
        Merge: Values(Common) + Values(Env) + Secrets(Env)
        Returns a flattened dict suitable for environment variables.
        """
        config = self.get_merged_config()

        # Flatten to ENV_VARS
        flattened = self._flatten_dict(config)

        # Post-processing
        flattened["ENVIRONMENT"] = self.env

        # Create compatibility aliases for common variables
        # These are used extensively in compose files without GLOBAL_ prefix
        compatibility_aliases = {
            "RESTART_POLICY": flattened.get("GLOBAL_RESTART_POLICY"),
            "BASE_DOMAIN": flattened.get("GLOBAL_BASE_DOMAIN"),
            "TIMEZONE": flattened.get("GLOBAL_TIMEZONE"),
        }

        for alias, value in compatibility_aliases.items():
            if value and alias not in flattened:
                flattened[alias] = value

        return flattened

    def get_compose_files(self, component_path: Path) -> List[str]:
        """
        Return list of compose files with -f flag.
        Looks for compose.base.yml and compose.{env}.yml
        Returns absolute paths.
        """
        files = []

        # Base
        base_file = component_path / "compose.base.yml"
        if base_file.exists():
            files.extend(["-f", str(base_file.resolve())])  # Use resolve() to get absolute path
        else:
            # Fallback to old behavior if not migrated?
            # Or assume if base missing, check for docker-compose.{env}.yml (legacy)
            legacy_file = component_path / f"docker-compose.{self.env}.yml"
            if legacy_file.exists():
                return [
                    "-f",
                    str(legacy_file.resolve()),
                ]  # Use resolve() to get absolute path

        # Env Override
        override = component_path / f"compose.{self.env}.yml"
        if override.exists():
            files.extend(["-f", str(override.resolve())])  # Use resolve() to get absolute path

        return files

    def update_secret_key(self, key_path: str, value: Any, secret_file_path: Optional[Path] = None) -> bool:
        """
        Updates a specific key in a SOPS-encrypted YAML secret file.

        Args:
            key_path: The dot-separated path to the key (e.g., "apps.authelia.users_admin_password_hash").
            value: The new value for the key.
            secret_file_path: The path to the secret file. Defaults to self.secrets_path / f"{self.env}.enc.yaml".

        Returns:
            True if successful, False otherwise.
        """
        file_to_update = secret_file_path if secret_file_path else (self.secrets_path / f"{self.env}.enc.yaml")

        if not file_to_update.exists():
            self._get_logger().error(f"Secret file not found: {file_to_update}")
            return False

        if subprocess.run(["which", "sops"], capture_output=True).returncode != 0:
            self._get_logger().error("SOPS is not installed. Cannot update secret file.")
            return False

        try:
            # Decrypt the file
            result = subprocess.run(
                ["sops", "-d", "--output-type", "yaml", str(file_to_update)],
                capture_output=True,
                text=True,
                check=True,
                env=os.environ,  # Inherit current environment variables
            )
            decrypted_data = yaml.safe_load(result.stdout) or {}

            # Update the specific key
            keys = key_path.split(".")
            current_level = decrypted_data
            for i, key in enumerate(keys):
                if i == len(keys) - 1:
                    current_level[key] = value
                else:
                    if key not in current_level or not isinstance(current_level[key], dict):
                        current_level[key] = {}
                    current_level = current_level[key]

            # Re-encrypt and save the file
            # Write to temp file first, then encrypt in-place
            # SOPS needs a real file path to match creation_rules

            updated_yaml = yaml.dump(decrypted_data, default_flow_style=False, sort_keys=False)

            # Write decrypted content to the target file temporarily
            file_to_update.write_text(updated_yaml)

            # Encrypt in-place using the actual file path (so SOPS can match creation_rules)
            result = subprocess.run(
                ["sops", "--encrypt", "--in-place", str(file_to_update)],
                text=True,
                check=True,
                capture_output=True,
                env=os.environ,
            )
            self._get_logger().info(f"Successfully updated secret key '{key_path}' in {file_to_update}")
            return True

        except subprocess.CalledProcessError as e:
            self._get_logger().error(f"Failed to update secret file {file_to_update}: {e.stderr}")
            return False
        except Exception as e:
            self._get_logger().error(f"An unexpected error occurred while updating secret file: {e}")
            return False
