"""Filesystem utilities."""

import shutil
from collections.abc import Sequence
from pathlib import Path

import yaml

from toolkit.config.constants import (
    DEFAULT_CONFIG,
    FILE_PATTERNS,
    MESSAGES,
    PATH_STRUCTURES,
)
from toolkit.config.settings import settings
from toolkit.core.logging import FileNotFoundError, logger


def ensure_directory(path: Path) -> Path:
    """Ensure directory exists, create if not."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_file(source: Path, destination: Path) -> bool:
    """Copy file with error handling."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        logger.debug(MESSAGES.INFO_FILE_COPIED.format(f"{source} → {destination}"))
        return True
    except Exception as e:
        logger.error(MESSAGES.ERROR_FILE_COPY_FAILED.format(source, destination, e))
        return False


def backup_file(file_path: Path) -> Path | None:
    """Create a backup of a file."""
    if not file_path.exists():
        logger.warning(MESSAGES.WARNING_FILE_NOT_FOUND.format(file_path))
        return None

    from datetime import datetime

    timestamp = datetime.now().strftime(DEFAULT_CONFIG.BACKUP_TIMESTAMP_FORMAT)
    backup_path = file_path.parent / f"{file_path.name}.{timestamp}{FILE_PATTERNS.BACKUP_SUFFIX}"

    try:
        shutil.copy2(file_path, backup_path)
        logger.success(MESSAGES.SUCCESS_BACKUP_CREATED.format(backup_path))
        return backup_path
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_BACKUP.format(file_path, e))
        return None


def find_files(
    directory: Path,
    pattern: str = "*",
    recursive: bool = True,
) -> list[Path]:
    """Find files matching pattern in directory.

    Utility function for finding files by glob pattern. For more complex
    file discovery with exclusions, use get_project_files() instead.

    Args:
        directory: Directory to search in
        pattern: Glob pattern to match (default: "*" matches all files)
        recursive: If True, search recursively with rglob; if False, use glob

    Returns:
        List of Path objects matching the pattern

    Example:
        >>> find_files(Path("/project"), "*.py", recursive=True)
        [Path("/project/main.py"), Path("/project/utils/helpers.py")]

    Note:
        - Use get_project_files() for searching with exclusions
        - Use Path.glob() or Path.rglob() directly for simple cases
    """
    if recursive:
        return list(directory.rglob(pattern))
    else:
        return list(directory.glob(pattern))


def check_file_exists(file_path: Path, required: bool = False) -> bool:
    """Check if file exists, optionally raise error if required."""
    exists = file_path.exists() and file_path.is_file()

    if required and not exists:
        raise FileNotFoundError(str(file_path))

    return exists


def _is_excluded(file_path: Path, exclude_patterns: list[str]) -> bool:
    """Check if a file path matches any exclusion pattern.

    Args:
        file_path: Path to check
        exclude_patterns: List of exclusion patterns

    Returns:
        True if file should be excluded, False otherwise
    """
    path_str = str(file_path)

    for exclude in exclude_patterns:
        # File extension/suffix exclusions (e.g., ".example", ".py")
        if exclude.startswith(".") and not exclude.startswith("./"):
            if file_path.name.endswith(exclude):
                return True

        # Directory-based exclusions (e.g., "**/.bckp/**")
        elif "/" in exclude:
            # Extract directory name from pattern (e.g., ".bckp" from "**/.bckp/**")
            dir_name = exclude.strip("*/").strip("/")
            if f"/{dir_name}/" in path_str or path_str.endswith(f"/{dir_name}"):
                return True

        # Fallback to glob matching
        elif file_path.match(exclude):
            return True

    return False


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Remove duplicate paths while preserving order.

    Args:
        paths: List of paths that may contain duplicates

    Returns:
        Deduplicated list of paths
    """
    seen: set[Path] = set()
    unique_paths = []

    for path in paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)

    return unique_paths


def get_project_files(
    pattern: str | Sequence[str] = "*.yml",
    exclude_patterns: list[str] | None = None,
    root: Path | None = None,
) -> list[Path]:
    """Get project files matching pattern, excluding specified patterns.

    Args:
        pattern: Glob pattern(s) to match files
        exclude_patterns: List of exclusion patterns
        root: Root directory to search (defaults to project root)

    Returns:
        Sorted list of matching file paths
    """
    if exclude_patterns is None:
        exclude_patterns = [
            "*.example",
            "*/tmp/*",
            "*/.git/*",
            "*/.*",
            ".*/*",
            "*.bak",
            "*.bckp/*",
        ]

    patterns = [pattern] if isinstance(pattern, str) else list(pattern)
    base = root or settings.project_root

    files = []
    for current_pattern in patterns:
        for file_path in base.rglob(current_pattern):
            # Skip non-files and excluded paths
            if not file_path.is_file():
                continue

            if _is_excluded(file_path, exclude_patterns):
                continue

            files.append(file_path)

    # Deduplicate and sort
    return sorted(_deduplicate_paths(files))


def validate_yaml_syntax(file_path: Path) -> bool:
    """Validate YAML file syntax."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        logger.success(MESSAGES.VALIDATION_YAML_VALID.format(file_path.name))
        return True
    except yaml.YAMLError as e:
        logger.error(MESSAGES.ERROR_YAML_INVALID.format(file_path.name, e))
        return False
    except Exception as e:
        logger.warning(MESSAGES.ERROR_YAML_VALIDATION_FAILED.format(file_path.name, e))
        return False


def validate_yaml_files(file_paths: list[Path]) -> int:
    """Validate multiple YAML files and return error count."""
    error_count = 0
    for file_path in file_paths:
        if file_path.suffix in FILE_PATTERNS.CONFIG_EXTENSIONS and file_path.exists():
            if not validate_yaml_syntax(file_path):
                error_count += 1
    return error_count


def get_app_directory(app_name: str) -> Path:
    """Get application directory path."""
    return settings.project_root / PATH_STRUCTURES.APPS_DIR / app_name


def get_service_directory(service_name: str) -> Path:
    """Get service directory path."""
    return settings.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES / service_name


def get_infra_directory(component: str) -> Path:
    """Get infrastructure directory path."""
    return settings.project_root / PATH_STRUCTURES.INFRA_DIR / component


def validate_required_files(base_dir: Path, required_files: list[str]) -> list[str]:
    """Check multiple required files and return list of missing files."""
    missing_files = []
    for file_name in required_files:
        file_path = base_dir / file_name
        if not file_path.exists():
            missing_files.append(file_name)
        else:
            logger.success(MESSAGES.VALIDATION_FILE_EXISTS.format(file_name))

    if missing_files:
        logger.warning(MESSAGES.WARNING_MISSING_FILES.format(", ".join(missing_files)))

    return missing_files
