"""CONSOLE-004 AC2 (#2570) -- the gate on forge writes is declared per environment and reaches the API.

ADR-066 W14: `infra.forge.writes_enabled` is false in `common.yaml`, true in prod only, and the API
builds no forge writer while it is not true. The suite checks the EFFECT a reader of the API's
configuration would see: the value in each environment's generated ConfigMaps (the file the API's
pods load), and that the Go reader asks for the very name the generator emits. A key that parses but
that no pod receives would leave every write route answering 503 in prod, and a value that reached
staging would give it a writer the decision says it must not have (W7).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALUES = REPO_ROOT / "infra" / "config" / "values"
GO_CONFIG = REPO_ROOT / "apps" / "api" / "src" / "pkg" / "config" / "env.go"
ENV_VAR = "INFRA_FORGE_WRITES_ENABLED"


def _forge(env: str) -> dict[str, Any]:
    doc = yaml.safe_load((VALUES / f"{env}.yaml").read_text(encoding="utf-8")) or {}
    return (doc.get("infra") or {}).get("forge") or {}


def _configmaps(env: str) -> dict[str, dict[str, str]]:
    path = REPO_ROOT / "infra" / "k8s" / "overlays" / env / "generated" / "configmaps.yaml"
    return {
        doc["metadata"]["name"]: doc.get("data") or {}
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if doc and doc.get("kind") == "ConfigMap"
    }


def _carriers(env: str) -> dict[str, str | None]:
    """Every ConfigMap that carries the other forge variables, with the gate's value in it (None if absent)."""
    return {name: data.get(ENV_VAR) for name, data in _configmaps(env).items() if "INFRA_FORGE_GITEA_URL" in data}


class TestTheDeclaration:
    def test_common_declares_it_off_as_a_real_boolean(self) -> None:
        """A string "false" would be truthy to a careless reader; the declaration is a YAML bool."""
        assert _forge("common").get("writes_enabled") is False

    def test_prod_alone_turns_it_on(self) -> None:
        assert _forge("prod").get("writes_enabled") is True

    def test_staging_does_not_turn_it_on(self) -> None:
        """W7: staging has no forge writer, and a copy of prod's line there would give it one."""
        assert _forge("staging").get("writes_enabled") is not True

    def test_no_other_environment_file_turns_it_on(self) -> None:
        enabled = sorted(p.stem for p in VALUES.glob("*.yaml") if _forge(p.stem).get("writes_enabled") is True)
        assert enabled == ["prod"], f"writes are enabled in {enabled}, the decision is prod only"


class TestTheApiReceivesIt:
    def test_prods_forge_configmaps_say_true(self) -> None:
        carriers = _carriers("prod")
        assert carriers, "no prod ConfigMap carries the forge variables, so this test would prove nothing"
        assert set(carriers.values()) == {"true"}, f"prod ConfigMaps carry {carriers}"

    def test_staging_forge_configmaps_say_false(self) -> None:
        carriers = _carriers("staging")
        assert carriers, "no staging ConfigMap carries the forge variables, so this test would prove nothing"
        assert set(carriers.values()) == {"false"}, f"staging ConfigMaps carry {carriers}"

    def test_the_go_reader_asks_for_the_name_the_generator_emits(self) -> None:
        """The key flattens to INFRA_FORGE_WRITES_ENABLED (ADR-036); env.go must read exactly that."""
        source = GO_CONFIG.read_text(encoding="utf-8")
        assert re.search(rf'getBoolEnv\("{ENV_VAR}",\s*false\)', source), (
            f"env.go does not read {ENV_VAR} with a false default, so the gate would not follow the declaration"
        )
