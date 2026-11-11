"""The forge task view's sources (CONSOLE-004): the declaration the API parses.

`infra.forge.sources` is read by the API's `forge.ParseSources` as
`forge:owner/repo` separated by commas, where `forge:owner/*` is every repository
the owner has on that forge, and it is also the webhook receiver's gate. A malformed entry stops the reconcile and makes every delivery answer 503,
so the shape is held here, before it reaches a cluster.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMON = REPO_ROOT / "infra" / "config" / "values" / "common.yaml"
KNOWN_FORGES = {"github", "gitea"}


def _sources() -> list[str]:
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["infra"]["forge"]["sources"]
    return [part.strip() for part in declared.split(",") if part.strip()]


def _api_config(env: str) -> dict:
    path = REPO_ROOT / "infra" / "k8s" / "overlays" / env / "generated" / "configmaps.yaml"
    docs = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    return next(d for d in docs if d and d["metadata"]["name"] == "api-config")


def test_every_source_is_forge_owner_repo():
    for source in _sources():
        forge, _, path = source.partition(":")
        owner, _, repo = path.partition("/")
        assert forge in KNOWN_FORGES, f"{source}: unknown forge"
        assert owner and repo and "/" not in repo, f"{source}: not forge:owner/repo"
        # The API's rule: the owner is never a wildcard, and `*` is a whole repository name or absent.
        assert "*" not in owner, f"{source}: the owner is never a wildcard"
        assert repo == "*" or "*" not in repo, f"{source}: `*` stands alone"


def test_sources_are_sorted_and_unique():
    sources = _sources()
    assert len(sources) == len(set(sources)), "duplicate source"
    assert sources == sorted(sources), "keep the list sorted so a diff shows the one repository it adds"


def test_the_platform_repository_is_read():
    sources = _sources()
    assert "github:mlorentedev/kubelab" in sources or "github:mlorentedev/*" in sources


def test_github_is_the_personal_account_only():
    # The view covers Gitea and the personal account; no organisation reaches it.
    owners = {s.partition(":")[2].partition("/")[0] for s in _sources() if s.startswith("github:")}
    assert owners == {"mlorentedev"}


def test_the_generated_configmap_carries_the_declaration_unchanged():
    # The template folds a long value over several lines (yamllint's limit); a fold
    # at a hyphen would read back with a space in a repository name.
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["infra"]["forge"]["sources"]
    for env in ("staging", "prod"):
        api = _api_config(env)
        assert api["data"]["INFRA_FORGE_SOURCES"] == declared, env


TEMPLATE = REPO_ROOT / "infra" / "k8s" / "templates" / "configmaps.yaml.j2"


def _render(value: str) -> str:
    # The generator's own environment, so the test renders what `config generate` renders.
    from toolkit.core.templating import TemplateRenderer

    template = TemplateRenderer(TEMPLATE.parent).env.get_template(TEMPLATE.name)
    rendered = template.render(apps=[{"name": "x", "env_vars": {"K": value}}], namespace="n")
    return next(d for d in yaml.safe_load_all(rendered) if d)["data"]["K"]


def test_the_template_folds_a_long_value_and_reads_it_back_unchanged():
    declared = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["infra"]["forge"]["sources"]
    long_value = ", ".join(f"github:owner/a-hyphenated-repository-name-{i}" for i in range(12))
    # The declaration is the case that once folded at `kubelab-devnode-` and read back
    # with a space in the name.
    for value in (declared, long_value):
        assert _render(value) == value


def test_the_template_never_folds_a_value_folding_would_change():
    for value in (" lead" + "x" * 120, "x" * 120 + " ", "a  b " + "x" * 120):
        assert _render(value) == value, repr(value[:12])


def test_gitea_sources_are_exactly_the_declared_repositories():
    # A repository is declared once, under the Gitea organizations; the sources may
    # neither miss one nor name one the forge reconciler does not create.
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    organizations = common["apps"]["services"]["core"]["gitea"]["organizations"]
    declared = {
        f"gitea:{org}/{repo['name']}" for org, spec in organizations.items() for repo in spec.get("repositories") or []
    }
    assert {s for s in _sources() if s.startswith("gitea:")} == declared


def test_each_overlay_carries_its_declared_gitea_address():
    # Staging has no `gitea` Service and no token, so it declares none; prod reads the
    # in-cluster Service. Compared against the values files, not a copy of them.
    def declared(name: str) -> str | None:
        values = yaml.safe_load((COMMON.parent / name).read_text(encoding="utf-8"))
        return ((values.get("infra") or {}).get("forge") or {}).get("gitea_url")

    common = declared("common.yaml")
    for env in ("staging", "prod"):
        expected = declared(f"{env}.yaml")
        expected = common if expected is None else expected
        assert _api_config(env)["data"]["INFRA_FORGE_GITEA_URL"] == expected, env
    assert common == "", "staging must not wire a Gitea reader"
    assert declared("prod.yaml"), "prod must wire the Gitea reader"
