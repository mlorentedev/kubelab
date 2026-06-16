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

from ruamel.yaml import YAML

from toolkit.config.constants import COMPONENTS
from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_k8s import K8sGenerator
from toolkit.features.registry import tag_exists


def _resolve_image(env: str, app: str) -> tuple[str, str]:
    """Return ``(registry, image_name)`` for an app from the merged config."""
    env_vars = ConfigurationManager(env, settings.project_root).get_env_vars()
    registry = env_vars.get("REGISTRY", "docker.io/mlorentedev")
    image_name = env_vars.get(f"APPS_PLATFORM_{app.upper()}_IMAGE_NAME")
    if not image_name:
        raise ValueError(f"No image_name configured for platform app '{app}'")
    return registry, image_name


def promote(env: str, app: str, version: str) -> None:
    """Set ``apps.platform.<app>.version`` in ``values/<env>.yaml`` and regenerate the overlay.

    Raises ``ValueError`` for an unknown app, a non-existent registry tag, or a
    ``dev`` target (dev runs on Docker Compose, not the K8s overlays).
    """
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

    values_path = settings.project_root / "infra" / "config" / "values" / f"{env}.yaml"
    if not values_path.exists():
        raise FileNotFoundError(f"Values file not found: {values_path}")

    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(values_path.read_text())

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
