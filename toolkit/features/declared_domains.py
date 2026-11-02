"""The public domains the values files declare, per environment (OBS-019, IDP-042).

`apps.*.<...>domain` in `infra/config/values/` means "the public name this
service answers on". Two readers need the full set: the OBS-019 test that every
declared prod domain has a DNS record, and the product contract guard that
refuses a hostname another route already owns. One enumeration serves both, so
the two can never disagree about what is declared.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from toolkit.config.constants import PATH_STRUCTURES
from toolkit.config.settings import PROJECT_ROOT

VALUES_DIR = PROJECT_ROOT / PATH_STRUCTURES.CONFIG_VALUES_DIR


def declared_domains(env: str, values_dir: Path = VALUES_DIR) -> dict[str, str]:
    """Every `<key>: <domain>` a service declares under `apps`, merged common -> env."""
    found: dict[str, str] = {}
    for source in ("common", env):
        path = values_dir / f"{source}.yaml"
        if not path.exists():
            continue
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _walk(config.get("apps", {}), found)
    return found


def _walk(node: object, found: dict[str, str], path: str = "apps") -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        here = f"{path}.{key}"
        if key.endswith("domain") and isinstance(value, str) and value:
            found[here] = value
        else:
            _walk(value, found, here)
