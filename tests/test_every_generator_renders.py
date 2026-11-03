"""Every generator `config generate` runs renders, for every env, in CI (#3045).

#2926 moved the ACME resolvers to `networking.public_resolvers` and left
`traefik.yml.j2` reading the removed `DNS_RESOLVER_1`. `config generate` then failed
for staging and prod, and CI said nothing: its drift gate runs only the generators
whose output it diffs, because CI has no SOPS key. The class is a key removed from
the values while a template still reads it, and it can recur in any generator.

So this runs the same list the command runs (`services_for`, `generator_for`), in
a copy of the repo, with every catalogued secret replaced by a placeholder. The
renderer is strict, so a template that reads an undeclared name fails here.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from toolkit.cli.config import generator_for, services_for
from toolkit.features import configuration
from toolkit.features.secrets_manager import SECRET_CATALOG

REPO = Path(__file__).resolve().parents[1]
ENVS = ("dev", "staging", "prod")


def _placeholder_secrets(_manager: object, _path: Path) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for spec in SECRET_CATALOG:
        *parents, leaf = spec.key_path.split(".")
        node = tree
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = "placeholder"
    return tree


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generators write into their project root, so they run against a copy."""
    root = tmp_path_factory.mktemp("generate") / "repo"
    shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "htmlcov"))
    return root


@pytest.mark.parametrize(("env", "service"), [(env, svc) for env in ENVS for svc in services_for(env)])
def test_the_generator_renders(env: str, service: str, repo_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(configuration.ConfigurationManager, "_decrypt_sops", _placeholder_secrets)
    generator = generator_for(service)
    assert generator is not None, service
    generator.project_root = repo_copy
    result = generator.generate(env)
    assert result.get("success"), f"{service} for {env}: {result.get('error')}"
