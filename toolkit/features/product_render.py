"""Render a product contract into ``apps.platform.<app>`` and detect drift (IDP-042 AC3, Q2).

A contract owns six keys of its app's values block, listed in ``CONTRACT_KEYS``
with the function that derives each from the contract. Every other key
(``version`` above all, which ``promote`` owns) is left alone.

Drift is judged on ``values/<env>.yaml`` merged over ``common.yaml`` at the app
level, because that is what the generators read. ``write`` therefore edits only
keys whose merged value differs, and puts the correction in the env file: a
key that is right in ``common.yaml`` is not copied into every env.

``auth`` maps to the two keys the generators already read: ``public`` is
``enable_auth: false`` / ``auth_level: bypass``; ``forwardauth`` is
``enable_auth: true`` / ``auth_level: one_factor``, the only Authelia policy any
app uses today. ``oidc`` is refused before rendering (``refuse_oidc_at_render``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML

from toolkit.config.settings import PROJECT_ROOT
from toolkit.features.declared_domains import VALUES_DIR
from toolkit.features.product_contract import Contract
from toolkit.features.product_guards import refuse_oidc_at_render

SNAPSHOT_DIR = PROJECT_ROOT / "infra" / "config" / "products" / "contracts"

_AUTH_LEVEL = {"public": "bypass", "forwardauth": "one_factor"}

#: values key -> how the contract derives it for an env.
CONTRACT_KEYS: dict[str, Callable[[Contract, str], Any]] = {
    "default_port": lambda c, env: c.port,
    "health_path": lambda c, env: c.health_path,
    "domain": lambda c, env: getattr(c.hostnames, env),
    "enable_auth": lambda c, env: c.auth != "public",
    "auth_level": lambda c, env: _AUTH_LEVEL[c.auth],
    # The guard has already pinned the repository to <registry>/<image_name>.
    "image_name": lambda c, env: c.image.rsplit("/", 1)[1],
}

__all__ = ["CONTRACT_KEYS", "SNAPSHOT_DIR", "VALUES_DIR", "drift", "rendered", "write"]


def rendered(
    contract: Contract, app: str, env: str, mapping: Mapping[str, Callable[[Contract, str], Any]] = CONTRACT_KEYS
) -> dict[str, Any]:
    """The contract-owned keys of ``apps.platform.<app>`` for ``env``."""
    refuse_oidc_at_render(contract, app)
    return {key: derive(contract, env) for key, derive in mapping.items()}


def _merged_app(app: str, env: str, values_dir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in ("common", env):
        data = yaml.safe_load((values_dir / f"{source}.yaml").read_text()) or {}
        merged.update(((data.get("apps") or {}).get("platform") or {}).get(app) or {})
    return merged


def drift(
    contract: Contract,
    app: str,
    env: str,
    *,
    values_dir: Path = VALUES_DIR,
    mapping: Mapping[str, Callable[[Contract, str], Any]] = CONTRACT_KEYS,
) -> tuple[dict[str, tuple[Any, Any]], int]:
    """Return ``({key: (rendered, in values)}, keys compared)``; refuse to compare nothing."""
    if not mapping:
        raise ValueError("no contract-owned keys to compare: an empty mapping would report every tree clean")
    want = rendered(contract, app, env, mapping)
    have = _merged_app(app, env, values_dir)
    differences = {key: (value, have.get(key)) for key, value in want.items() if have.get(key) != value}
    return differences, len(want)


def write(contract: Contract, app: str, env: str, *, values_dir: Path = VALUES_DIR) -> list[str]:
    """Correct the drifted keys in ``values/<env>.yaml``; return their names. Never touches ``version``."""
    differences, _ = drift(contract, app, env, values_dir=values_dir)
    if not differences:
        return []
    path = values_dir / f"{env}.yaml"
    ruamel = YAML()
    ruamel.preserve_quotes = True
    doc = ruamel.load(path.read_text())
    block = doc["apps"]["platform"][app]
    for key, (value, _) in differences.items():
        if key in block:
            block[key] = value
        else:
            # Appending would land after a trailing section comment (see
            # tests/test_values_version_key_placement.py); insert before version.
            position = list(block).index("version") if "version" in block else len(block)
            block.insert(position, key, value)
    with path.open("w") as handle:
        ruamel.dump(doc, handle)
    return list(differences)
