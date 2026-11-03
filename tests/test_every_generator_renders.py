"""Every generator `config generate` runs renders, for every env, in CI (#3045).

#2926 moved the ACME resolvers to `networking.public_resolvers` and left
`traefik.yml.j2` reading the removed `DNS_RESOLVER_1`. `config generate` then failed
for staging and prod, and CI said nothing: its drift gate runs only the generators
whose output it diffs, because CI has no SOPS key. The class is a key removed from
the values while a template still reads it, and it can recur in any generator.

So this runs the same list the command runs (`services_for`, `generator_for`), in
a copy of the repo, with each env's committed secret keys holding placeholders. The
renderer is strict, so a template that reads an undeclared name fails here.
"""

from __future__ import annotations

import ipaddress
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.cli.config import generator_for, services_for
from toolkit.config.constants import PATH_STRUCTURES
from toolkit.features import configuration

REPO = Path(__file__).resolve().parents[1]
ENVS = ("dev", "staging", "prod")


def _placeholders(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _placeholders(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_placeholders(v) for v in node]
    return "placeholder"


def _placeholder_secrets(_manager: object, path: Path) -> dict[str, Any]:
    """The committed file's own keys, each value a placeholder.

    SOPS encrypts values and leaves key names in plaintext, so this reads which
    secrets each env really declares without a key: a template reading a secret
    that env's vault lacks fails here as it would on a machine with the age key.
    """
    if not path.exists():
        return {}
    tree = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tree.pop("sops", None)
    return _placeholders(tree)


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generators write into their project root, so they run against a copy."""
    root = tmp_path_factory.mktemp("generate") / "repo"
    shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", ".worktrees", ".venv", "node_modules", "htmlcov"))
    return root


@pytest.mark.parametrize(("env", "service"), [(env, svc) for env in ENVS for svc in services_for(env)])
def test_the_generator_renders(env: str, service: str, repo_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(configuration.ConfigurationManager, "_decrypt_sops", _placeholder_secrets)
    generator = generator_for(service)
    assert generator is not None, service
    generator.project_root = repo_copy
    result = generator.generate(env)
    assert result.get("success"), f"{service} for {env}: {result.get('error')}"


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_traefik_resolvers_are_the_ssot_list(env: str, repo_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each SSOT resolver renders once, as a bare address with Traefik's `:53`."""
    monkeypatch.setattr(configuration.ConfigurationManager, "_decrypt_sops", _placeholder_secrets)
    generator = generator_for("traefik")
    assert generator is not None
    generator.project_root = repo_copy
    assert generator.generate(env).get("success")
    resolvers = configuration.ConfigurationManager(env, project_root=repo_copy).get_merged_config()["networking"][
        "public_resolvers"
    ]
    rendered = yaml.safe_load(
        (repo_copy / PATH_STRUCTURES.TRAEFIK_CONFIG_OUTPUT_DIR / env / "traefik.yml").read_text(encoding="utf-8")
    )
    found = [r["acme"]["dnsChallenge"]["resolvers"] for r in rendered["certificatesResolvers"].values()]
    # The SSOT's own shape, checked apart from the template: a scalar or an entry
    # with a port would render malformed resolvers that this list comparison mirrors.
    assert isinstance(resolvers, list) and resolvers, resolvers
    # IPv4 only: the template writes `<ip>:53`, which Traefik cannot parse for an
    # IPv6 address (it needs `[<ip>]:53`).
    for ip in resolvers:
        ipaddress.IPv4Address(ip)
    assert found and all(f == [f"{ip}:53" for ip in resolvers] for f in found)
