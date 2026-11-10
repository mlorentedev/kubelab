"""The forge task view's sources (CONSOLE-004): the declaration the API parses.

`infra.forge.sources` is read by the API's `forge.ParseSources` as
`forge:owner/repo` separated by commas, and it is also the webhook receiver's
gate. A malformed entry stops the reconcile and makes every delivery answer 503,
so the shape is held here, before it reaches a cluster.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMON = REPO_ROOT / "infra" / "config" / "values" / "common.yaml"
KNOWN_FORGES = {"github", "gitea"}


def _sources() -> list[str]:
    declared = yaml.safe_load(COMMON.read_text())["infra"]["forge"]["sources"]
    return [part.strip() for part in declared.split(",") if part.strip()]


def test_every_source_is_forge_owner_repo():
    for source in _sources():
        forge, _, path = source.partition(":")
        owner, _, repo = path.partition("/")
        assert forge in KNOWN_FORGES, f"{source}: unknown forge"
        assert owner and repo and "/" not in repo, f"{source}: not forge:owner/repo"


def test_sources_are_sorted_and_unique():
    sources = _sources()
    assert len(sources) == len(set(sources)), "duplicate source"
    assert sources == sorted(sources), "keep the list sorted so a diff shows the one repository it adds"


def test_the_platform_repository_is_read():
    assert "github:mlorentedev/kubelab" in _sources()


def test_the_generated_configmap_carries_the_declaration_unchanged():
    # The template folds a long value over several lines (yamllint's limit); a fold
    # at a hyphen would read back with a space in a repository name.
    declared = yaml.safe_load(COMMON.read_text())["infra"]["forge"]["sources"]
    for env in ("staging", "prod"):
        path = REPO_ROOT / "infra" / "k8s" / "overlays" / env / "generated" / "configmaps.yaml"
        api = next(d for d in yaml.safe_load_all(path.read_text()) if d and d["metadata"]["name"] == "api-config")
        assert api["data"]["INFRA_FORGE_SOURCES"] == declared, env
