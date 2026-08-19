"""Development tools and utilities commands."""

import json
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


# =============================================================================
# SPEC GATE (CI-GATE-009)
# =============================================================================


@app.command("spec-gate")
def spec_gate(
    body_file: Annotated[
        Path,
        typer.Option(
            "--body-file",
            help="File holding the PR body. A file rather than a string: a body "
            "passed on the command line is re-scanned by the shell, which has "
            "already corrupted one durable artefact in this repo.",
        ),
    ],
    specs_root: Annotated[Path, typer.Option("--specs-root", help="Root of the specs tree")] = Path("specs"),
    repo: Annotated[
        str, typer.Option("--repo", help="owner/name of the repo owning the issues")
    ] = "mlorentedev/kubelab",
) -> None:
    """Refuse a PR that closes a spec's issue without archiving the spec.

    Reads the tree as checked out, so in CI it judges the merge result rather
    than the diff — a rebase or squash cannot route around it.
    """
    from toolkit.features import spec_gate as gate

    pr_body = body_file.read_text(encoding="utf-8")
    violations = gate.check(pr_body, specs_root, repo=repo)
    message, code = gate.report(
        violations,
        gate.declared_exception(pr_body),
        gate.undeclared_specs(specs_root),
    )

    if code == 0:
        logger.success(message) if not violations else logger.warning(message)
    else:
        logger.error(message)
    raise typer.Exit(code)


@app.command("review-attestation")
def review_attestation(
    payload_file: Annotated[
        Path,
        typer.Option(
            "--payload-file",
            help="File holding a `gh pr view --json ...` payload. A file rather "
            "than a string, for the same reason spec-gate takes one: a PR body "
            "re-scanned by the shell has already corrupted a durable artefact here.",
        ),
    ],
    registry: Annotated[Path, typer.Option("--registry", help="Reviewer registry (JSON)")] = Path(
        "harness/review-attestation.json"
    ),
) -> None:
    """Report whether a PR was actually reviewed, and refuse it if not.

    Exits 0 for attested / exempt / disclosed, 1 for declined / pending, and 2
    when the state could not be determined. Two is never collapsed into zero:
    for a gate, "I could not tell" delivered as "fine" is the defect this exists
    to end.
    """
    from toolkit.features import review_attestation as att

    try:
        reg = att.load_registry(registry)
        payload = json.loads(payload_file.read_text(encoding="utf-8"))
        verdict = att.classify(payload, reg)
    except (att.RegistryError, att.PayloadError, OSError, json.JSONDecodeError) as exc:
        logger.error(f"review attestation: {exc}")
        logger.error("Cannot determine whether this PR was reviewed, so it is NOT treated as reviewed.")
        raise typer.Exit(2) from exc

    if verdict.ok:
        logger.success(f"{verdict.state} — {verdict.detail}")
        raise typer.Exit(0)

    escape = reg["escape"]
    logger.error(f"{verdict.state} — {verdict.detail}")
    logger.error(
        "Options: (a) get it reviewed, then re-run — this gate re-runs on new "
        f'reviewer output; (b) declare the unreviewed merge with the "{escape["label"]}" '
        f'label AND a non-empty "{escape["section"]}" section in the PR body. '
        "Proceeding on an unreviewed PR is allowed. Proceeding silently is not."
    )
    raise typer.Exit(1)
