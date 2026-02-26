"""Development tools and utilities commands."""

import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES
from toolkit.config.settings import settings
from toolkit.core.logging import logger

app = typer.Typer(
    name="tools",
    help="Development tools and utilities",
    no_args_is_help=True,
)

certs_app = typer.Typer(
    name="certs",
    help="TLS certificate management for local development",
    no_args_is_help=True,
)

app.add_typer(certs_app, name="certs")


# =============================================================================
# CERTIFICATE COMMANDS
# =============================================================================


def _check_mkcert_installed() -> bool:
    """Check if mkcert is installed."""
    return shutil.which("mkcert") is not None


def _get_certs_path(env: str) -> Path:
    """Get the certificates directory path for an environment."""
    from toolkit.features.configuration import ConfigurationManager

    config_manager = ConfigurationManager(env, settings.project_root)
    return config_manager.certs_path / env


def _get_default_domains(env: str) -> list[str]:
    """Get default domains from environment configuration."""
    from toolkit.features.configuration import ConfigurationManager

    config_manager = ConfigurationManager(env, settings.project_root)
    env_vars = config_manager.get_env_vars()

    base_domain = env_vars.get("BASE_DOMAIN", env_vars.get("GLOBAL_BASE_DOMAIN", "kubelab.test"))

    domains = [base_domain, f"*.{base_domain}"]

    # Include web app domain if it differs from the base domain (e.g. mlorente.test)
    web_domain = env_vars.get("APPS_PLATFORM_WEB_DOMAIN", "")
    if web_domain and web_domain != base_domain and not web_domain.endswith(f".{base_domain}"):
        domains.append(web_domain)

    # Include any configured domains that have more than one subdomain level
    # (wildcards like *.kubelab.test only cover one level, not console.minio.kubelab.test)
    for key, value in env_vars.items():
        if not key.endswith("_DOMAIN") or not value:
            continue
        if not value.endswith(f".{base_domain}"):
            continue
        # Check if it has more than one subdomain level relative to base_domain
        prefix = value[: -(len(base_domain) + 1)]  # strip ".base_domain"
        if "." in prefix and value not in domains:
            domains.append(value)

    return domains


@certs_app.command("install-mkcert")
def install_mkcert() -> None:
    """
    Install mkcert tool for generating locally-trusted certificates.

    Supports: Linux (apt/pacman/yay), macOS (brew).
    """
    if _check_mkcert_installed():
        logger.success("mkcert is already installed")
        result = subprocess.run(
            ["mkcert", "-CAROOT"],
            capture_output=True,
            text=True,
        )
        logger.info(f"CA root: {result.stdout.strip()}")
        return

    logger.info(MESSAGES.INFO_STARTING.format("mkcert installation"))

    # Detect package manager and install
    if shutil.which("brew"):
        cmd = ["brew", "install", "mkcert", "nss"]
    elif shutil.which("apt"):
        cmd = ["sudo", "apt", "install", "-y", "mkcert", "libnss3-tools"]
    elif shutil.which("pacman"):
        cmd = ["sudo", "pacman", "-S", "--noconfirm", "mkcert", "nss"]
    elif shutil.which("yay"):
        cmd = ["yay", "-S", "--noconfirm", "mkcert", "nss"]
    else:
        logger.error("No supported package manager found (brew, apt, pacman, yay)")
        logger.info("Install mkcert manually: https://github.com/FiloSottile/mkcert")
        raise typer.Exit(1)

    try:
        subprocess.run(cmd, check=True)
        logger.success(MESSAGES.SUCCESS_COMPLETED.format("mkcert installation"))
    except subprocess.CalledProcessError as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("mkcert installation", e))
        raise typer.Exit(1) from e

    logger.info("Installing local CA (may require sudo)...")
    try:
        subprocess.run(["mkcert", "-install"], check=True)
        logger.success(MESSAGES.SUCCESS_COMPLETED.format("Local CA installation"))
    except subprocess.CalledProcessError as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Local CA installation", e))
        raise typer.Exit(1) from e


@certs_app.command("generate")
def generate_certs(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Target environment"),
    ] = "dev",
    domains: Annotated[
        list[str] | None,
        typer.Option("--domain", "-d", help="Additional domains to include"),
    ] = None,
) -> None:
    """
    Generate TLS certificates for local development using mkcert.

    Creates cert.pem and key.pem in infra/resources/certs/{env}/.
    """
    if not _check_mkcert_installed():
        logger.error("mkcert is not installed. Run: toolkit tools certs install-mkcert")
        raise typer.Exit(1)

    all_domains = _get_default_domains(env)
    if domains:
        all_domains.extend(domains)

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique_domains: list[str] = []
    for d in all_domains:
        if d not in seen:
            seen.add(d)
            unique_domains.append(d)

    certs_path = _get_certs_path(env)
    certs_path.mkdir(parents=True, exist_ok=True)

    cert_file = certs_path / "cert.pem"
    key_file = certs_path / "key.pem"

    logger.info(MESSAGES.INFO_GENERATING.format(f"certificates for: {', '.join(unique_domains)}"))
    logger.info(f"Output directory: {certs_path}")

    try:
        subprocess.run(
            [
                "mkcert",
                "-cert-file",
                str(cert_file),
                "-key-file",
                str(key_file),
                *unique_domains,
            ],
            check=True,
            cwd=settings.project_root,
        )
        logger.success(MESSAGES.SUCCESS_CREATED.format(f"Certificate: {cert_file}"))
        logger.success(MESSAGES.SUCCESS_CREATED.format(f"Key: {key_file}"))

        # Copy local CA root for services that need to trust it (like MinIO)
        ca_root_result = subprocess.run(["mkcert", "-CAROOT"], capture_output=True, text=True, check=True)
        ca_root_path = Path(ca_root_result.stdout.strip())
        root_ca_file = ca_root_path / "rootCA.pem"
        dest_ca_file = certs_path / "rootCA.pem"

        if root_ca_file.exists():
            shutil.copy2(root_ca_file, dest_ca_file)
            logger.success(MESSAGES.SUCCESS_CREATED.format(f"Root CA: {dest_ca_file}"))
        else:
            logger.warning(f"Root CA not found at {root_ca_file}, skipping copy.")

        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Run: toolkit config generate --env dev")
        logger.info("  2. Restart Traefik: toolkit services restart traefik")
    except subprocess.CalledProcessError as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Certificate generation", e))
        raise typer.Exit(1) from e


@certs_app.command("status")
def certs_status(
    env: Annotated[
        str,
        typer.Option("--env", "-e", help="Target environment"),
    ] = "dev",
) -> None:
    """Show certificate status for an environment."""
    certs_path = _get_certs_path(env)
    cert_file = certs_path / "cert.pem"
    key_file = certs_path / "key.pem"

    logger.section(f"Certificate Status - {env.upper()}")

    if not certs_path.exists():
        logger.warning(MESSAGES.WARNING_NOT_FOUND.format(f"Certificates directory: {certs_path}"))
        logger.info("Run: toolkit tools certs generate --env dev")
        return

    if cert_file.exists():
        logger.success(f"Certificate: {cert_file}")
        try:
            result = subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-in",
                    str(cert_file),
                    "-noout",
                    "-subject",
                    "-dates",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    logger.info(f"  {line}")
        except Exception:
            pass
    else:
        logger.warning(MESSAGES.WARNING_NOT_FOUND.format(f"Certificate: {cert_file}"))

    if key_file.exists():
        logger.success(f"Key: {key_file}")
    else:
        logger.warning(MESSAGES.WARNING_NOT_FOUND.format(f"Key: {key_file}"))

    if _check_mkcert_installed():
        result = subprocess.run(
            ["mkcert", "-CAROOT"],
            capture_output=True,
            text=True,
        )
        logger.info(f"mkcert CA root: {result.stdout.strip()}")
    else:
        logger.warning("mkcert not installed")
