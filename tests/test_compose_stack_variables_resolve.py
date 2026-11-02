"""Every variable a dev Compose stack reads exists in the dev config (SSOT-032, #2754).

Compose turns an unset `${VAR}` into an empty string and a warning, so a stack whose
variables were renamed fails far from the cause. n8n read `APPS_SERVICES_CORE_N8N_*`
for months after the config moved it under `automation`, and had no image at all.

Key names are plaintext in a SOPS file, so this needs no decryption.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml

from toolkit.features.configuration import ConfigurationManager

REPO = pathlib.Path(__file__).resolve().parent.parent
STACKS = REPO / "infra" / "stacks"
VARIABLE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)([^}]*)\}")
FILES = sorted([*STACKS.rglob("compose.base.yml"), *STACKS.rglob("compose.dev.yml")])

# Set by ConfigurationManager on load, so they are in no file.
DERIVED_BY_THE_LOADER = {
    "ENVIRONMENT",
    "RESTART_POLICY",
    "BASE_DOMAIN",
    "TIMEZONE",
    "APPS_SERVICES_CORE_GITEA_ADMIN_EMAIL",
    "APPS_SERVICES_CORE_GITEA_ADMIN_USER",
    "APPS_SERVICES_OBSERVABILITY_GRAFANA_ADMIN_USER",
    "APPS_SERVICES_OBSERVABILITY_GRAFANA_OAUTH_CLIENT_ID",
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _load(relative: str) -> dict[str, Any]:
    return yaml.safe_load((REPO / "infra" / "config" / relative).read_text(encoding="utf-8")) or {}


def _known() -> set[str]:
    config: dict[str, Any] = {}
    for relative in ("values/common.yaml", "values/dev.yaml", "secrets/common.enc.yaml", "secrets/dev.enc.yaml"):
        _merge(config, _load(relative))
    config.pop("sops", None)
    flatten = ConfigurationManager._flatten_dict
    return set(flatten(ConfigurationManager.__new__(ConfigurationManager), config)) | DERIVED_BY_THE_LOADER


def unresolved(text: str, known: set[str]) -> list[str]:
    """Variables in a Compose file that nothing sets, skipping those with a `:-` or `-` default."""
    return sorted(
        {name for name, rest in VARIABLE.findall(text) if name not in known and not rest.startswith((":-", "-"))}
    )


def test_the_detector_reads_required_and_defaulted_variables() -> None:
    text = "a: ${SET}\nb: ${MISSING}\nc: ${DEFAULTED:-x}\nd: ${ALSO_DEFAULTED-x}\n"
    assert unresolved(text, {"SET"}) == ["MISSING"]


def test_the_compose_files_were_found() -> None:
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(STACKS)))
def test_each_variable_resolves_in_the_dev_config(path: pathlib.Path) -> None:
    assert unresolved(path.read_text(encoding="utf-8"), _known()) == []
