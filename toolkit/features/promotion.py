"""Image-version promotion (ADR-046 D6).

Set an app's image tag in an environment's values and regenerate its overlay,
atomically. This is the single primitive behind both the staging auto-bump
(SHA tags, continuous deployment) and the prod promotion (semver tags, gated by
PR). Going through one command keeps the schema path (``apps.platform.<app>.version``)
in one place, validates the tag exists before bumping, and guarantees the bump is
never committed without its regeneration so the config-drift gate (ADR-027) can
not be tripped.

The values files are human-authored and comment-rich, so edits go through a
ruamel round-trip (comment- and order-preserving) rather than a PyYAML rewrite.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from toolkit.config.constants import COMPONENTS
from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.registry import tag_exists
from toolkit.scripts import sync_k8s_images

# Immutable CI build tag: ``sha-${GITHUB_SHA::7}`` (see staging-deploy.yml). The
# web-image-receiver rejects anything else, so staging only ever pins this shape.
_SHA_TAG = re.compile(r"^sha-[0-9a-f]{7,}$")


def _load_values_doc(env: str) -> tuple[YAML, Path, Any]:
    """Load ``values/<env>.yaml`` comment-preservingly. Returns ``(yaml, path, data)``.

    Shared by ``promote`` (round-trip write) and ``resolve_image_sha`` (read-only)
    so the values path and ruamel round-trip config live in one place.
    """
    path = settings.project_root / "infra" / "config" / "values" / f"{env}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Values file not found: {path}")
    yaml = YAML()
    yaml.preserve_quotes = True
    return yaml, path, yaml.load(path.read_text())


def resolve_image_sha(env: str, app: str) -> str:
    """Return the immutable ``sha-<short>`` pinned for a platform app in ``values/<env>.yaml``.

    Reads ``apps.platform.<app>.version`` straight from the env SSOT — the exact
    artifact a human last validated on that environment (ADR-056 B1). release.yml
    re-tags this digest as the prod semver (build-once); it is never rebuilt.

    Raises ``ValueError`` if the app is not a platform app, or its pin is absent /
    not an immutable ``sha-<short>`` tag (still ``dev``, a semver, etc.) — refusing
    to promote bytes the environment never ran (incident #666 / kubelab#679).
    """
    if app not in COMPONENTS.PLATFORM_APPS:
        raise ValueError(
            f"App '{app}' is not a platform app {COMPONENTS.PLATFORM_APPS}; "
            "edge services (e.g. errors) are not on the build-once sha lane"
        )
    _, path, data = _load_values_doc(env)
    version = (data.get("apps") or {}).get("platform", {}).get(app, {}).get("version")
    if not version:
        raise ValueError(
            f"No staging-pinned version for platform app '{app}' in {path.name}; "
            "staging must deploy an immutable sha-<short> build before a prod re-tag"
        )
    if not _SHA_TAG.match(str(version)):
        raise ValueError(
            f"Staging pin for '{app}' is '{version}', not an immutable sha-<short> tag; "
            "refusing to re-tag bytes staging never validated (ADR-056 build-once)"
        )
    return str(version)


def read_pinned_version(env: str, app: str) -> str | None:
    """Return the raw ``apps.platform.<app>.version`` pin in ``values/<env>.yaml``, or ``None``.

    Tolerant sibling of ``resolve_image_sha``: no validation, never raises on a
    non-sha (prod pins a semver). Used by the prune janitor to learn which tags a
    committed overlay references so it never deletes one (ADR-056 prune guard).
    """
    try:
        _, _, data = _load_values_doc(env)
    except FileNotFoundError:
        return None
    version = (data.get("apps") or {}).get("platform", {}).get(app, {}).get("version")
    return str(version) if version else None


def _resolve_image(env: str, app: str) -> tuple[str, str]:
    """Return ``(registry, image_name)`` for an app from the merged config."""
    env_vars = ConfigurationManager(env, settings.project_root).get_env_vars()
    registry = env_vars.get("REGISTRY", "docker.io/mlorentedev")
    image_name = env_vars.get(f"APPS_PLATFORM_{app.upper()}_IMAGE_NAME")
    if not image_name:
        raise ValueError(f"No image_name configured for platform app '{app}'")
    return registry, image_name


def _promote_errors(version: str) -> None:
    """Set ``edge.errors.version`` in ``common.yaml`` and re-sync the kustomization.

    The errors image is a single semver shared across envs (DELIVERY-003), so its
    promotion is env-agnostic: it writes the one SSOT and derives the K3s tag via
    the image sync — no per-env overlay regeneration. Refuses a tag that does not
    exist in the registry, same safety as platform apps.
    """
    yaml, common_path, data = _load_values_doc("common")
    registry = data.get("registry", "docker.io/mlorentedev")
    errors_cfg = (data.get("edge") or {}).get("errors")
    if not errors_cfg or "image_name" not in errors_cfg:
        raise ValueError("edge.errors.image_name missing from common.yaml")
    image_name = errors_cfg["image_name"]

    exists = tag_exists(registry, image_name, version)
    if exists is False:
        raise ValueError(
            f"Tag '{version}' not found for {registry}/{image_name} — refusing to promote a "
            "non-existent image (it would ImagePullBackOff)"
        )
    if exists is None:
        logger.warning(f"Could not verify {registry}/{image_name}:{version} exists; proceeding")

    previous = errors_cfg.get("version", "(unset)")
    if previous == version:
        logger.info(f"errors already at {version}; nothing to do")
        return
    errors_cfg["version"] = version
    with common_path.open("w") as fh:
        yaml.dump(data, fh)
    logger.info(f"errors version {previous} -> {version} (edge.errors.version)")

    # Derive the K3s tag from the SSOT so the drift gate stays authoritative.
    sync_k8s_images.sync(common_path, settings.project_root / "infra" / "k8s" / "base" / "kustomization.yaml")
    logger.success(f"Promoted errors to {version}; kustomization re-synced")


def promote(env: str, app: str, version: str) -> None:
    """Set an app's deployed image tag in its SSOT and regenerate derived artifacts.

    Platform apps (api/web) write ``apps.platform.<app>.version`` in
    ``values/<env>.yaml`` and regenerate the overlay. The ``errors`` edge service
    writes the single ``edge.errors.version`` in ``common.yaml`` and re-syncs the
    kustomization (env-agnostic — see ``_promote_errors``).

    Raises ``ValueError`` for an unknown app, a non-existent registry tag, or a
    ``dev`` target for a platform app (dev runs on Docker Compose, not the overlays).
    """
    if app == "errors":
        _promote_errors(version)
        return
    if env == "dev":
        raise ValueError("Promotion targets K8s environments (staging|prod), not dev")
    if app not in COMPONENTS.PLATFORM_APPS:
        raise ValueError(
            f"App '{app}' is not a platform app {COMPONENTS.PLATFORM_APPS}; "
            "edge services (e.g. errors) are not promoted via this command"
        )

    registry, image_name = _resolve_image(env, app)

    exists = tag_exists(registry, image_name, version)
    if exists is False:
        raise ValueError(
            f"Tag '{version}' not found for {registry}/{image_name} — refusing to promote a "
            "non-existent image (it would ImagePullBackOff)"
        )
    if exists is None:
        logger.warning(f"Could not verify {registry}/{image_name}:{version} exists; proceeding")

    yaml, values_path, data = _load_values_doc(env)

    platform = data.setdefault("apps", {}).setdefault("platform", {})
    app_cfg = platform.setdefault(app, {})
    previous = app_cfg.get("version", "(inherited)")
    if previous == version:
        logger.info(f"{env}: {app} already at {version}; nothing to do")
        return
    app_cfg["version"] = version

    with values_path.open("w") as fh:
        yaml.dump(data, fh)
    logger.info(f"{env}: {app} version {previous} -> {version}")

    # Regenerate so generated/ always equals the values output (ADR-027 drift gate).
    K8sGenerator().generate(env)
    logger.success(f"Promoted {app} to {version} in {env}; overlay regenerated")
