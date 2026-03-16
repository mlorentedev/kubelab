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
        Merge order (later overrides earlier):
          common.yaml → {env}.yaml → common.enc.yaml → {env}.enc.yaml

        Returns the merged config WITHOUT flattening (preserves nested structure).
        """
        # 1. Load Common Values
        config = self._load_yaml(self.values_path / "common.yaml")

        # 2. Load Env Values (Deep merge)
        env_values = self._load_yaml(self.values_path / f"{self.env}.yaml")
        self._deep_update(config, env_values)

        # 3. Load Shared Secrets (Decrypt) — infra creds shared across all envs
        common_secrets = self._decrypt_sops(self.secrets_path / "common.enc.yaml")
        self._deep_update(config, common_secrets)

        # 4. Load Env Secrets (Decrypt) — env-specific secrets override common
        env_secrets = self._decrypt_sops(self.secrets_path / f"{self.env}.enc.yaml")
        self._deep_update(config, env_secrets)

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

    def _check_sops(self) -> bool:
        """Check if SOPS is installed."""
        if subprocess.run(["which", "sops"], capture_output=True).returncode != 0:
            self._get_logger().error("SOPS is not installed.")
            return False
        return True

    def _ensure_sops_file(self, file_path: Path) -> bool:
        """Create an empty SOPS-encrypted file if it doesn't exist."""
        if file_path.exists():
            return True

        self._get_logger().info(f"Creating new SOPS file: {file_path}")
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write empty YAML, then encrypt via SOPS (uses .sops.yaml creation_rules)
        file_path.write_text("{}\n")
        try:
            subprocess.run(
                ["sops", "--encrypt", "--in-place", str(file_path)],
                text=True,
                check=True,
                capture_output=True,
                env=os.environ,
            )
            self._get_logger().info(f"Created encrypted file: {file_path}")
            return True
        except subprocess.CalledProcessError as e:
            self._get_logger().error(f"Failed to create SOPS file: {e.stderr}")
            file_path.unlink(missing_ok=True)
            return False

    def _set_nested_key(self, data: Dict[str, Any], key_path: str, value: Any) -> None:
        """Set a value in a nested dict using a dot-separated key path."""
        keys = key_path.split(".")
        current = data
        for i, key in enumerate(keys):
            if i == len(keys) - 1:
                current[key] = value
            else:
                if key not in current or not isinstance(current[key], dict):
                    current[key] = {}
                current = current[key]

    def _encrypt_sops_file(self, file_path: Path, data: Dict[str, Any]) -> bool:
        """Write data to file and encrypt with SOPS. Single encrypt operation."""
        updated_yaml = yaml.dump(data, default_flow_style=False, sort_keys=False)
        file_path.write_text(updated_yaml)
        try:
            subprocess.run(
                ["sops", "--encrypt", "--in-place", str(file_path)],
                text=True,
                check=True,
                capture_output=True,
                env=os.environ,
            )
            return True
        except subprocess.CalledProcessError as e:
            self._get_logger().error(f"Failed to encrypt {file_path}: {e.stderr}")
            return False

    def batch_update_secrets(
        self,
        secrets: Dict[str, Any],
        secret_file_path: Optional[Path] = None,
    ) -> bool:
        """Update multiple keys in a SOPS file with a single decrypt/encrypt cycle.

        Args:
            secrets: Dict of dot-separated key paths → values.
            secret_file_path: Override for the SOPS file path.

        Returns:
            True if all updates succeeded.
        """
        file_to_update = secret_file_path or (self.secrets_path / f"{self.env}.enc.yaml")
        logger = self._get_logger()

        if not self._check_sops():
            return False

        if not self._ensure_sops_file(file_to_update):
            return False

        try:
            # 1. Single decrypt
            result = subprocess.run(
                ["sops", "-d", "--output-type", "yaml", str(file_to_update)],
                capture_output=True,
                text=True,
                check=True,
                env=os.environ,
            )
            decrypted_data = yaml.safe_load(result.stdout) or {}

            # 2. Update all keys in memory
            for key_path, value in secrets.items():
                self._set_nested_key(decrypted_data, key_path, value)
                logger.success(f"  Updated: {key_path}")

            # 3. Single encrypt
            if not self._encrypt_sops_file(file_to_update, decrypted_data):
                return False

            logger.info(f"Wrote {len(secrets)} secrets to {file_to_update}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to decrypt {file_to_update}: {e.stderr}")
            return False

    def update_secret_key(self, key_path: str, value: Any, secret_file_path: Optional[Path] = None) -> bool:
        """Update a single key in a SOPS file. For bulk updates use batch_update_secrets."""
        return self.batch_update_secrets({key_path: value}, secret_file_path)
